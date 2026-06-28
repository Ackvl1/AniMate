> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 3
> 概要: BSP 图引擎 + 异步流式 + 序列化 + HITL

# PRD: Anima Agent Phase 3 — BSP 图引擎 + 异步流式 + 序列化 + HITL

## Problem Statement

当前 Anima Agent 的 `while current: nodes[current].run(ctx)` 线性链架构限制了扩展性：

1. 加一个新 Node 需要改 agent.py 的字典和 while 循环逻辑
2. ReAct 工具循环、Reflect 重跑、Level 回退三种"绕回"逻辑分别藏在不同地方（ReactNode 内部 while、agent.py 的 `→ node` 日志、reflect.py 的 return）
3. 无法自然表达并行（RAG embedding + keyword 串行浪费 ~1s）
4. on_token 回调和 EventBus 两套机制职能重叠
5. 没有 checkpoint/序列化，无法实现暂停续跑
6. 没有 Human-in-the-Loop 机制，工具调用无法暂停等待用户确认

## Solution

BSP（Bulk Synchronous Parallel）图引擎替换线性 while 循环，Node 变为无状态纯函数，所有控制流统一由图边（edge）定义。

## User Stories

1. 作为一名开发者，我希望能通过 `graph.add_edge("react", "router")` 定义节点之间的流转，而不是藏在 Node.run() 的 return 里
2. 作为一名开发者，我希望能通过 `graph.add_conditional_edge("router", router_fn, {...})` 定义分支逻辑
3. 作为一名开发者，我希望能通过 `graph.add_fan_out("before", ["rag_embed", "rag_keyword"])` 定义并行节点
4. 作为一名开发者，我希望能通过 `graph.add_join(["rag_embed", "rag_keyword"], "react")` 定义汇聚点
5. 作为系统，BSP 引擎每轮超级步应收集所有就绪节点，并行执行不冲突的节点
6. 作为系统，Node 应是无状态纯函数：输入 RunContext，输出 NodeResult，不依赖外部状态
7. 作为系统，ReAct 工具循环应通过图回路边实现（react → router → tool → react），而非 Node 内部 while
8. 作为系统，Reflect level 2/3/4 回退应通过图的条件边实现，与 ReAct 循环机制统一
9. 作为一名用户，我期待 Agent.chat_stream() 返回 AsyncGenerator[AgentEvent]，实时产出 text_token 等事件
10. 作为一名用户，我期待每次 chat 的 pipeline 状态可序列化到 SQLite，重启后可从最后 checkpoint 恢复
11. 作为一名用户，我期待调危险工具时可暂停等待用户确认，并通过 gen.send() 恢复
12. 作为一名用户，我期待长时间对话时早期 messages 会自动压缩为摘要，不粗暴截断

## Implementation Decisions

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 图引擎 | `animate/core/engine/graph.py` | Graph 定义、Node 注册、Edge 定义、条件边、并行边、Join |
| BSP 调度器 | `animate/core/engine/scheduler.py` | 超级步循环、就绪节点集、并行执行池 |
| RunContext | `animate/core/engine/context.py` | 共享上下文 + 写保护声明（取代旧 RunContext） |
| AgentEvent | `animate/core/engine/events.py` | 事件类型定义 + EventBus + Generator 双通道 |
| Node ABC | `animate/core/engine/node.py` | Node 基类：reads/writes 声明 + async run() |
| Checkpointer | `animate/core/engine/checkpoint.py` | SQLite 序列化/反序列化 pipeline 状态 |
| HITL | `animate/core/engine/hitl.py` | 工具审批确认 + generator.send() 恢复 |

### 图引擎 API 设计

```python
graph = Graph()
graph.add_node("before", BeforeNode(...))      # 注册节点
graph.add_node("rag_embed", RagEmbedNode(...))
graph.add_node("rag_keyword", RagKeywordNode(...))
graph.add_node("react", ReactNode(llm, tools))
graph.add_node("router", RouterNode())
graph.add_node("tool_exec", ToolExecNode(tools))
graph.add_node("emotion", EmotionAnalysisNode(llm))
graph.add_node("after", AfterNode())
graph.add_node("reflect", ReflectNode(llm))

graph.add_edge("before", "fan_out")             # 顺序边
graph.add_fan_out("fan_out", ["rag_embed", "rag_keyword"])  # 并行边
graph.add_join(["rag_embed", "rag_keyword"], "react")       # 汇聚
graph.add_edge("react", "router")               # 路由入口

# 条件边：router 决定下一个节点
graph.add_conditional_edge("router", router_fn, {
    "tool": "tool_exec",
    "continue": "emotion",
})

graph.add_edge("tool_exec", "react")            # ReAct 回路
graph.add_edge("emotion", "after")
graph.add_edge("after", "reflect")

# Reflect 回退回路（与 ReAct 回路共享机制）
graph.add_conditional_edge("reflect", reflect_router, {
    "pass": None,           # 结束
    "reformat": "after",    # level 2
    "regenerate": "react",  # level 3
    "reretrieve": "before", # level 4
})
```

### BSP 调度算法

```
每轮超级步：
  1. 找出所有就绪节点（上游全部完成的节点）
  2. 检查 reads/writes 冲突 → 不冲突的并行执行
  3. 运行节点 → 收集 NodeResult
  4. 更新完成状态 → 标记下游就绪
  5. 有回路边？标记上游重新就绪（用于 ReAct）
  6. 没有更多就绪节点？结束
```

### Node 接口变更

```python
class Node(ABC):
    """节点基类——无状态纯函数"""
    
    reads: set[str] = set()     # 读取的 ctx 字段
    writes: set[str] = set()    # 写入的 ctx 字段
    
    @abstractmethod
    async def run(self, ctx: RunContext, emit: EventEmitter) -> NodeResult:
        ...
```

### 序列化/Checkpoint

- 使用 SQLite 存储：`checkpoints(trace_id, node, ctx_pickle, edges_done, created_at)`
- 每次 Node 执行前 checkpoint（savepoint 模式）
- 序列化使用 pickle（当前进程内使用，足够）
- ctx 里排除不可序列化对象（LLM client、工具注册表等），在反序列化后重建

### HITL

- 工具定义新增 `needs_approval: bool` 字段
- ReactNode 遇到 `needs_approval=True` 的工具 → yield `AgentEvent(type="tool.confirm", ...)` → 暂停
- cli.py/UI 调用 `gen.send(approved)` → 继续 pipeline
- Checkpoint 在 yield 前保存，确保暂停时可序列化

## Testing Decisions

### 测试原则
- 每个 Node 的 reads/writes 声明有对应的冲突检测测试
- 图定义有测试验证节点连通性（没有孤立节点、没有死循环）
- 使用 mock LLM 测试图调度行为（mock 的 chat 返回预定义结果）
- BSP 超级步逻辑有独立的单元测试（不依赖具体 Node 实现）

### 要测试的模块

| 模块 | 测试内容 |
|------|---------|
| `engine/graph.py` | 节点注册、边注册、条件边、并行边、join、死循环检测 |
| `engine/scheduler.py` | 单节点、串行链、条件分支、并行 fan-out/join、ReAct 回路 |
| `engine/context.py` | reads/writes 冲突检测、字段写入权限 |
| `engine/node.py` | Node 基类接口 |
| `engine/checkpoint.py` | 序列化/反序列化、savepoint 恢复 |
| `engine/hitl.py` | tool.confirm 暂停 + gen.send() 恢复 |

### 现有测试影响

现有 80+ 单元测试位于 `tests/`，涉及 `animate/core/agent/` 下的 Node 类和 Agent。迁移到图引擎后：
- Node 类（Before/React/After/Reflect）接口从 `run(ctx) → str` 改为 `async run(ctx, emit) → NodeResult`
- 需同步更新现有 Node 测试
- Agent 测试替换为 Engine 测试

## Out of Scope

- EmotionNode 的具体实现（Phase 3 的独立任务，只在引擎中预留注册位）
- 纯文本输出改造（BeforeNode prompt 改 JSON→文本，在 EmotionNode 实现时一起做）
- 上下文压缩 autoCompact（参考 Claude Code，Phase 4+）
- TTS 集成（Phase 4+）
- Vision 多模态（Phase 5+）
- 长期记忆 SQLite 持久化（独立于 checkpoint，Phase 4+）

## Further Notes

- 引擎和 Node 的迁移可以并行进行：先写好 Graph + Scheduler，再逐个 Node 迁移
- 第一个迁移的 Node 应该是 ReflectNode（最简单，没有循环依赖）
- Generator 回退方案：如果 async 改造成本太大，先用同步 Generator + 事件队列攒批（B2 方案）
- 序列化在初期可以选做——先保证 yield 链通畅，再补 checkpoint
