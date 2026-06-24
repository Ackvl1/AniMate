> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 3.5
> 概要: Before Phase 并行化 — RAG fan-out/join

# PRD: Phase 3.5 — Before Phase 并行化 (RAG + 图引擎 fan-out/join)

## Problem Statement

当前 `BeforeNode` 通过 `asyncio.create_task` 手动模拟 RAG 和本地操作的并行。这种"假并行"：
1. 没有利用图引擎的 fan-out/join 机制，BSP 调度能力未实战验证
2. 向量搜索依赖 embed HTTP（~1-3s），关键词搜索和系统提示组装被迫等 embed 完成
3. 加新 RAG 源需要改 BeforeNode 内部代码，不符合图引擎"加 Node 就行"的承诺

## Solution

将 `BeforeNode` 拆解为 4 个独立节点，通过 BSP 图引擎的 fan-out + join 并行调度：

```
                                    [RAGVector]   embed HTTP + vector_search
start ──fan_out──→ [RAGKeyword]   keyword_search           join → [Merge] → react
                    [SystemPrompt] 人设 + 指令 + 记忆 + 反馈
```

- **RAGVector**: embed HTTP 调用 + vector_store.search（串行，有数据依赖）
- **RAGKeyword**: keyword_store.search（无 embed 依赖，跟 RAGVector 并行）
- **SystemPrompt**: 组装人设 + EMOTION_INSTRUCTION + 长期记忆 + 重试反馈（纯本地，瞬间完成）
- **Merge**: 收三个节点的结果 → 去重合并 RAG chunks → 拼完整 system prompt → 加 memory history → 加 user input → 写入 ctx.messages

## User Stories

1. 作为一个开发者，我希望 Before 阶段的 RAG 检索和本地操作能通过图引擎并行，让墙钟时间更短
2. 作为一个开发者，我希望 RAG 向量检索和关键词检索互不阻塞，各自独立运行
3. 作为一个开发者，我希望能通过 `add_fan_out` / `add_join` 定义并行操作，而不需要在节点内部手动 create_task
4. 作为一个开发者，我希望 Merge 节点能从之前各节点的 `NodeResult.data` 中读取结果，而非直接操作 ctx
5. 作为一个开发者，我希望现有的图结构（before → react → after → reflect）不变，只拆分 before 阶段
6. 作为一个开发者，我希望旧的 BeforeNode 仍然保留但标记为 deprecated，以便逐步迁移
7. 作为一个开发者，我希望如果 RAG 检索失败（embed HTTP 超时等），不阻塞整个 Pipeline，走空 RAG 兜底
8. 作为一个开发者，我希望 BSP 调度器正确处理 fan_out/join 的并行冲突检测
9. 作为一个测试者，我希望每个新节点有独立的单元测试，覆盖正常路径和异常路径
10. 作为一个测试者，我希望集成测试能验证 tri-node fan-out → join → react 的完整流程

## Implementation Decisions

### 新节点

| 节点 | 文件 | 输入 | 输出 |
|------|------|------|------|
| `RAGVectorNode` | `animate/core/agent/nodes/rag_vector.py` | `ctx.user_input` | `NodeResult(data={"chunks": [...]})` |
| `RAGKeywordNode` | `animate/core/agent/nodes/rag_keyword.py` | `ctx.user_input` | `NodeResult(data={"chunks": [...]})` |
| `SystemPromptNode` | `animate/core/agent/nodes/system_prompt.py` | `ctx.extras["long_term_facts"]`, `ctx.is_retry`, `ctx.feedback` | `NodeResult(data={"system_parts": [...]})` |
| `MergeNode` | `animate/core/agent/nodes/merge.py` | 从 `_node_results` 读上游三个节点的 data | 填充 `ctx.messages` |

### 节点接口

每个节点复用 Node ABC：
```python
class SomeNode(Node):
    async def run(self, ctx: RunContext, emit) -> NodeResult:
        # 从 ctx 读输入
        # 做自己的事
        return NodeResult(next_node="merge", data={...})
```

- RAG 节点不做去重（交给 Merge 做）
- Merge 不 emit 事件（它只是组装数据，没有要流式输出的东西）
- Merge 的 `next_node` 永远是 `"react"`（除非 retry，retry 时 system prompt 可以不同）

### 图构造变更

```python
g = Graph()

g.add_node("rag_vector", RAGVectorNode(vector_store))
g.add_node("rag_keyword", RAGKeywordNode(keyword_store))
g.add_node("system_prompt", SystemPromptNode(persona))

g.add_node("merge", MergeNode())

g.add_fan_out("__entry__", ["rag_vector", "rag_keyword", "system_prompt"])
g.add_join(["rag_vector", "rag_keyword", "system_prompt"], "merge")

g.add_edge("merge", "react")
g.add_edge("react", "after")
g.add_edge("after", "reflect")

g.add_conditional_edge("reflect", reflect_router, {...})
g.set_entry("__entry__")
```

使用一个虚拟入口节点 `__entry__`（无实际 Node 对象，仅用于调度），和虚拟 join 节点（无实际 Node 对象）。

### 异常处理

- RAG 节点失败 → 返回空 chunks 列表，不抛异常
- 所有节点的异常在 GraphEngine 层面 catch，不影响其他并行节点
- Merge 里对空 chunks 不做特殊处理（system prompt 里直接不加"相关知识"段落）

### 向后兼容

- 保留旧的 `BeforeNode`（标记 `deprecated`，不引用）
- 保留 `from animate.core.agent.nodes import BeforeNode`（不删除已有 imports）
- 所有测试迁移到新节点

### 不做的

- checkpoint/HITL 不在此 PRD 范围内
- 不修改 GraphEngine 本身（fan_out/join 已有实现）
- 不修改 agent.py 的 chat_stream 接口

## Testing Decisions

### 测试原则

- 每个新节点独立测试（正常路径 + 异常路径）
- 使用 Mock 隔离 LLM 和外部 HTTP 调用
- Merge 测试：验证正确的去重合并逻辑、retry 时 system prompt 正确
- 集成测试：构造完整的图（fan_out → join → merge → react）并运行，验证事件流

### 测试文件

| 文件 | 测试内容 |
|------|---------|
| `tests/test_nodes_rag_vector.py` | RAGVectorNode：embed 成功/失败、vector_store.search 成功/失败、返回 chunks |
| `tests/test_nodes_rag_keyword.py` | RAGKeywordNode：keyword_store.search 成功/失败、返回 chunks |
| `tests/test_nodes_system_prompt.py` | SystemPromptNode：人设注入、长期记忆注入、重试反馈注入、无 retry |
| `tests/test_nodes_merge.py` | MergeNode：三路结果合并去重、空 chunks、memory history 注入、user input 注入 |
| `tests/test_graph_before_parallel.py` | 集成测试：fan_out → join → merge → react 全流程、BSP 冲突检测 |

### 预期测试数

约 20 个新测试（每个节点 4-5 个 + 集成测试 3-4 个）

## Out of Scope

- BeforeNode 的删除或拆包（保留但 deprecated）
- ReactNode/AfterNode/ReflectNode 的修改
- checkpoint/HITL
- 图引擎本身的 fan_out/join 实现修改（已有代码，只需要测试）
- agent.py chat_stream() 接口变更
- 实际 embed HTTP 调用（测试中用 MagicMock 替代）

## Further Notes

- `_retrieve_async` 方法从 BeforeNode 中提取为 RAGVectorNode 和 RAGKeywordNode 的独立逻辑
- RAGVectorNode 内部串行执行 embed + vector_search，不拆开
- MergeNode 读取 `engine._node_results` 来获取上游数据——需要确认 GraphEngine 是否暴露这个。（如果否，考虑给 GraphEngine 加 `get_result(node_name)` 方法）
- 三个新节点都需要注册到 `animate.core.agent.nodes.__init__.py`
