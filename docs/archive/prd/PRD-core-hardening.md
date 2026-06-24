> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 2
> 概要: 核心加固 — Fail-Closed 工具、Result Budgeting、Re-Reminders、Analysis Scratchpad

# PRD: AniMate 核心加固 — Claude Code 借鉴模式 Phase 1

## Problem Statement

AniMate 的 Node 状态机架构正确、管线清晰，但缺少围绕 Agent Loop 的"支撑系统"。具体问题：

1. **工具无安全分级** — `ExecutePythonTool` 能执行任意代码，但 LLM 和其他代码不知道它是破坏性操作。新工具默认无任何安全限制。
2. **工具结果无预算控制** — 工具输出原样塞回 messages，即使 1M context 也需要保护不被超长输出撑爆。
3. **多轮 ReAct 角色漂移** — system prompt 中的人设指令会在 4-5 轮 tool call 后被工具结果稀释。
4. **质量评估单步无推理链** — ReflectNode 直接给结论，缺乏显式推理步骤，稳定性可提升。

## Solution

从 Claude Code 源码中借鉴 4 个模式，按落地难度排序：

### 1. Fail-Closed 工具注册
给 `LocalTool` 基类增加 3 个安全属性（`is_read_only`、`is_parallel_safe`、`is_destructive`），默认都是最严格值。安全属性暴露在 tool schema 中，LLM 可见。

### 2. Result Budgeting（工具结果预算）
`ToolRegistry.execute()` 对工具输出做大小检查：超过 50,000 字符时截断 + 存盘 + 替换为缩略版 + 告知 LLM 完整路径。

### 3. System Re-Reminders（上下文指令重注入）
ReactNode 的每轮 tool result 后动态追加 `<system-reminder>` 块，注入当前角色名，保持角色设定在多轮调用中不被稀释。

### 4. Analysis Scratchpad（分析草稿板）
ReflectNode 的评估 prompt 改为"先在 `<analysis>` 中逐维分析，然后在 `<summary>` 中返回 JSON 结论"结构——一次 LLM 调用，两步输出。

## User Stories

1. 作为工具开发者，我创建一个新 LocalTool 时不需要手动声明安全属性，默认就是最严格的安全行为。
2. 作为 AniMate 用户，我不希望 LLM 不知轻重地调用破坏性工具（如执行代码）。
3. 作为 LLM，我知道每个工具的只读/破坏性属性，能自主做出安全决策。
4. 作为角色对话用户，我不希望在多轮工具调用后 LLM 忘记角色设定。
5. 作为开发者，我不希望 1MB 的工具输出撑爆 context（即使有 1M 容量）。
6. 作为维护者，我希望质量评估能稳定给出可靠的 level 判断，减少不必要的重试或漏检。
7. 作为 AniMate 用户，我不希望质量评估增加额外的 LLM 调用成本。

## Implementation Decisions

### 1. Fail-Closed 工具注册

**文件**：`animate/core/tools/base.py`

`LocalTool` 新增 3 个类属性：

```python
is_read_only: bool = False       # 默认：有副作用（写操作）
is_parallel_safe: bool = False    # 默认：不能并发执行
is_destructive: bool = False      # 默认：非破坏性
```

`to_schema()` 在返回的 schema dict 中增加 `x_is_read_only`、`x_is_destructive` 元信息字段，LLM 调用时可见。

现有工具需要进行声明式标注：

| 工具 | is_read_only | is_parallel_safe | is_destructive |
|------|-------------|-----------------|----------------|
| TimeTool | ✅ True | ✅ True | ✅ False |
| CalculatorTool | ✅ True | ✅ True | ✅ False |
| WikipediaTool | ✅ True | ✅ True | ✅ False |
| WebSearchTool | ✅ True | ✅ True | ✅ False |
| WebExtractTool | ✅ True | ✅ True | ✅ False |
| WeatherTool | ✅ True | ✅ True | ✅ False |
| ArxivTool | ✅ True | ✅ True | ✅ False |
| ExecutePythonTool | ❌ False | ❌ False | ✅ True |
| ReadFileTool | ✅ True | ✅ True | ✅ False |
| WriteFileTool | ❌ False | ❌ False | ❌ False |
| SearchFilesTool | ✅ True | ✅ True | ✅ False |

### 2. Result Budgeting

**文件**：`animate/core/tools/registry.py`

- 阈值：**50,000 字符**（与 Claude Code 主流标准一致）
- 超限行为：截断到 50,000 字符 + 添加 `[完整结果(实际字符数)已保存到 {path}]` 后缀
- 完整结果持久化到 `~/.hermes/tmp/tool_results/{trace_id}_{tool_name}_{timestamp}.txt`
- `ToolResult` 新增 `truncated: bool` 和 `full_path: str | None` 字段（如需要返回给调用方）

### 3. System Re-Reminders

**文件**：`animate/core/agent/nodes/react.py`

在 `_handle_tool_calls()` 的 tool result 追加后，增加：

```python
# 注入角色保持提醒
reminder = f"<system-reminder>你仍然在扮演当前角色。保持角色设定和语气。</system-reminder>"
messages.append({"role": "system", "content": reminder})
```

角色名从 `ctx` 中动态读取（后续支持多角色时不用改代码）。

### 4. Analysis Scratchpad

**文件**：`animate/core/agent/nodes/reflect.py`

`EVALUATE_PROMPT` 改为：

```
先在 <analysis> 中逐维分析回复质量（角色一致性、内容相关性、语气适当性），
然后在 <summary> 中返回 JSON: { "level": 0-4, "feedback": "..." }
```

解析逻辑：提取 `<summary>` 中的 JSON，剥离 `<analysis>` 部分不进入日志和输出。

仍然是一次 LLM 调用，不增加成本。

## Testing Decisions

- 测试应通过公共接口验证行为，而非内部实现细节
- 对 base.py 的改动：测试 LocalTool 子类继承默认安全属性、子类可覆盖、to_schema() 包含 x_ 字段
- 对 registry.py 的改动：测试正常输出不截断、超限输出截断 + 存盘、截断消息包含路径信息
- 对 react.py 的改动：测试 tool result 后追加了 system-reminder、不破坏现有 tool_call 循环
- 对 reflect.py 的改动：测试输出中能解析到 <summary> 内的 JSON、无 analysis 泄漏到外部

## Out of Scope

- Context Collapse（MemoryManager 摘要折叠）— 记忆模块后续大版本重构
- StreamingToolExecutor（流式工具并发执行）
- AgentPool（多用户会话管理）
- Hook 系统（扩展点）
- 7 种权限模式和 ML 分类器
- 终端 UI 或 React 渲染
- QQ 群接入适配

## Further Notes

- Claude Code 默认每工具结果 50,000 字符（Source: ch17-performance），MCP 可调上限到 500K
- DeepSeek V4 Flash 有 1M context，50K/tool × 10轮 = 350K tokens，占比 ~35%，安全区间
- 所有改动保持向后兼容，现有工具注册代码不用改
