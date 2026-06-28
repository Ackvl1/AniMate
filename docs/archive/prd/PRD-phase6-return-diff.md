# PRD: Phase 6 — Return-Diff 架构重构

> 状态：设计完成，待实施
> 预计时间：9 周

---

## Problem Statement

AniMate 的 BSP 图引擎当前使用"节点直接写 ctx"模式。这种模式存在以下问题：

1. **状态变更不可追溯** — 无法知道哪个节点修改了哪个字段
2. **FIELD_WRITERS 未强制** — 节点可以越权写入任意字段
3. **测试需要 mock ctx** — 无法测试纯函数输入输出
4. **并发节点状态不一致** — 并行执行的节点可能产生中间状态不一致
5. **后续迭代成本高** — 添加新节点需要理解 ctx 完整结构

---

## Solution

将 BSP 图引擎改造为 Return-Diff 模式：节点返回 diff（状态差异），引擎统一 apply。

| 维度 | 当前 | Phase 6 |
|------|------|---------|
| 节点写入 | 直接写 ctx | 返回 diff |
| 引擎职责 | 只做调度 | 调度 + apply diff |
| 流式输出 | 节点内 emit | 保持不变 |
| 工具执行 | 即时副作用 | 保持不变 |
| FIELD_WRITERS | 未强制 | 引擎层强制 |
| 状态追溯 | 无 | DiffHistory 持久化 |

---

## User Stories

### 核心架构

1. 作为开发者，我希望节点返回 diff 而非直接写 ctx，以便引擎统一管理状态变更
2. 作为开发者，我希望引擎自动 apply diff 并校验 FIELD_WRITERS，防止节点越权写入
3. 作为开发者，我希望每个节点声明 reads/writes，引擎自动校验写入权限
4. 作为开发者，我希望 diff 应用时检查 current != value，避免无意义的覆盖
5. 作为开发者，我希望并行节点的 diff 在所有节点完成后统一 apply，保证一致性

### 流式输出

6. 作为 VTuber 消费端，我希望流式过程中实时收到 emotion.update 事件
7. 作为 VTuber 消费端，我希望 diff apply 后收到 emotion.final 事件作为权威值
8. 作为开发者，我希望 ReactNode 流式过程中不写 ctx，只通过 emit 传递事件
9. 作为开发者，我希望 ReactNode 返回的 diff 包含最终 emotion/gesture 值

### 工具执行

10. 作为开发者，我希望工具执行保持即时副作用，不走 diff 路径
11. 作为开发者，我希望工具执行失败时 diff 不应用，ctx 保持原状

### 异常恢复

12. 作为开发者，我希望节点执行前保存 ctx 快照
13. 作为开发者，我希望节点异常时恢复到快照状态
14. 作为开发者，我希望 checkpoint 只保护串行节点，不保护并行节点
15. 作为开发者，我希望 Agent 层兜底是唯一允许绕过 diff 的通道

### 状态管理

16. 作为开发者，我希望 extras 字段拍平为顶层 key，统一走 diff 路径
17. 作为开发者，我希望 extras 删除用 False 代替 pop()，利用 falsy 语义
18. 作为开发者，我希望 messages diff 用 clear+extend 保持引用
19. 作为开发者，我希望 snapshot/restore 只操作数据字段，排除 services

### 调试支持

20. 作为开发者，我希望 DiffHistory 记录每个节点的 diff、inputs、耗时
21. 作为开发者，我希望 DiffHistory 持久化到 SQLite，支持 30 天查询
22. 作为开发者，我希望 DiffHistory 支持按 trace_id 查询完整执行链路

### 测试

23. 作为开发者，我希望测试直接验证 diff 返回值，而非 mock ctx
24. 作为开发者，我希望 444 个测试全部通过

---

## Implementation Decisions

### 核心模块

| 模块 | 变更 |
|------|------|
| `engine/node.py` | NodeResult 新增 diff 字段 |
| `engine/graph.py` | GraphEngine 新增 apply_diff + checkpoint + DiffHistory |
| `engine/context.py` | RunContext 新增 snapshot/restore |
| `log/log_db.py` | ChatLogDB 新增 diff_history 表 + DiffHistory 类 |
| `agent/nodes/*.py` | 所有节点改为返回 diff |

### NodeResult 扩展

```python
@dataclass
class NodeResult:
    next_node: str | None = None
    diff: dict[str, Any] | None = None
```

### FIELD_WRITERS 全量对齐

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

### 引擎 apply 逻辑

```python
EXTRAS_FIELDS = {
    "rag_vector_chunks", "rag_keyword_chunks",
    "system_parts", "memory_facts", "retry_feedback_injected",
}

async def _apply_diff(self, ctx, diff, node_name, emit):
    for field, value in diff.items():
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

### Diff 删除语义

用 `False` 代替 `pop()`，利用 falsy 语义：

```python
# ReflectNode
diff={"retry_feedback_injected": False}  # False = 已消费

# SystemPromptNode 检查
if ctx.is_retry and ctx.feedback and not ctx.extras.get("retry_feedback_injected"):
    # False 是 falsy → not False → True → 注入 feedback
```

### Agent 层兜底

```python
# 唯一允许直接写 ctx 的场景
async def _run_engine():
    try:
        await engine.run(ctx, emit=emit)
    except Exception:
        ctx.final_text = "抱歉，我刚才走神了..."
        ctx.emotion = "confused"
        ctx.gesture = "tilt_head"
```

---

## Testing Decisions

### 测试原则

- 测试外部行为（diff 返回值），不测内部实现
- 每个节点独立测试 diff 正确性
- 边界情况单独测试（失败、冲突、retry）

### 测试模块

| 测试文件 | 内容 |
|----------|------|
| `tests/test_node_diff.py` | 每个节点的 diff 返回正确性 |
| `tests/test_engine_apply.py` | 引擎 apply diff + FIELD_WRITERS 校验 |
| `tests/test_checkpoint.py` | checkpoint/restore 机制 |
| `tests/test_diff_history.py` | DiffHistory 持久化 + 查询 |
| `tests/test_boundary_cases.py` | 8 个边界情况 |

### 验收标准

- [ ] 所有节点返回 diff，不直接写 ctx
- [ ] 引擎自动 apply diff
- [ ] FIELD_WRITERS 强制校验
- [ ] 流式 emit 保持实时性
- [ ] 工具执行保持即时性
- [ ] 8 个边界情况全部处理
- [ ] DiffHistory 持久化正常
- [ ] 444 个测试全部通过

---

## Out of Scope

- 多 Agent 协作（后续 Phase）
- LangGraph 集成（不装 langgraph）
- 性能优化（先保证正确性）
- 向后兼容层（直接迁移）

---

## Further Notes

- 设计文档：`docs/phase6-return-diff-plan.md`
- 实施时间：9 周
- 关键风险：ReactNode 重构（流式 + 工具执行）
