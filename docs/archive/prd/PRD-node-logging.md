> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 4
> 概要: 节点级日志系统整改

# PRD: 节点级日志系统整改

## Problem Statement

当前日志系统存在 5 个问题：
1. **Phase 名称是旧的** — `emit("phase.start", phase="before")` 掩盖了实际执行的节点（RAGVector、RAGKeyword、SystemPrompt、Merge 全部输出同一个 `"before"`）
2. **RAG 节点不输出检索信息** — 用户看不到查到了多少知识、预览是什么
3. **ReflectNode 成功时静默** — 只有失败打 warning，正常的 level+feedback 评估结果看不到
4. **MergeNode 用 DEBUG 级别** — 默认 INFO 级别看不到，切 DEBUG 又刷屏
5. **日志 DB 存储不全** — RAG chunks 和 reflect 的 analysis 分析文本没有入库

## Solution

### 1. 事件类型升级：`phase.start` → `node.start`

每个节点在 `run()` 开头 emit `node.start` + 节点名，结尾 emit `node.done` + 节点名 + 摘要数据。

```python
await emit("node.start", name="rag_vector")
# ... 执行 ...
await emit("node.done", name="rag_vector", chunks=len(results), preview=...)
```

CLI `stream_chat()` 改为监听 `node.start`/`node.done` 事件，在 verbose 模式下显示节点名和摘要。

### 2. RAG 节点增加 INFO 日志

RAGVectorNode 和 RAGKeywordNode 在检索后输出：
- 检索到的 chunk 条数
- top-1 chunk 的前 60 字预览（如果非空）
- 同时 emit `node.done` 传递这些信息

### 3. ReflectNode 增加 INFO 日志

成功评估后输出：
- level 值
- feedback 内容（截断 80 字）
- 同时 emit `node.done` 传递 level 和 feedback

### 4. 所有节点日志统一至 INFO 级别

- MergeNode 从 `logger.debug` 改为 `logger.info`
- 统一截断规则：文本摘要最多 80 字符
- `cli.py` 的 `stream_chat` 在 verbose(debug_mode[1]) 模式下显示 node 流转

### 5. 日志 DB 补充

PhaseEventLogger 补充处理：
- `node.done` 事件：记录节点名 + 输出摘要到 phase_events 表
- Extract RAG chunk 数据到 extra 字段
- Extract reflect 的 analysis 到 extra 字段

## User Stories

1. 作为开发者，我想在日志中看到实际执行的节点名（RAGVectorNode / SystemPromptNode / ReactNode），而不是旧的阶段名
2. 作为开发者，我想在 RAG 检索后看到检索到了多少条知识、预览是什么
3. 作为开发者，我想在 Reflect 评估后看到评估等级和反馈内容
4. 作为 Debug 模式用户，我不需要切到 DEBUG 级别就能看到节点流转
5. 作为运维者，我希望日志 DB 中能查到每次 RAG 检索的 chunk 数量和 Reflect 的 analysis

## Implementation Decisions

### 节点事件契约

每个节点 emit 两个事件：

```python
# 开始
await emit("node.start", name="rag_vector")

# 结束（摘要数据在 data 中）
await emit("node.done", name="rag_vector", chunks=3, preview="祥子是丰川家族...")
```

| 节点 | `node.start` name | `node.done` data |
|------|-------------------|-----------------|
| RAGVectorNode | `rag_vector` | `{chunks: int, preview: str}` |
| RAGKeywordNode | `rag_keyword` | `{chunks: int, preview: str}` |
| SystemPromptNode | `system_prompt` | `{has_facts: bool, has_retry: bool}` |
| MergeNode | `merge` | `{total_chunks: int, history_turns: int}` |
| ReactNode | `react` | `{rounds: int, tool_calls: int}` |
| AfterNode | `after` | `{emotion: str, gesture: str, length: int}` |
| ReflectNode | `reflect` | `{level: int, feedback: str, analysis: str}` |

### CLI 显示

`cli.py` `stream_chat()` 中：

```
默认模式：不显示 node.start/node.done（只显示流式文本）
verbose 模式（/debug verbose）：
  📍 RAGVector: 3 chunks
  📍 RAGKeyword: 2 chunks  
  📍 Merge: 5 chunks, 2 轮记忆
  📍 React: 2 rounds
  📍 After: emotion=calm
  📍 Reflect: level=0
```

### 日志级别

所有节点用 `logger.info()`，统一截断限制 80 字符。

### RAG Store 不改

当前 VectorStore 和 KeywordStore 只存纯文本 chunk。不改存储格式，RAG 日志只显示：
- chunk 数量
- top-1 的前 60 字预览

### log_db 扩展

PhaseEventLogger 的 `handle_event` 增加处理 `node.done`：
- 记录节点名、输出摘要到 phase_events
- RAG: extra 存 `{chunks_count: N, preview: "..."}`
- Reflect: extra 存 `{level: N, feedback: "...", analysis: "..."}`

## Testing Decisions

- 测试每个节点 emit 的 `node.start` 和 `node.done` 事件
- 测试 ReflectNode 成功时的 INFO 日志输出
- 测试 MergeNode 的 INFO 日志输出 chunk 条数
- 测试 PhaseEventLogger 能正确记录 `node.done` 事件
- 现有节点功能测试不应受影响

## Out of Scope

- VectorStore/KeywordStore 增加来源文件名存储（不改 pickle 格式）
- 日志 UI 展示优化（留待外部工具）
- 多角色支持
- Context Collapse

## Further Notes

- `phase.start` 事件保留向后兼容（目前没有外部依赖它）
- 所有修改只涉及日志输出和 DB 写入，不影响 Agent 行为逻辑
- 改动集中在 7 个 node 文件 + cli.py + logging.py
