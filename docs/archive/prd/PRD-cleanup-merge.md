> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 清理
> 概要: 删除死代码，统一架构

# PRD: Phase Cleanup — 删除死代码，统一架构

## Problem Statement

AniMate 经历了从「线性 Agent」到「BSP 图引擎」的架构升级，但升级过程中遗留了 4 个死代码文件、2 套并行的核心抽象（Node ABC、RunContext、事件系统）、和 3 个测试旧代码的测试文件。

具体问题：
1. `agent/node.py` — 旧的同步 Node ABC，不被任何生产代码使用
2. `agent/context.py` — 旧的 RunContext + RunServices，不被生产代码使用
3. `agent/events.py` — 旧的 EventBus 发布/订阅事件系统，不被任何代码使用
4. `nodes/before.py` — 旧的 BeforeNode（单节点 RAG+人设+记忆），被替换为 4 节点 BSP 并行版本
5. `agent/__init__.py` 仍然 export 所有旧符号
6. 4 个测试文件测试死代码
7. `engine/context.py` 的 `services` 字段用匿名对象替代原有类型，失去类型安全

## Solution

### 删 4 个死文件
- `animate/core/agent/context.py` — Old RunContext + RunServices
- `animate/core/agent/node.py` — Old Node ABC
- `animate/core/agent/events.py` — Old EventBus
- `animate/core/agent/nodes/before.py` — Old BeforeNode

### 移 2 个有用的旧类型到新位置
- `RunServices` dataclass → 移到 `engine/context.py`（恢复类型安全）
- `RunServices` 从 agent 包移除，从 engine 包导出

### 改 3 个 __init__.py export
- `agent/nodes/__init__.py` — 移除 BeforeNode
- `agent/__init__.py` — 移除 OldRunContext, OldNode, EVETN_* 常量
- 保留 `animate/core/__init__.py` 不变  

### 修 1 个拼写错误
- `cli.py` — `keywordLibrart` → `keywordLibrary`

### 更新 5 个测试文件
- `test_core_dataclasses.py` — 改引 `engine.context`, 用新 RunContext 测试替换旧字段测试
- `test_core_nodes.py` — 重写为 async Node ABC + NodeResult + emit 测试
- `test_nodes_before.py` — 删（测旧 BeforeNode 的 6 个测试）
- `test_retry_feedback.py` — 删 `TestBeforeNodeRetry` 类（2 个测试）
- `test_react_thinking.py` — `BeforeNode.EMOTION_INSTRUCTION` → `SystemPromptNode.EMOTION_INSTRUCTION`

## User Stories

1. 作为新开发者，我不希望在 `animate/core/agent/nodes/` 下看到不用的节点文件，产生"我该用哪个"的困惑
2. 作为 IDE 用户，import `RunContext` 时我希望看到正确的类型提示和字段列表
3. 作为测试者，我不希望测试文件覆盖已死的代码路径
4. 作为维护者，我希望 `animate/core/agent/` 下只包含当前活跃的代码
5. 作为开发者，我希望 `ctx.services.memory` 有正确的类型推断，而不是 `Any`

## Implementation Decisions

### 1. RunServices 迁移

旧的 `agent/context.py` 将被完全删除。`RunServices` 类型定义迁移到 `engine/context.py`：

```python
@dataclass
class RunServices:
    """运行时服务容器 — 每个 chat 调用可能变化的服务。"""
    memory: MemoryManager | None = None

@dataclass
class RunContext:
    ...
    services: RunServices = field(default_factory=RunServices)
```

替代当前的匿名对象 `field(default_factory=lambda: type('S', (), {'memory': None, 'state': None})())`。

`engine/context.py` 不再通过 lambda 创建匿名类型，`services` 字段类型从 `Any` 变为 `RunServices`。

### 2. 删除顺序

1. 先改 `engine/context.py`（加 RunServices）
2. 然后删 `agent/context.py`、`agent/node.py`、`agent/events.py`、`nodes/before.py`
3. 然后更新 `__init__.py` exports
4. 然后更新测试文件
5. 最后修 `cli.py` 拼写

### 3. 测试文件处理

`test_core_dataclasses.py` 从测试旧 RunContext 的 `history`/`system_prompt_parts` 改为测试新 RunContext 的：
- 默认值（trace_id 自动生成、llm_call_count=0、messages=[]、emotion="" 等）
- FIELD_WRITERS 写保护机制
- check_write_permission()
- extras 字典

`test_core_nodes.py` 从测试旧 sync Node ABC 改为测试新 async Node ABC：
- 不能直接实例化（ABC 约束）
- 异步 run() 方法签名（ctx + emit → NodeResult）
- reads/writes 声明
- emit 事件发射

### 4. 测试文件删除

`test_nodes_before.py` — 整个删除（6 个测试全部覆盖死代码）
`test_retry_feedback.py` — 只删除 `TestBeforeNodeRetry` 类（2 个测试），保留 `TestReactNodeRetry`

## Testing Decisions

- 删除测试文件后，CI 测试总数从 140+ 降至约 132
- `test_core_dataclasses.py` 重写后增加对 `extras` 和 `FIELD_WRITERS` 的覆盖——这是当前没有测试覆盖的代码
- `test_core_nodes.py` 重写后确保新 Node ABC 的 async 接口有测试覆盖
- 旧 `test_retry_feedback` 的 `TestBeforeNodeRetry` 删除后，retry feedback 功能由 `SystemPromptNode` 的测试覆盖

## Out of Scope

- Context Collapse（记忆折叠）
- StreamingToolExecutor
- AgentPool / Fork
- Hook 系统
- 多角色支持（`cli.py` 硬编码 Saki 问题）
- `test_core_llm.py` 的 6 个 error（独立问题）

## Further Notes

- 删除操作不涉及运行时逻辑变更——所有被删代码在运行态都已不被引用
- 删除后 `animate/core/agent/` 从 13 个 Python 文件减少到 9 个
- `animate/core/agent/__init__.py` 的 export 减少约一半
