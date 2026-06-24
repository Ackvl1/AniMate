> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 4
> 概要: 短期记忆重构与上下文管理

# PRD: 短期记忆重构与上下文管理系统

## Problem Statement

AniMate 的短期记忆系统存在多个问题：

1. **两套消息源不一致** — `MemoryManager` 持有独立的消息列表，MergeNode 复制到 `ctx.messages`，写完后再写回。两套数据可能不同步。
2. **FIFO 硬截断，无 token 感知** — `ConversationMemory` 按 `max_turns` 丢弃旧消息，不感知实际 token 消耗，浪费 1M context 容量。
3. **MergeNode `clear()` 破坏外部干预** — 每轮 `ctx.messages.clear()` 抹掉了任何在图外对消息列表做的预处理（如压缩）。
4. **消息丢弃不对称** — `pop(0)` 假设 user/assistant 成对出现，工具调用、重试等非对称消息序列会错丢。
5. **没有压缩机制** — 长对话（500+ 轮）无法在不丢失上下文的情况下继续。
6. **没有内容保护策略** — 所有消息地位平等，关键指令和最近的对话没有优先保留权。
7. **角色扮演的 emotion 状态不在 messages 中** — 压缩后情绪历史丢失。

## Solution

采用 Claude Code 启发的**消息即记忆**架构，配合渐进式压缩管道：

1. **单一消息源** — `self._messages` 是 Agent 持有的唯一短期记忆，`ctx.messages` 直接引用它，无复制。
2. **Token 感知的压缩触发** — 基于 tiktoken 估算消息总 token 数，达到阈值（默认 70% context）时触发压缩。
3. **Protect-Head + Protect-Tail 压缩策略** — 保护 system prompt + 前 5 轮 + 后 10 轮，中间区域可压缩。
4. **三层渐进压缩** — L1 Snip（工具结果裁剪）→ L4 Auto-Compact（LLM 摘要），从低成本到高成本。
5. **Archive 独立存储** — 被压缩的原始消息存入独立 Archive（FTS5 SQLite），不进 RAG VectorStore。
6. **可配置策略参数** — head/tail 轮数、压缩阈值、token 估算方式均可从 config.yaml 配置。
7. **Emotion 日志进入压缩范围** — emotion 变化记录在 ctx 中，压缩时写入摘要 prompt。
8. **用户主动压缩** — CLI `/compact` 命令。

## User Stories

1. 作为用户，我希望聊到 700+ 轮后系统能自动压缩历史，而不是报错或丢失上下文。
2. 作为用户，我希望压缩后最近的 10 轮对话内容仍然完整，不影响当前对话连贯性。
3. 作为用户，我希望系统提示 `⏳ 正在压缩对话历史...`，让我知道它在忙。
4. 作为用户，我希望压缩后系统仍然记得我在对话早期表达的偏好和约定。
5. 作为用户，我希望可以手动 `/compact` 触发压缩，不等自动触发。
6. 作为用户，我希望压缩时角色情绪变化的历史被保留在摘要中。
7. 作为开发者，我希望 MergeNode 不再 `clear()` 消息列表，让外部预处理（压缩）不会失效。
8. 作为开发者，我希望短期记忆和长期记忆解耦，短期只管 messages，长期只管 facts。
9. 作为开发者，我希望丢弃消息时按轮次对称丢弃或内容加权，不按位置猜测。
10. 作为开发者，我希望 token 估算使用 tiktoken（`cl100k_base`），对中日英准确。
11. 作为开发者，我希望压缩阈值、head/tail 轮数是可配置的，不用改代码。
12. 作为开发者，我希望压缩能够多次执行，每次压缩中间区域，保护首尾。
13. 作为开发者，我希望压缩管道是可扩展的（策略接口），未来可以加新的压缩策略。
14. 作为开发者，我希望被压缩的原始消息进入 Archive 存储，不丢失。
15. 作为开发者，我希望 Archive 与 RAG 的 VectorStore 分离，不污染知识检索质量。
16. 作为开发者，我希望自动压缩显示压缩次数的 progress 标识。
17. 作为开发者，我希望压缩在每轮 chat_stream() 开头同步执行，不引入并发复杂度。
18. 作为开发者，我希望压缩失败时有降级策略（L1 Snip），连续失败 3 次才报错。

## Implementation Decisions

### 模块变更

**修改：`animate/core/agent/agent.py`**
- Agent 新增 `self._messages: list[dict]` 作为唯一短期记忆
- `chat_stream()` 中 `ctx.messages = self._messages`（引用，非复制）
- Post-turn 直接 `self._messages.append(asst_response)`
- 接入 ContextManager：`update_from_response()` → `need_compress()` → `compress()`
- Reset 时先触发 `on_session_end` 再清空 messages
- 引入增量 token 计数器（TokenCounter），每轮只 encode 新增消息

**修改：`animate/core/agent/nodes/merge.py`**
- 不再 `ctx.messages.clear()`
- 检查 `messages[0]` 是否为 system prompt：是则替换，否则 insert(0)
- 追加 user input 到末尾

**修改：`animate/core/memory/conversation.py`**
- 简化为纯工具函数：`count_rounds()`、`estimate_tokens()`、`find_message_boundaries()`
- 不再持有消息列表本身

**新建：`animate/core/context/__init__.py`**
- 包入口

**新建：`animate/core/context/manager.py`**
- `ContextManager` 类：
  - `__init__(model_limit, threshold, compact_reserve, head_rounds, tail_rounds)`
  - `update_from_response(usage)`
  - `need_compress() → bool`
  - `compress(messages, ctx)`
  - `_select_head(messages) → set[int]`
  - `_select_tail(messages) → set[int]`
  - `_snip_tool_results(messages, indices)`
  - `_auto_compact(messages, head, tail, middle, ctx)`
  - `reset()`
- 所有参数可从 config.yaml 配置
- `_select_head`: 所有 system prompt + 最早 head_rounds 轮非 system 消息
- `_select_tail`: 从末尾向前，覆盖至少 tail_rounds 轮完整对话 + 最后一条消息
- 轮数保护：按 assistant 消息计数，不是按条数
- 中文 token 估算：使用 tiktoken `cl100k_base`，兜底 `len/1.5`
- 压缩次数计数，显示 `🗜️ 正在压缩对话历史 [#N]...`
- Emotion 日志：从 ctx.extras.emotion_log 读取，注入摘要 prompt

**新建：`animate/core/context/strategies/snip.py`**
- L1 策略：扫描 middle 中的 tool 类型消息，content 超过阈值替换为占位符

**新建：`animate/core/context/strategies/compact.py`**
- L4 策略：LLM 调用生成结构化摘要
- 摘要 prompt 包含：已解决事项、活跃事项、用户偏好、情绪变化记录、关键决策
- 支持多次压缩（摘要的再摘要）

**新建：`animate/core/context/token_counter.py`**
- 增量 token 计数器：每轮只 encode 新增消息
- `add_message(msg)`, `remove_messages(count)`, `rebuild(messages)`, `total`
- 使用 tiktoken `cl100k_base`

**新建：`animate/core/memory/archive.py`**
- ArchiveStore：独立的 SQLite + FTS5 存储
- `store_compressed(messages)` — 被压消息入库
- `search(query, limit) → list[dict]` — FTS5 全文检索
- 与 VectorStore 分离，不进 RAG 管道
- MemoryNode 检索时可选查询 archive，score 打折

**新建：`animate/core/agent/nodes/memory_node.py`**
- MemoryNode（已有设计，但在短期记忆 PRD 中只声明接口，长期记忆 PRD 再完整实现）

### 技术细节

- Token 估算依赖: `pip install tiktoken`
- 摘要使用主模型的 `chat()` 接口（非流式）
- 压缩失败连续 3 次才报错，前 2 次降级为 Snip + 跳过
- 不支持多实例并发压缩（当前单线程 asyncio，安全）
- 压缩时 CLI 输出状态：「🗜️ 正在压缩对话历史 [#1] ...」
- 不支持 session 旋转（第一期不做）
- `_select_tail` 保证即使只有 1 条消息也保护最后一条

### 压缩策略

```
need_compress():
  │
  ├── No → 不处理
  │
  └── Yes → compress():
       ├── _select_head()     # system + 最早 N 轮
       ├── _select_tail()     # 最近 N 轮
       ├── middle = 其余
       │
       ├── L1 Snip:           # 替换大 tool_result
       │   for i in middle:
       │     if role==tool & content>500:
       │       content = "[工具结果压缩]"
       │
       ├── 仍需压缩? → L4:
       │   _auto_compact():
       │     - 构造结构化摘要 prompt（含 emotion_log）
       │     - LLM 调用
       │     - archive.store(原始 middle)
       │     - 替换 middle 为摘要消息
       │
       └── archive original middle messages
```

## Testing Decisions

### 测试原则

- 测试行为，不测实现细节
- 使用真实 tiktoken 编码（不 mock），用短文本验证 token 估算
- ContextManager 使用 mock LLM 测试压缩逻辑，不依赖真实 API
- MergeNode 测试验证 messages 不被 clear，system prompt 正确插入
- Archive 使用 `:memory:` SQLite 测试
- TokenCounter 测试验证增量计数与全量计数一致

### 测试模块

| 测试文件 | 测试内容 |
|---------|---------|
| `tests/test_context_manager.py` | 初始化参数、need_compress 阈值、_select_head/tail 边界、< 20 轮不压缩、middle 为空不压缩、L1 Snip、压缩失败降级、连续 3 次报错、emotion_log 传递、reset、配置覆盖 |
| `tests/test_token_counter.py` | 增量添加、全量重建、与 tiktoken 一致性、中/日/英混合 |
| `tests/test_merge_node_no_clear.py` | messages 不 clear、已有 system prompt 替换、无 system prompt 时 insert(0)、不破坏已有非 system 消息 |
| `tests/test_short_term_messages.py` | Agent 初始 messages 为空、chat_stream 后追加回复、跨轮累积、reset 清空、后压缩不丢失历史 |
| `tests/test_archive_store.py` | store_compressed、FTS5 search、与 VectorStore 分离 |

### 预期测试数

约 35-45 个新测试。

## Out of Scope

- 长期记忆（MemoryNode、事实提取、fact_store 工具）— 后续 PRD
- 序列化（session JSONL、断点续跑）— 后续 PRD
- RAG 重构 — 后续 PRD
- session 旋转 — 第一期不做
- 异步压缩 — 第一期不做
- 多实例并发锁 — 当前不需要
- Unity/WebSocket 集成 — Phase 5+
- Archive 进 RAG VectorStore — 不污染 RAG，Archive 独立 FTS5
- 用户自定义压缩 prompt — 后续版本

## Further Notes

- 本 PRD 只关注短期记忆 + 上下文管理。长期记忆、序列化、RAG 重构各自独立 PRD。
- Archive 的检索（MemoryNode）在长期记忆 PRD 中完成，本 PRD 只建存储。
- tiktoken 的 `cl100k_base` 兼容 DeepSeek V4、GPT-4、通义等主流模型。
- 压缩 prompt 的角色扮演定制（`RoleplayCompactStrategy`）后续版本做插件化。第一期用通用 prompt。
- 压缩时显示的压缩次数从 1 开始递增（`#1`, `#2`...），表示这是会话中第 N 次压缩。
