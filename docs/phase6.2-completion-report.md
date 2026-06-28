# Phase 6.2 完成报告：Return-Diff 架构全节点迁移

> 完成日期：2026-06-28
> 状态：✅ 全部完成
> 测试：493 passed
> 变更：28 文件，+711 / -316 行

---

## 一、概述

Phase 6.2 将 BSP 图引擎中 **全部 8 个节点** 从"直接写 `ctx`"改造为"返回 `NodeResult(diff={...})`"模式。引擎层通过 `GraphEngine._apply_diff()` 统一校验并应用 diff，实现了：

- **零 mock 测试**：节点逻辑可在不构造完整 `RunContext` 的情况下独立验证
- **FIELD_WRITERS 强制执行**：越权写入在引擎层被 `PermissionError` 阻断
- **DiffHistory 持久化**：每次节点执行的 diff + inputs + duration 被异步写入独立 SQLite
- **emotion/gesture 所有权明确**：AfterNode 显式 emit `emotion.final` / `gesture.final`，`_apply_diff` 不再 auto-emit

---

## 二、架构决策

### 2.1 Plan A vs Plan B（ReactNode）

| 维度 | 方案 A（采用） | 方案 B |
|------|--------------|--------|
| 核心思路 | 流式中间态仍直接写 `ctx.emotion/gesture`，最终通过 diff 返回 | 流式中全部走闭包 nonlocal，最终合并写 diff |
| 优点 | 改动最小，流式语义不变，与 `TextMarkerStreamer` 兼容 | 完全消除 ReactNode 内所有 `ctx` 写入 |
| 缺点 | ReactNode 内仍有 `ctx.emotion/gesture/raw_text` 直写（`_stream_round` 中） | 需要重构 `TextMarkerStreamer` 和 `StreamingToolExecutor` 的 emit 签名 |
| 风险 | 中（流式直写与 diff 返回共存，但 diff 覆盖最终值） | 高（影响面大，可能引入回归） |

**决策理由**：ReactNode 是最复杂的节点，内部有流式 LLM 调用、StreamingToolExecutor 预执行、TextMarkerStreamer 实时解析等。强行消除所有 `ctx` 写入需要重构 3 个以上子模块，且收益有限。方案 A 保证 diff 返回的最终值正确覆盖 `ctx`，流式中间态的直写不影响最终一致性。

### 2.2 emotion.final / gesture.final 所有权

**问题**：原设计中 `_apply_diff` 在 emotion/gesture 字段变更时自动 emit `emotion.final` / `gesture.final`。但这与 AfterNode 的显式 emit 产生语义冲突——AfterNode 做 emotion 校验和复合规则修正后才 emit final，而 `_apply_diff` 会在 ReactNode 设置 emotion 时也 emit final。

**解决方案**：

1. **AfterNode 显式 emit**：在 `AfterNode.run()` 中，校验完成后直接 `await emit("emotion.final", value=emotion)` 和 `await emit("gesture.final", value=gesture)`
2. **`_apply_diff` 去 auto-emit**：`_apply_diff` 中 emotion/gesture 字段直接 `setattr`，不再自动 emit final 事件
3. **Agent 兜底 emit**：引擎异常兜底时，Agent 层手动 emit `emotion.final` 和 `gesture.final`

**语义**：
- `emotion.update`：流式中间态（零到多次），VTuber 实时切换表情
- `emotion.final`：diff apply 后由 AfterNode 显式发射（零或一次），用于 replay/回放

### 2.3 `_apply_diff` 重构

原设计的 `_apply_diff` 包含 emotion/gesture auto-emit 和判等逻辑。重构后：

```python
async def _apply_diff(self, ctx, diff, node_name, emit):
    for field, value in diff.items():
        # 1. FIELD_WRITERS 校验
        allowed = FIELD_WRITERS.get(field)
        if allowed and node_name not in allowed:
            raise PermissionError(...)

        # 2. 路由写入
        if field == "messages":
            ctx.messages.clear()
            ctx.messages.extend(value)
        elif field in EXTRAS_FIELDS:
            ctx.extras[field] = value
        elif field in ("emotion", "gesture"):
            # 直接 setattr，不判等，不 auto-emit
            setattr(ctx, field, value)
        else:
            # 普通字段：判等后 setattr
            current = getattr(ctx, field, None)
            if current != value:
                setattr(ctx, field, value)
```

关键变化：
- emotion/gesture 不再判等（值总是设置，由 AfterNode 负责 emit final）
- 其他字段保留判等优化（避免不必要的赋值）
- 完全移除 `await emit(f"{field}.final", value=value)` 逻辑

---

## 三、8 个节点迁移详情

### 3.1 MemoryNode

| 维度 | 详情 |
|------|------|
| 文件 | `animate/core/agent/nodes/memory_node.py` |
| reads | `{"user_input"}` |
| writes | `{"memory_facts"}` |
| diff 字段 | `{"memory_facts": list}` |
| 行为 | 从 `MemoryProvider.prefetch()` 检索事实，返回 diff；异常时返回空列表 |
| 原来 | `ctx.extras["memory_facts"] = facts` |
| 现在 | `return NodeResult(diff={"memory_facts": facts})` |

### 3.2 RAGVectorNode

| 维度 | 详情 |
|------|------|
| 文件 | `animate/core/agent/nodes/rag_vector.py` |
| reads | `{"user_input"}` |
| writes | `{"rag_vector_chunks"}` |
| diff 字段 | `{"rag_vector_chunks": list[str]}` |
| 行为 | embed HTTP 调用 + `vector_store.search()`，返回去重后的 chunks |
| 原来 | `ctx.extras["rag_vector_chunks"] = chunks` |
| 现在 | `return NodeResult(diff={"rag_vector_chunks": chunks})` |

### 3.3 RAGKeywordNode

| 维度 | 详情 |
|------|------|
| 文件 | `animate/core/agent/nodes/rag_keyword.py` |
| reads | `{"user_input"}` |
| writes | `{"rag_keyword_chunks"}` |
| diff 字段 | `{"rag_keyword_chunks": list[str]}` |
| 行为 | `keyword_store.search()` 检索，返回 chunks |
| 原来 | `ctx.extras["rag_keyword_chunks"] = chunks` |
| 现在 | `return NodeResult(diff={"rag_keyword_chunks": chunks})` |

### 3.4 SystemPromptNode

| 维度 | 详情 |
|------|------|
| 文件 | `animate/core/agent/nodes/system_prompt.py` |
| reads | `{"is_retry", "feedback", "memory_facts"}` |
| writes | `{"system_parts", "retry_feedback_injected"}` |
| diff 字段 | `{"system_parts": list[str], "retry_feedback_injected": bool}` |
| 行为 | 组装人设 + EMOTION_INSTRUCTION + 长期记忆 + 重试反馈 |
| 关键修复 | **去双写**：原代码 `ctx.extras["retry_feedback_injected"] = True`（直接写 ctx）+ 返回 diff 中也含此字段。修复后只通过 diff 返回，不再直接写 `ctx.extras` |

### 3.5 MergeNode

| 维度 | 详情 |
|------|------|
| 文件 | `animate/core/agent/nodes/merge.py` |
| reads | `{"rag_vector_chunks", "rag_keyword_chunks", "system_parts", "messages", "user_input"}` |
| writes | `{"messages"}` |
| diff 字段 | `{"messages": list[dict]}` |
| 行为 | 合并 RAG chunks（去重）→ 拼 system prompt → 插入/替换 messages[0] |
| 关键变化 | **不再 `clear()` `ctx.messages`**，只在局部构建 messages 列表返回 diff；防御纵深：仅在极端回退场景（messages 末尾缺 user）时补入 |

### 3.6 ReactNode（方案 A）

| 维度 | 详情 |
|------|------|
| 文件 | `animate/core/agent/nodes/react.py` |
| reads | `{"messages", "is_retry", "feedback", "retry_feedback_injected"}` |
| writes | `{"messages", "raw_text", "emotion", "gesture", "llm_call_count", "accumulated_usage"}` |
| diff 字段 | `{"messages": list, "raw_text": str, "emotion": str, "gesture": str\|None, "llm_call_count": int, "accumulated_usage": int}` |
| 行为 | 流式 LLM 调用 + ReAct 工具循环 + StreamingToolExecutor |
| 方案 A 特征 | 流式中间态仍直接写 `ctx.emotion/gesture/raw_text`（`_stream_round` 中），最终通过 diff 返回 6 字段覆盖 |
| retry feedback | 检查 `ctx.extras["retry_feedback_injected"]` 标记，已设置则跳过注入（避免与 SystemPromptNode 双重注入） |

### 3.7 AfterNode

| 维度 | 详情 |
|------|------|
| 文件 | `animate/core/agent/nodes/after.py` |
| reads | `{"raw_text", "emotion", "gesture"}` |
| writes | `{"final_text", "emotion", "gesture"}` |
| diff 字段 | `{"final_text": str, "emotion": str, "gesture": str\|None}` |
| 行为 | 校验 emotion（未知→calm）、校验 gesture、应用复合规则（emotion→gesture 限制）、清理残留 marker |
| 关键修复 | **空文本分支**：原代码在 `raw_text` 为空时仍设置 `ctx.final_text = ""`，但无 `emotion.final` emit。修复后空文本分支也 emit `emotion.final` 和 `gesture.final` |
| emit | 显式 emit `emotion.final` 和 `gesture.final`（所有者） |

### 3.8 ReflectNode

| 维度 | 详情 |
|------|------|
| 文件 | `animate/core/agent/nodes/reflect.py` |
| reads | `{"final_text", "user_input", "llm_call_count", "accumulated_usage"}` |
| writes | `{"is_retry", "feedback", "retry_feedback_injected", "accumulated_usage", "llm_call_count"}` |
| diff 字段 | `{"is_retry": bool, "feedback": str, "retry_feedback_injected": None\|False, "llm_call_count": int, "accumulated_usage": int}` |
| 行为 | LLM 质量评估（`<analysis>` + `<summary>` scratchpad 模式），根据 level 决定路由 |
| 路由 | `level=0-1` → `None`（通过）；`level=2-3` → `"react"`（重生成）；`level=4` → `"before"`（重检索） |
| 标记清理 | level 2-3 路由时清 `retry_feedback_injected`（`diff={..., "retry_feedback_injected": None}`），确保 ReactNode 可注入新 feedback |

---

## 四、DiffHistory 设计

### 4.1 独立 DB + 7 字段 Schema

```sql
CREATE TABLE IF NOT EXISTS diff_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    node_name TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    inputs_json TEXT,
    events_json TEXT,
    duration_ms REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_diff_trace ON diff_history(trace_id);
CREATE INDEX IF NOT EXISTS idx_diff_ts ON diff_history(created_at);
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `trace_id` | TEXT | 会话级 trace 标识，用于关联一次完整图执行 |
| `node_name` | TEXT | 节点名称（如 `react`、`after`） |
| `diff_json` | TEXT | JSON 序列化的 diff 字典 |
| `inputs_json` | TEXT | JSON 序列化的节点输入快照（`_capture_inputs` 抓取） |
| `events_json` | TEXT | JSON 序列化的事件列表（预留） |
| `duration_ms` | REAL | 节点执行耗时（毫秒） |
| `created_at` | TIMESTAMP | 自动记录时间戳 |

### 4.2 独立文件位置

```
animate/data/trace/diff_history.db    ← 独立 SQLite 文件
animate/data/logs/chat_log.db         ← 与聊天日志解耦
```

通过 `animate/core/paths.py` 的 `trace_dir()` 统一解析路径。

### 4.3 Async + WAL + Buffer

```python
class DiffHistory:
    def __init__(self, db_path="", retention_days=30, max_buffer=100):
        # PRAGMA journal_mode=WAL    → 读写并发安全
        # PRAGMA busy_timeout=5000   → 写入等待 5 秒
        # PRAGMA synchronous=NORMAL  → 性能优化
        self._lock = asyncio.Lock()  # 串行化写入

    async def record(self, node_name, diff, trace_id, inputs=None, events=None, duration_ms=0):
        async with self._lock:
            self._buffer.append(...)
            if len(self._buffer) >= self._max_buffer:
                await self._flush()
```

**设计要点**：
- **异步**：`record()` 是 async 方法，通过 `asyncio.Lock` 串行化写入
- **WAL 模式**：SQLite WAL 日志模式，允许读写并发
- **Buffer**：缓冲区满（默认 100 条）时自动 flush，引擎结束时显式 flush
- **独立 DB**：与 `ChatLogDB` 完全解耦，30 天 retention 独立管理
- **双索引**：`idx_diff_trace`（按 trace_id 查询）+ `idx_diff_ts`（按时间清理）

### 4.4 引擎集成

`GraphEngine._run_node()` 中：
1. 执行前：`_capture_inputs(node, ctx)` 抓取节点输入快照
2. 执行后：如果 `result.diff` 存在，调用 `diff_history.record()` 记录
3. 引擎结束：`diff_history.flush()` 确保缓冲区写入

`Agent` 层：`DiffHistory` 实例为单例，跨 `chat()` 调用复用。

---

## 五、Bug 修复（6 个）

### Bug 1: AfterNode 空分支无 final emit

**问题**：当 `ctx.raw_text` 为空字符串时，AfterNode 直接返回 `NodeResult(diff={"final_text": ""})`，但没有 emit `emotion.final` 和 `gesture.final`。下游 replay/回放工具无法获取最终表情状态。

**修复**：在空文本分支中添加显式 emit：
```python
if not text:
    await emit("emotion.final", value="calm")
    await emit("gesture.final", value=None)
    return NodeResult(diff={"final_text": "", "emotion": "calm", "gesture": None})
```

### Bug 2: SystemPromptNode 双写

**问题**：SystemPromptNode 在设置 `retry_feedback_injected` 时，既直接写 `ctx.extras["retry_feedback_injected"] = True`，又在返回的 diff 中包含此字段。导致 `_apply_diff` 重复写入（虽然值相同，但语义不清晰）。

**修复**：移除直接写 `ctx.extras` 的代码，只通过 diff 返回：
```python
# 修复前
ctx.extras["retry_feedback_injected"] = True
return NodeResult(diff={"system_parts": system_parts, "retry_feedback_injected": True})

# 修复后
retry_feedback_injected = True
return NodeResult(diff={"system_parts": system_parts, "retry_feedback_injected": retry_feedback_injected})
```

### Bug 3: 重复 except

**问题**：在 ReactNode 的工具执行路径中，存在重复的 `except Exception` 块，导致异常处理逻辑冗余且可能吞掉错误。

**修复**：合并重复的异常处理，确保每个 try 块有唯一的 except 处理。

### Bug 4: Agent 兜底 emit

**问题**：引擎异常兜底时（`_run_engine` 的 except 分支），直接写 `ctx.final_text`、`ctx.emotion`、`ctx.gesture` 但没有 emit `emotion.final` 和 `gesture.final`。导致下游等待 final 事件的消费者（如 VTuber 控制器）永远收不到事件。

**修复**：在 Agent 兜底路径中显式 emit final 事件：
```python
except Exception:
    ctx.final_text = "抱歉，我刚才走神了..."
    ctx.emotion = "confused"
    ctx.gesture = "tilt_head"
    await emit("emotion.final", value="confused")
    await emit("gesture.final", value="tilt_head")
```

### Bug 5: MemoryNode 死字段 data=

**问题**：MemoryNode 旧代码使用 `NodeResult(data={"memory_facts": facts})`，但 `data` 字段在 Phase 6 中已被废弃，应使用 `diff` 字段。

**修复**：改为 `NodeResult(diff={"memory_facts": facts})`。

### Bug 6: 后备记忆通路

**问题**：当 `memory_provider` 为 `None` 时，图的入口从 `memory` 变为 `__entry__`，但条件边的 router 映射中 `"before"` 指向 `"memory"`（当无 memory_provider 时应指向 `__entry__`）。

**修复**：在 `agent.py` 的 `_build_graph` 中动态路由：
```python
g.add_conditional_edge("reflect", reflect_router, {
    "before": "memory" if memory_provider else "__entry__",
    "react": "react",
    None: None,
})
```

---

## 六、边界情况处理（8 项，全部解决）

| # | 问题 | 解决方案 | 状态 |
|---|------|----------|------|
| 1 | **部分失败** | 节点失败时 diff 不应用（`_run_node` 的 try/except 中 `ctx.restore(snapshot)`），emit 已发生的事件保留在队列中 | ✅ |
| 2 | **Diff 冲突** | 引擎层通过 `FIELD_WRITERS` 校验写权限，同批并行节点的写冲突由 `_resolve_conflicts()` 检测并延迟 | ✅ |
| 3 | **流式中间态** | ReactNode 流式中直接写 `ctx.emotion/gesture`，最终 diff 覆盖（方案 A），保证最终一致性 | ✅ |
| 4 | **工具执行失败** | 工具层面 try/except 补偿，返回错误消息，diff 正常返回 | ✅ |
| 5 | **Diff 验证** | `_apply_diff` 中 `FIELD_WRITERS` 校验 + 节点 `writes` 声明，越权写入抛 `PermissionError` | ✅ |
| 6 | **Retry 机制** | `RunContext.snapshot()` + `restore()` 快照回滚，节点失败时自动恢复到执行前状态 | ✅ |
| 7 | **Diff 历史** | 独立 SQLite 文件 + WAL mode + 30 天 retention + `cleanup()` 方法 | ✅ |
| 8 | **向后兼容** | 直接迁移，不支持旧模式（所有节点已迁移至 diff 模式） | ✅ |

---

## 七、测试结果

### 7.1 总览

```
============================= 493 passed ==============================
```

**493 个测试全部通过，零失败，零跳过。**

### 7.2 测试分类

| 测试文件 | 用例数 | 覆盖内容 |
|----------|--------|----------|
| `test_diff_history.py` | 6 | DiffHistory init、record、query、buffer flush、trace 过滤、链式排序 |
| `test_node_memory_diff.py` | 5 | MemoryNode diff 返回、不写 ctx、空 facts、异常处理、next_node |
| `test_node_after_diff.py` | 8 | AfterNode diff 返回、不写 ctx、空文本、marker 清理、emotion 校验、gesture 修正 |
| `test_node_react_diff.py` | 5 | ReactNode 6 字段 diff、diff 类型、raw_text 匹配、next_node=None |
| `test_node_reflect_diff.py` | 9 | ReflectNode diff 返回、不写 ctx、路由（level 0/2/4）、llm_call_count、accumulated_usage |
| `test_engine_apply_diff.py` | 7 | `_apply_diff` 更新 ctx、extras、FIELD_WRITERS 校验、PermissionError |
| `test_nodes_after.py` | 8 | AfterNode 完整行为（emotion/gesture 校验、复合规则、marker 清理） |
| `test_nodes_merge.py` | 8 | MergeNode 去重、system prompt 插入、历史消息保留、user input 注入 |
| `test_nodes_system_prompt.py` | 6 | SystemPromptNode 人设注入、长期记忆、重试反馈 |
| `test_nodes_rag_vector.py` | 5 | RAGVectorNode embed + search、异常处理 |
| `test_nodes_rag_keyword.py` | 4 | RAGKeywordNode search、异常处理 |
| `test_nodes_reflect.py` | 7 | ReflectNode 质量评估、路由决策、emit 事件 |
| `test_merge_node_no_clear.py` | 6 | MergeNode 不清空 messages、system prompt 位置、RAG chunk 注入 |
| `test_b10_b11_b12_fix.py` | 10 | B10 user_input 去重、B11 feedback 去重、B12 compress_async |
| `test_graph_engine.py` | 7 | 图定义、BSP 调度、条件分支、fan-out/join、react 回路 |
| 其他测试文件 | ~300+ | 核心模块、工具、日志、会话、内存、权限等 |

---

## 八、文件变更总结

### 8.1 变更统计

- **总文件数**：28 个文件
- **新增行数**：+711 行
- **删除行数**：-316 行
- **净增行数**：+395 行

### 8.2 核心变更文件

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `animate/core/engine/graph.py` | 修改 | `_apply_diff` 去 auto-emit + `_capture_inputs` + DiffHistory 集成 |
| `animate/core/engine/diff_history.py` | 新增 | 独立 SQLite DiffHistory 实现（7 字段、async、WAL、buffer） |
| `animate/core/engine/context.py` | 修改 | `RunContext.snapshot()` / `restore()` + `FIELD_WRITERS` 完整声明 |
| `animate/core/engine/node.py` | 修改 | `NodeResult.diff` 字段声明 |
| `animate/core/paths.py` | 新增 | `trace_dir()` 路径函数 |
| `animate/core/agent/agent.py` | 修改 | DiffHistory 单例、Agent 兜底 emit final、条件边路由修复 |
| `animate/core/agent/nodes/memory_node.py` | 修改 | 返回 diff 而非写 ctx |
| `animate/core/agent/nodes/rag_vector.py` | 修改 | 返回 diff 而非写 ctx |
| `animate/core/agent/nodes/rag_keyword.py` | 修改 | 返回 diff 而非写 ctx |
| `animate/core/agent/nodes/system_prompt.py` | 修改 | 返回 diff + 去双写 |
| `animate/core/agent/nodes/merge.py` | 修改 | 返回 diff + 不清空 messages |
| `animate/core/agent/nodes/react.py` | 修改 | 返回 6 字段 diff（方案 A） |
| `animate/core/agent/nodes/after.py` | 修改 | 返回 diff + 显式 emit final + 空分支修复 |
| `animate/core/agent/nodes/reflect.py` | 修改 | 返回 diff + 标记清理 |

### 8.3 新增测试文件

| 文件 | 用例数 | 覆盖 |
|------|--------|------|
| `tests/test_diff_history.py` | 6 | DiffHistory 持久化 |
| `tests/test_node_memory_diff.py` | 5 | MemoryNode diff |
| `tests/test_node_after_diff.py` | 8 | AfterNode diff |
| `tests/test_node_react_diff.py` | 5 | ReactNode diff |
| `tests/test_node_reflect_diff.py` | 9 | ReflectNode diff |

---

## 九、下一步

### 9.1 Phase 7 候选方向

| 方向 | 说明 | 优先级 |
|------|------|--------|
| **DiffHistory 可视化** | 基于 `diff_history.db` 的 trace 回放工具（CLI/Web），展示每次节点执行的 diff 轨迹 | 高 |
| **DiffHistory 查询 API** | 暴露 `DiffHistory.query()` 为 Agent 工具，允许 LLM 查询历史状态 | 中 |
| **ReactNode 方案 B** | 消除 ReactNode 内所有 `ctx` 直写，完全走 diff（需重构 TextMarkerStreamer） | 低 |
| **Diff 合并策略** | 支持多节点并行写入同一字段时的自动合并（当前是延迟冲突节点） | 中 |
| **Diff 审计日志** | 将 DiffHistory 与 LogCollector 集成，统一审计入口 | 低 |

### 9.2 新功能候选

| 功能 | 说明 | 复杂度 |
|------|------|--------|
| **Diff 回放工具** | 读取 `diff_history.db`，按 trace_id 重放节点执行序列 | 中 |
| **状态检查点恢复** | 基于 DiffHistory 的手动状态恢复（调试用） | 中 |
| **Diff 统计面板** | 节点执行耗时、diff 大小、写入频率统计 | 低 |
| **增量 Diff** | 支持 diff 只包含变更字段（当前返回全量 diff） | 高 |

### 9.3 技术债务

| 项目 | 说明 |
|------|------|
| ReactNode 流式直写 | 方案 A 保留了 `_stream_round` 中 `ctx.emotion/gesture` 的直写，长期应迁移 |
| `data` 字段废弃 | `NodeResult.data` 仍保留（向后兼容），但所有节点已迁移至 `diff`，可标记 `@deprecated` |
| DiffHistory events_json | Schema 中有 `events_json` 字段但未使用，可扩展为 emit 事件记录 |
| 测试覆盖率 | 493 个测试覆盖主要路径，但 DiffHistory 的并发场景（多 trace 同时写入）测试不足 |

---

## 十、总结

Phase 6.2 完成了 AniMate BSP 图引擎从"直接写 ctx"到"返回 diff"的全量迁移：

1. **8 个节点全部迁移**：MemoryNode、RAGVectorNode、RAGKeywordNode、SystemPromptNode、MergeNode、ReactNode、AfterNode、ReflectNode
2. **6 个 Bug 修复**：AfterNode 空分支、SystemPromptNode 双写、重复 except、Agent 兜底 emit、MemoryNode 死字段、后备记忆通路
3. **DiffHistory 独立实现**：7 字段 schema、async + WAL + buffer、独立 SQLite 文件、30 天 retention
4. **493 个测试全部通过**：零失败，覆盖 diff 返回、FIELD_WRITERS 校验、边界情况
5. **28 个文件变更**：+711 / -316 行，架构清晰，代码质量高

Return-Diff 架构已完全就绪，为后续的 trace 回放、状态调试、Diff 可视化等高级功能奠定了坚实基础。
