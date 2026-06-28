# Phase 6 实施手册：Return-Diff 架构重构

> 最后更新：2026-06-26
> 状态：Phase 6.1 完成，Phase 6.2 进行中（3/8 节点已迁移）

---

## 一、目标

将 BSP 图引擎从"节点直接写 ctx"改造为"节点返回 diff，引擎统一 apply"。

| 维度 | 当前 | Phase 6 |
|------|------|---------|
| 节点写入 | 直接写 ctx | 返回 diff |
| 引擎职责 | 只做调度 | 调度 + apply diff |
| 流式输出 | 节点内 emit | 保持不变 |
| 工具执行 | 即时副作用 | 保持不变 |
| FIELD_WRITERS | 未强制 | 引擎层强制 |

---

## 二、核心设计

### 2.1 NodeResult 扩展

```python
@dataclass
class NodeResult:
    next_node: str | None = None
    diff: dict[str, Any] | None = None  # 新增，废弃 data 字段
```

### 2.2 引擎 apply 逻辑

```python
EXTRAS_FIELDS = {
    "rag_vector_chunks", "rag_keyword_chunks",
    "system_parts", "memory_facts", "retry_feedback_injected",
}

async def _apply_diff(self, ctx, diff, node_name, emit):
    for field, value in diff.items():
        # FIELD_WRITERS 统一校验
        allowed = FIELD_WRITERS.get(field)
        if allowed and node_name not in allowed:
            raise PermissionError(f"Node '{node_name}' cannot write '{field}'")
        
        if field == "messages":
            ctx.messages.clear()
            ctx.messages.extend(value)
        elif field in EXTRAS_FIELDS:
            ctx.extras[field] = value
        else:
            current = getattr(ctx, field, None)
            if current != value:
                setattr(ctx, field, value)
                if field in ("emotion", "gesture"):
                    await emit(f"{field}.final", value=value)
```

### 2.3 FIELD_WRITERS 全量对齐

```python
FIELD_WRITERS = {
    "user_input": {"__entry__"},
    "messages": {"system_prompt", "merge", "react"},
    "raw_text": {"react"},
    "final_text": {"after"},
    "emotion": {"system_prompt", "react", "after"},
    "gesture": {"react", "after"},
    "llm_call_count": {"react", "reflect"},
    "accumulated_usage": {"react", "reflect"},
    "is_retry": {"reflect"},
    "feedback": {"reflect"},
    "retry_feedback_injected": {"system_prompt", "reflect"},
    "rag_vector_chunks": {"rag_vector"},
    "rag_keyword_chunks": {"rag_keyword"},
    "system_parts": {"system_prompt"},
    "memory_facts": {"memory"},
}
```

### 2.4 节点重构模式

**简单节点（AfterNode）**：

```python
class AfterNode(Node):
    reads = {"raw_text", "emotion", "gesture"}
    writes = {"final_text", "emotion", "gesture"}
    
    async def run(self, ctx, emit) -> NodeResult:
        # 读取 ctx（只读）
        text = ctx.raw_text.strip()
        emotion = ctx.emotion
        gesture = ctx.gesture
        
        # 处理逻辑
        cleaned = TextMarkerStreamer.strip_markers(text)
        
        # 校验 + 复合规则
        # ...
        
        # 返回 diff
        return NodeResult(
            next_node="reflect",
            diff={"final_text": cleaned, "emotion": emotion, "gesture": gesture}
        )
```

**复杂节点（ReactNode）**：

```python
class ReactNode(Node):
    reads = {"messages", "is_retry", "feedback", "retry_feedback_injected",
             "llm_call_count", "accumulated_usage"}
    writes = {"messages", "raw_text", "emotion", "gesture",
              "llm_call_count", "accumulated_usage"}
    
    async def run(self, ctx, emit) -> NodeResult:
        # 局部变量（不写 ctx）
        messages = list(ctx.messages)
        final_emotion = ctx.emotion
        final_gesture = ctx.gesture
        llm_call_count = ctx.llm_call_count  # 读初始值
        accumulated_usage = ctx.accumulated_usage
        
        async def tracking_emit(type, **data):
            nonlocal final_emotion, final_gesture
            if type == "emotion.update":
                final_emotion = data.get("emotion", final_emotion)
                final_gesture = data.get("gesture", final_gesture)
            await emit(type, **data)
        
        # 流式调用 LLM + 工具执行
        # 每轮 LLM 调用：
        llm_call_count += 1
        # usage 累加：
        accumulated_usage += total
        
        # 返回 diff（绝对值）
        return NodeResult(
            next_node="after",
            diff={
                "messages": messages,
                "raw_text": full_text,
                "emotion": final_emotion,
                "gesture": final_gesture,
                "llm_call_count": llm_call_count,
                "accumulated_usage": accumulated_usage,
            }
        )
```

### 2.5 Checkpoint 机制（异常恢复）

```python
class GraphEngine:
    def __init__(self, ...):
        self._checkpoints: dict[str, dict] = {}
    
    async def _run_node(self, name, ctx, emit):
        """执行单个节点。
        
        NOTE: checkpoint 假设此节点不在并行批次中，
        或并行节点自行 try/except 兜底不抛异常
        （现有 RAGVector/Keyword/SystemPrompt 均如此）。
        """
        node = self._graph.nodes.get(name)
        if node is None:
            return
        
        _emit = emit if emit is not None else _noop_emit
        self._checkpoints[name] = ctx.snapshot()
        
        try:
            result = await node.run(ctx, _emit)
            self._node_results[name] = result
            if result.diff:
                await self._apply_diff(ctx, result.diff, name, emit)
        except Exception as e:
            ctx.restore(self._checkpoints[name])
            logger.error(f"Node {name} failed, restored: {e}")
            raise
```

### 2.6 RunContext snapshot/restore

```python
class RunContext:
    def snapshot(self) -> dict:
        """返回可序列化的数据字段快照"""
        return {
            "user_input": self.user_input,
            "messages": list(self.messages),
            "emotion": self.emotion,
            "gesture": self.gesture,
            "raw_text": self.raw_text,
            "final_text": self.final_text,
            "is_retry": self.is_retry,
            "feedback": self.feedback,
            "llm_call_count": self.llm_call_count,
            "accumulated_usage": self.accumulated_usage,
            "extras": dict(self.extras),
        }
    
    def restore(self, snapshot: dict):
        """从快照恢复数据字段"""
        for key, value in snapshot.items():
            if key == "messages":
                self.messages.clear()
                self.messages.extend(value)
            elif key == "extras":
                self.extras.clear()
                self.extras.update(value)
            else:
                setattr(self, key, value)
```

### 2.7 DiffHistory 持久化

**文件位置**：`animate/core/log/log_db.py`（与 ChatLogDB 一起）

**SQL Schema**：

```sql
CREATE TABLE IF NOT EXISTS diff_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    node_name TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    inputs_json TEXT,
    events_json TEXT,
    duration_ms REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_diff_trace ON diff_history(trace_id);
```

**Python 实现**（放在 `log_db.py`）：

```python
class DiffHistory:
    def __init__(self, db: "ChatLogDB", max_buffer: int = 100):
        self._db = db
        self._buffer: list[dict] = []
        self._max_buffer = max_buffer
    
    async def record(self, node_name: str, diff: dict, trace_id: str,
                     inputs: dict = None, events: list = None,
                     duration_ms: float = 0):
        """记录 diff 历史"""
        self._buffer.append({
            "trace_id": trace_id,
            "node_name": node_name,
            "diff": diff,
            "inputs": inputs or {},
            "events": events or [],
            "duration_ms": duration_ms,
        })
        if len(self._buffer) >= self._max_buffer:
            await self._flush()
    
    async def _flush(self):
        """批量写入数据库"""
        for entry in self._buffer:
            self._db.log_diff_history(**entry)
        self._buffer.clear()
    
    async def flush(self):
        """引擎结束时调用"""
        await self._flush()
```

**ChatLogDB 新增方法**：

```python
class ChatLogDB:
    def _init_tables(self):
        # ... 现有表 ...
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS diff_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                diff_json TEXT NOT NULL,
                inputs_json TEXT,
                events_json TEXT,
                duration_ms REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_diff_trace ON diff_history(trace_id)"
        )
    
    def log_diff_history(self, trace_id: str, node_name: str,
                         diff: dict, inputs: dict = None,
                         events: list = None, duration_ms: float = 0):
        self._conn.execute(
            "INSERT INTO diff_history (trace_id, node_name, diff_json, "
            "inputs_json, events_json, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (trace_id, node_name, json.dumps(diff),
             json.dumps(inputs) if inputs else None,
             json.dumps(events) if events else None,
             duration_ms)
        )
        self._conn.commit()
    
    def query_diff_history(self, trace_id: str = None,
                           limit: int = 50) -> list[dict]:
        if trace_id:
            rows = self._conn.execute(
                "SELECT * FROM diff_history WHERE trace_id = ? "
                "ORDER BY id DESC LIMIT ?", (trace_id, limit)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM diff_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]
```

### 2.8 引擎集成 + inputs 抓取

```python
EXTRAS_FIELDS = {
    "rag_vector_chunks", "rag_keyword_chunks",
    "system_parts", "memory_facts", "retry_feedback_injected",
}

class GraphEngine:
    def __init__(self, ..., diff_history: DiffHistory = None):
        self._diff_history = diff_history
    
    def _capture_inputs(self, node, ctx) -> dict:
        """抓取节点输入（区分 extras 字段）"""
        inputs = {}
        for f in (node.reads or []):
            if f in EXTRAS_FIELDS:
                inputs[f] = ctx.extras.get(f)
            else:
                inputs[f] = getattr(ctx, f, None)
        return inputs
    
    async def _run_node(self, name, ctx, emit):
        node = self._graph.nodes.get(name)
        if node is None:
            return
        
        _emit = emit if emit is not None else _noop_emit
        self._checkpoints[name] = ctx.snapshot()
        
        # 抓取 inputs（用于 DiffHistory）
        inputs = self._capture_inputs(node, ctx)
        
        t0 = time.monotonic()
        try:
            result = await node.run(ctx, _emit)
            self._node_results[name] = result
            if result.diff:
                await self._apply_diff(ctx, result.diff, name, emit)
                # 记录 diff 历史
                if self._diff_history:
                    await self._diff_history.record(
                        name, result.diff, ctx.trace_id,
                        inputs=inputs,
                        duration_ms=(time.monotonic() - t0) * 1000
                    )
        except Exception as e:
            ctx.restore(self._checkpoints[name])
            logger.error(f"Node {name} failed, restored: {e}")
            raise
    
    async def run(self, ctx, emit):
        # ... 现有循环 ...
        # 循环结束后 flush
        if self._diff_history:
            await self._diff_history.flush()
        return self
```

### 2.9 创建路径

```python
# graph.py - Graph.create_engine 加参数
class Graph:
    def create_engine(self, max_steps: int = 50,
                      diff_history: DiffHistory = None) -> GraphEngine:
        return GraphEngine(self, max_steps=max_steps,
                          diff_history=diff_history)

# agent.py - Agent.chat_stream 创建 DiffHistory
async def chat_stream(self, user_input):
    # ... 现有逻辑 ...
    
    # 创建 DiffHistory（复用 log_db）
    from animate.core.log.log_db import DiffHistory
    diff_history = None
    if self._log_db:
        diff_history = DiffHistory(self._log_db)
    
    engine = self._graph.create_engine(
        max_steps=MAX_GRAPH_STEPS,
        diff_history=diff_history
    )
    # ...
```

### 2.10 Diff 删除语义

**问题**：ReflectNode 使用 `ctx.extras.pop("retry_feedback_injected")` 删除 key，但 diff 模型只支持 set，不支持 delete。

**解决方案**：用 `False` 代替 `pop()`，利用 falsy 语义。

```python
# ReflectNode 当前代码
ctx.extras.pop("retry_feedback_injected", None)  # 删除 key

# Phase 6 改为
diff={"retry_feedback_injected": False}  # False = 已消费

# SystemPromptNode 检查（不需要改）
if ctx.is_retry and ctx.feedback and not ctx.extras.get("retry_feedback_injected"):
    # False 是 falsy → not False → True → 注入 feedback
    ...
```

**但 SystemPromptNode 的写入需要改**：

```python
# SystemPromptNode 当前代码（直接写 extras）
ctx.extras["retry_feedback_injected"] = True

# Phase 6 改为（返回 diff）
return NodeResult(
    next_node="merge",
    diff={
        "system_parts": system_parts,
        "retry_feedback_injected": True,  # 通过 diff 返回
    }
)
```

**语义**：
- `True` = 已注入 feedback
- `False` = 已消费，可以重新注入
- key 不存在 = 未处理，可以注入

三种情况都满足 `not ctx.extras.get(...)` 为 True 的条件。

### 2.11 Agent 层兜底（唯一绕过 diff 的通道）

```python
# agent.py - 引擎异常兜底
async def _run_engine():
    try:
        await engine.run(ctx, emit=emit)
    except Exception:
        # 引擎崩溃兜底：直接写 ctx，绕过 diff 机制
        # 因为引擎可能处于不确定状态，不能再调 _apply_diff
        # 这是唯一允许绕过 diff 的通道
        ctx.final_text = "抱歉，我刚才走神了..."
        ctx.emotion = "confused"
        ctx.gesture = "tilt_head"
```

**设计原则**：Agent 层兜底是唯一允许直接写 ctx 的场景。其他所有状态变更必须走 diff。

### 2.12 消费端事件语义

| 事件 | 时机 | 语义 |
|------|------|------|
| emotion.update | 流式中（零到多次） | 中间态，VTuber 实时切换表情 |
| emotion.final | diff apply 后（零或一次） | 最终态，用于 replay/回放 |

---

## 三、边界情况处理

| # | 问题 | 解决方案 |
|---|------|----------|
| 1 | 部分失败 | 节点失败时 diff 不应用，emit 已发生 |
| 2 | Diff 冲突 | 引擎层合并策略（override/merge） |
| 3 | 流式中间态 | 引擎 apply 时检查 current != value |
| 4 | 工具执行失败 | 工具层面补偿，diff 不应用 |
| 5 | Diff 验证 | 类型检查 + writes 声明校验 |
| 6 | Retry 机制 | checkpoint 快照 + 回滚 |
| 7 | Diff 历史 | SQLite 持久化 + 30 天清理 |
| 8 | 向后兼容 | 直接迁移，不支持旧模式 |

---

## 四、实施计划

| Phase | 时间 | 内容 | 状态 |
|-------|------|------|------|
| 6.1 | 2 周 | 基础设施（NodeResult + GraphEngine + DiffHistory） | ✅ 完成 |
| 6.2 | 1 周 | 简单节点重构（After/Reflect/Memory/SystemPrompt） | 🔄 进行中 |
| 6.3 | 1 周 | RAG 节点重构（Vector/Keyword/Merge） | 待开始 |
| 6.4 | 2 周 | ReactNode 重构（流式 + 工具执行） | 待开始 |
| 6.5 | 2 周 | 边界情况处理（8 个问题） | 待开始 |
| 6.6 | 1 周 | 测试 + B4 激活 | 待开始 |
| **总计** | **9 周** | | |

### Phase 6.1 完成内容（2026-06-26）

| 组件 | 文件 | 变更 |
|------|------|------|
| NodeResult.diff | `node.py` | 新增 `diff: dict[str, Any] | None = None` |
| RunContext.snapshot/restore | `context.py` | 新增快照/恢复方法 |
| FIELD_WRITERS | `context.py` | 完善所有字段声明（15 个字段） |
| GraphEngine._apply_diff | `graph.py` | 引擎自动 apply diff + FIELD_WRITERS 校验 |
| EXTRAS_FIELDS | `graph.py` | extras 字段路由常量 |
| DiffHistory | `diff_history.py` | SQLite 持久化 + 时间范围查询 + 清理 |

**测试**：23 个新测试（5+8+8+7）

### Phase 6.2 已迁移节点（2026-06-26）

| 节点 | 复杂度 | 文件 | 变更要点 |
|------|--------|------|----------|
| MemoryNode | L=2 | `memory_node.py` | 不再写 `ctx.extras["memory_facts"]`，返回 diff |
| AfterNode | L=2 | `after.py` | 读取 ctx 值到局部变量，校验后返回 diff |
| ReflectNode | L=2 | `reflect.py` | 读取 ctx 值到局部变量，LLM 调用后返回 diff |

**新增测试**：22 个（5+8+9）
**适配旧测试**：6 个（test_nodes_after, test_nodes_reflect, test_b10_b11_b12, test_scratchpad）

### Phase 6.2 待迁移节点（2026-06-28 grill 确认，方案 A）

| 节点 | 复杂度 | diff 字段 | 备注 |
|------|--------|-----------|------|
| RAGVectorNode | L=1 | `{rag_vector_chunks}` | 加 diff 返回 |
| RAGKeywordNode | L=1 | `{rag_keyword_chunks}` | 同上 |
| SystemPromptNode | L=2 | `{system_parts, retry_feedback_injected}` | 返回 diff |
| MergeNode | L=3 | `{messages}` | 多输入聚合，返回完整 messages list |
| ReactNode | L=3 | `{messages, raw_text, emotion, gesture, llm_call_count, accumulated_usage}` | 方案 A：6 字段 diff，流式 ctx 直写保留 |

**方案 A 关键决策：**
- ReactNode diff 含 emotion/gesture/raw_text（diff 完整性）
- `_apply_diff` 移除 emotion/gesture 的 auto final emit
- AfterNode 显式 emit emotion.final / gesture.final
- `_apply_diff` 对 emotion/gesture 去掉 `if current != value` 判断（风格对齐 + 渐进迁移预留）
- ReactNode 删除冗余 `next_node="after"`

**PRD**：`PRD-phase6.2-remaining-nodes.md`

---

## 五、验收标准

- [x] NodeResult.diff 字段
- [x] RunContext.snapshot/restore
- [x] GraphEngine._apply_diff + FIELD_WRITERS
- [x] DiffHistory 持久化
- [x] MemoryNode 返回 diff
- [x] AfterNode 返回 diff
- [x] ReflectNode 返回 diff
- [x] RAGVectorNode 返回 diff
- [x] RAGKeywordNode 返回 diff
- [x] SystemPromptNode 返回 diff
- [x] MergeNode 返回 diff
- [x] ReactNode 返回 diff
- [x] 所有节点迁移完成
- [ ] 8 个边界情况全部处理
- [x] 全量测试通过（493 passed）
- [x] 8 个边界情况全部处理

---

## 六、文件清单

### 新增文件
- `animate/core/engine/diff_history.py` — DiffHistory 类
- `tests/test_node_result_diff.py` — NodeResult 测试
- `tests/test_run_context_snapshot.py` — RunContext 测试
- `tests/test_engine_apply_diff.py` — GraphEngine 测试
- `tests/test_diff_history.py` — DiffHistory 测试
- `tests/test_node_memory_diff.py` — MemoryNode 迁移测试
- `tests/test_node_after_diff.py` — AfterNode 迁移测试
- `tests/test_node_reflect_diff.py` — ReflectNode 迁移测试

### 修改文件
- `animate/core/engine/node.py` — NodeResult 加 diff 字段
- `animate/core/engine/context.py` — RunContext 加 snapshot/restore + FIELD_WRITERS 完善
- `animate/core/engine/graph.py` — GraphEngine 加 _apply_diff + EXTRAS_FIELDS
- `animate/core/agent/nodes/memory_node.py` — 返回 diff
- `animate/core/agent/nodes/after.py` — 返回 diff
- `animate/core/agent/nodes/reflect.py` — 返回 diff
- `tests/test_nodes_after.py` — 适配 diff 检查
- `tests/test_nodes_reflect.py` — 适配 diff 检查
- `tests/test_b10_b11_b12_fix.py` — 适配 diff 检查
- `tests/test_scratchpad.py` — 适配 diff 检查
