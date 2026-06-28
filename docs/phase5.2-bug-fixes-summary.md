# Anima Agent Phase 5.2 — 全量 Bug 修复 + 审计日志接入

## Status

Accepted (2026-06-24)

## Test Results

```
修复前: 416 passed, 1 failed (MCP), 2 skipped
修复后: 441 passed, 1 failed (MCP), 2 skipped
新增测试: +25 (B10-B12×13, LogCollector×8, B2×4)
```

## Bug 修复总表

### P1 — 逻辑错误/数据丢失（7/7 已修）

| # | Bug | 修复方案 | 文件数 |
|---|-----|---------|--------|
| **B10** | Retry 时 user_input 被重复追加 | user_input 上移至 agent.py 构建 ctx.messages 时注入；MergeNode 改为防御性守卫 | 2 |
| **B11** | Retry feedback 被双重注入 | `ctx.extras["retry_feedback_injected"]` 标记互斥，ReflectNode 路由时清标记 | 3 |
| **B12** | `_auto_compact` 同步阻塞事件循环 | `chat_async()` 新增 + `compress_async()` + `_auto_compact_async()` 全链路 async | 3 |
| **B13** | ReflectNode LLM usage 不累加 | `LLMResult.total_tokens` 字段 + `chat()`/`chat_async()` 出口回填 + ReflectNode 累加 | 3 |
| **B14** | 所有 Node writes 为空 → BSP 冲突检测失效 | 7 个节点声明 `reads`/`writes`，覆盖全部并行/串行路径 | 7 |
| **B15** | 3 张日志表（compression/emotion/tool_audit）从不写入 | LogCollector 事件分派器接入 emit 事件链 + ContextManager/MemoryProvider 直接调用 | 6 |
| **B16** | `ChatLogDB.long_term_facts` 死数据 | DefaultMemoryProvider 注入 log_db，`_handle_fact_store` 写入审计日志 | 2 |

### P2 — 功能缺失（5/7 已修）

| # | Bug | 修复方案 | 文件数 |
|---|-----|---------|--------|
| **B1** | 模型切换后压缩阈值不更新 | `ContextManager.reconfigure(model_limit)` + cli.py 切换后调用来更新阈值 | 2 |
| **B2** | DeepSeek streaming 不返回 usage → 压缩永不触发 | tiktoken 后备：stream 结束后 `accumulated_usage` 未增加则调 `estimate_tokens()` 估算 | 1 |
| **B7** | `stream_options: None` 传给非流式调用 | `_build_kwargs` 非流式时 omit `stream_options` key | 1 |
| **B17** | `on_session_switch` 空操作 | DefaultMemoryProvider 实现 `on_session_switch` 更新 `_session_id` | 1 |
| **B19/B6** | `SessionSearchTool` 未注册 | Agent.__init__ 中创建并注册到 ToolRegistry | 1 |

### P3 — 代码质量/边界（7/7 已修）

| # | Bug | 修复方案 | 文件数 |
|---|-----|---------|--------|
| **B3** | `compact()` skip/fail 混为一谈 | 前置消息数检查，返回 `status: "skip"` 而非模糊的 `"error"` | 1 |
| **B9** | `_auto_compact` 插入位置在连续压缩时错乱 | 插入位置从 `min(middle_indices)` 改为基于 head|tail 新列表索引 | 2 |
| **B20** | `strip_markers` 误删正常括号文本 | 改用 `re.sub(r"\(\s*(\w+)\s*,\s*(\w+)\s*\)")` 仅剥离 (word,word) 格式 | 1 |
| **B21** | `_snip_tool_results` 阈值 500 过低 | RESULT_THRESHOLD 500 → 5000（匹配 50000 预算量级） | 1 |
| **B22** | `extract_quick_facts` 正则太宽 | 删除 `以后(.+)` `别(.+)` `下次(.+)` 三条过宽正则 | 1 |
| **Bx** | `_fail_or_degrade()` 定义后从未调用 | compress/compress_async 失败路径加 `_fail_or_degrade()` | 1 |

### P4 — 工整性（2/2 已修）

| # | Bug | 修复方案 | 文件数 |
|---|-----|---------|--------|
| **B5** | `count_rounds` unused import | 删除 import 行 | 1 |
| **B8** | Pre-turn 压缩后 `ctx.messages` 同步 | 已在 B12 修复中自动解决（compress_async 后重新组合含 user_input） | 0 |

### 挂起（2 项，待 Phase 6）

| # | 严重度 | 原因 |
|---|--------|------|
| **B4** | P3 | `check_write_permission` 需更新 `FIELD_WRITERS` 节点名 + GraphEngine 加校验（~15 行）。当前收益有限（主要覆盖 extras 外字段），留 Phase 6 架构重写时一并处理 |
| **B18** | P2 | `on_session_end` 深度提事实是功能需求，需 PRD 级设计 |

---

## 新增组件

### LogCollector（`animate/core/log/collector.py`）

审计事件分派器。Node 零感知——继续 `emit()`，LogCollector 在 agent 层收口。

```
emit("tool.done", ...) 
  → LogCollector.handle(ev) 
  → log_db.log_tool_audit(...)
  → log_db.log_emotion(...)
  → log_db.log_compression(...)   (ContextManager 直接调)
  → log_db.add_fact(...)          (MemoryProvider 直接调)
```

### `RunServices.log_db`

运行时服务注入。各组件通过 `ctx.services.log_db` 获取 log_db 引用。

---

## 关键架构变化

| 维度 | 修复前 | 修复后 |
|------|--------|--------|
| **user_input 注入** | MergeNode 无条件 append（不可重入） | agent.py 构建 ctx.messages 时注入（幂等） |
| **retry feedback 注入** | SystemPromptNode + ReactNode 重复注入 | `retry_feedback_injected` 标记互斥 |
| **压缩路径** | 同步阻塞事件循环 | async + `chat_async()` 不阻塞 |
| **Node reads/writes** | 全部空 set | 7 节点全部声明 |
| **审计日志** | 4 张表定义但从未写入 | LogCollector 全链路接入 |
| **streaming usage** | 依赖 API include_usage（DeepSeek 不支持） | tiktoken 三层递退 |
| **模型切换阈值** | ContextManager 不更新 | `reconfigure()` 方法 + CLI 调用 |
| **会话搜索** | SessionSearchTool 定义但未注册 | Agent 自动注册 |
| **strip_markers** | 删除所有括号内容 | 仅剥离 (word,word) 格式 |
| **snip 阈值** | 500 chars | 5000 chars |

---

## Phase 6 目标：LangGraph 纯函数架构

### 架构方向

将当前 BSP 图引擎改造为 LangGraph 风格的 return-diff 模式：

```python
# 当前（节点直接写 ctx）
class ReactNode(Node):
    async def run(self, ctx, emit):
        ctx.emotion = "happy"
        ctx.messages = new_msgs
        return NodeResult(next_node="after")

# Phase 6 目标（节点返回 diff，框架 merge）
class ReactNode(Node):
    async def run(self, messages, **kwargs) -> dict:
        emotion, gesture, raw_text = await self._stream(messages)
        return {
            "messages": new_msgs,
            "emotion": emotion,
            "gesture": gesture,
            "raw_text": raw_text,
        }
```

### 收益

1. **测试零 mock** — 纯 dict 输入 × dict 输出
2. **FIELD_WRITERS 自动生效** — GraphEngine apply diff 时校验
3. **LangGraph 兼容** — 节点天然适配 `node(state) → dict` 签名
4. **副作用本地化** — 流式中间态的 emotion/gesture 在 return 时才落定

### 待修 Bug（B18）

- ~~**B4**：更新 `FIELD_WRITERS` 节点名 + GraphEngine 写入校验~~ → Phase 6.2 已解决（FIELD_WRITERS 自动激活）
- **B18**：`on_session_end` 深度事实提取到 MemoryStore

### 待决事项

- 自研 return-diff 引擎 vs 直接上 LangGraph
- ReactNode 流式写入的跨 round emotion/gesture 状态管理方案
