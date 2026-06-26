# AniMate 架构决策记录 (ADR)

> 记录关键架构决策及其背景、替代方案、代价。
> 更新至 Phase 6（2026-06-26）。

---

## ADR-1: BSP 图引擎替代线性 While 链

**状态**: ✅ 已实现 (Phase 3)  
**背景**: 原有线性 `while current: nodes[current].run(ctx)` 链无法表达并行（RAG embed + keyword 串行浪费 ~1s）、条件回边（ReAct 循环、Reflect 重试）分散在各节点内部、加新 Node 需要改 while 循环。  
**决策**: 采用 BSP（Bulk Synchronous Parallel）图引擎：

- `Graph` 定义节点 + 边（direct / conditional / fan_out / join）
- `GraphEngine` 每轮超级步完成：冲突检测 → 并行执行不冲突节点 → 调度下游
- Node 为无状态纯函数（`async run(ctx, emit) → NodeResult`），声明 `reads`/`writes` 用于冲突检测
- 所有控制流统一由边定义，Node 内部不硬编码下一个节点

**替代方案对比**:

| 方案 | 优点 | 缺点 |
|------|------|------|
| **BSP 图引擎 (选择)** | 天然支持并行+条件回边；加节点只需 add_node + add_edge | 调度开销 vs 串行的边际收益需节点数 > 4 |
| 状态机 | 实现简单 | 并行表达能力差，加状态需要改状态表 |
| 线性链 | 最简单 | 无法并行，条件分支/回路分散在多处 |
| Pregel | 超大规模图计算 | 过度设计，5-7 个节点用不上 |

**代价**: 引擎复杂度增加，但节点架构清晰度大幅提升。当前 7 节点（5 串行 + 3 并行 fan-out）证明收益大于开销。

---

## ADR-2: 真流式 via asyncio.Queue 桥接

**状态**: ✅ 已实现 (Phase 修复)  
**背景**: 初版 `chat_stream()` 在 `list[AgentEvent]` 中收集所有事件，引擎跑完才批量 yield，用户等几秒后瞬间刷出整段话。  
**决策**: 使用 `asyncio.Queue` 桥接 emit 回调和 yield 消费者：

- 引擎在后台 `asyncio.create_task` 运行，emit 实时 `await queue.put(ev)`
- 主循环逐条 `await queue.get()` 并 yield
- 哨兵机制：引擎 finally 块 `put(None)` 通知结束

**代价**: 额外的 Queue 抽象层，但实现了 LLM 输出第一个 token 时消费者立即收到 `text_token` 的真流式。

---

## ADR-3: Fail-Closed 工具系统

**状态**: ✅ 已实现 (Phase 2)  
**背景**: 新工具默认无安全限制，`ExecutePythonTool` 能执行任意代码但 LLM 和系统不知道这是破坏性操作。  
**决策**: `LocalTool` 基类声明 3 个安全属性，默认最严格：

| 属性 | 默认值 | 含义 |
|------|--------|------|
| `is_read_only` | `False` | 默认有副作用 |
| `is_parallel_safe` | `False` | 默认不能并发 |
| `is_destructive` | `False` | 默认非破坏性 |

安全属性暴露在 tool schema 的 `x_is_read_only` / `x_is_destructive` 字段，LLM 可见。

**代价**: 创建新工具需要显式声明安全属性，但所有现有工具已标注完毕（11 个本地工具）。

---

## ADR-4: Result Budgeting + Tool Call Snip

**状态**: ✅ 已实现 (Phase 2 + Phase 5)  
**背景**: 1M context 也需要保护不被超长工具输出撑爆。tool_call arguments 也可能超大（如代码文件内容）。  
**决策**: 

- 工具输出：50K 字符阈值，超限截断+存盘+附路径提示
- Tool call arguments：2K 字符阈值，超限替换为 `[参数过长，已省略]`
- System Re-Reminders：每次 tool_call 后注入 `<system-reminder>` 防人格漂移

**代价**: 截断可能丢失信息，但完整结果已存盘供回溯。

---

## ADR-5: 长期记忆 vs 短期记忆分离

**状态**: ✅ 已实现 (Phase 4)  
**背景**: 短期消息列表和长期事实库混在一起，RAG VectorStore 和事实库职能重叠。  
**决策**: 

- **短期记忆**: `self._messages` 是 Agent 持有的唯一消息列表，`ctx.messages` 引用它（不复制）
- **长期记忆**: `MemoryStore`（SQLite + FTS5）独立存储，不混入 RAG VectorStore
- `MemoryProvider` ABC 定义插件接口，`DefaultMemoryProvider` 提供基础实现
- `MemoryNode` 是图引擎接入点，在 fan_out 前检索

**代价**: 两套存储有少量代码重复（SQLite 操作），但职责完全解耦。

---

## ADR-6: 渐进式上下文压缩

**状态**: ✅ 已实现 (Phase 4)  
**背景**: 长对话（500+ 轮）的消息列表持续膨胀，FIFO 硬截断浪费 1M context，且没有内容保护策略。  
**决策**: 保护首尾 + 渐进压缩：

- **Protect-Head**: system prompt + 最早 5 轮
- **Protect-Tail**: 最近 10 轮
- **L1 Snip**: 中间区域大工具结果替换占位符（低成本）
- **L4 Auto-Compact**: LLM 摘要替换中间区域（高成本）
- **Session Rotation**: 压缩成功时冻结旧 session，创建新 session 带摘要
- 所有参数从 `config.yaml` 读取

**代价**: LLM 摘要额外消耗一次 API 调用。Session Rotation 增加了存储复杂度。

---

## ADR-7: 多计时器日志引擎

**状态**: ✅ 已实现 (Phase 5)  
**背景**: BSP fan_out 并行执行 RAGVector / RAGKeyword / SystemPrompt 时，旧单计时器无法区分并行节点，前两个节点的耗时被截断到接近 0。  
**决策**: `PhaseEventLogger` 维护 `_timers: dict[str, float]` 字典，每个节点独立计时。延迟写入：

- `node.start` 只创建新计时器，不结束已有计时器
- `node.done` 只结束指定节点的计时
- `_event_buffer` 缓存事件，`on_chat_end` 时批量 flush + 单次 commit
- Buffer 超 20 条时自动 flush（防内存泄漏）

**代价**: 重构了 PhaseEventLogger 内部实现，但对外接口完全不变。

---

## ADR-8: 信任分系统

**状态**: ✅ 已实现 (Phase 5)  
**背景**: regex 误提取的噪音和 LLM 主动存储的高置信事实都是 0.5 分，无区分。  
**决策**: 按来源设初始分 + 检索晋升 + 冲突 max 合并：

| 来源 | 初始分 | 说明 |
|------|--------|------|
| regex 提取 | 0.3 | 低置信，可能有噪音 |
| LLM `fact_store` 工具 | 0.7 | 高置信，LLM 主动存储 |
| 检索晋升 | cap +0.2 | 每次检索命中 retrieval_count++，boost 0.002/次 |
| 冲突合并 | MAX(已有, 新传入) | 相同事实取最高分，不降级 |
| 用户反馈 | ±0.05 | `fact_feedback` 工具可调 |

**代价**: 检索晋升的 cap 防止热事实无限碾压冷事实，但也意味着冷事实需要更长时间才能提升排名。

---

## ADR-9: Inline Marker 流式情绪系统

**状态**: ✅ 已实现 (Phase 3)  
**背景**: LLM 回复中需要实时输出 emotion/gesture 变化，支持 Live2D/TTS 等 VTuber 消费端。  
**决策**: LLM 在回复文本中嵌入 `(emotion,gesture)` inline 标记：

- `TextMarkerStreamer` 状态机在流式过程中实时解析标记
- 标记发射 `emotion.update` 事件，纯文本发射 `text_token` 事件
- 支持跨 token 边界的标记切分
- 未闭合的标记在 flush 时作为普通文本输出
- `AfterNode` 做最终校验和应用复合规则（emotion→gesture 限制）

**代价**: LLM 需要遵循标记格式，不严格的 LLM 可能输出格式错误的标记。AfterNode 的 `strip_markers()` 做容错清理。

---

## ADR-10: HITL 权限管理

**状态**: ✅ 已实现 (Phase 3)  
**背景**: 破坏性工具（execute_python、write_file）不应在无用户确认的情况下自动执行。  
**决策**: `PermissionManager` session 级记忆：

- 只读工具（is_read_only=True）→ 自动放行
- 非只读工具 → 首次调用征求用户意见
- 用户批准后同一 session 不再重复询问
- `auto_mode=True` 时跳过所有询问（QQ 群场景）

**代价**: 用户体验上首次调破坏性工具多一次确认交互。但在 CLI 下只是输个 y/n，可接受。

---

## ADR-11: MCP 集成

**状态**: ✅ 已实现 (Phase 4)  
**背景**: 需要扩展 Agent 的能力范围（文件操作、知识图谱记忆、GitHub 操作等）。  
**决策**: 集成 MCP（Model Context Protocol）标准：

- 使用 stdio 协议启动 MCP Server（filesystem / memory / github / brave-search）
- `MCPToolWrapper` 将 MCP 工具包装为 `LocalTool`，统一注册到 `ToolRegistry`
- 本地工具与 MCP 工具重名时自动加前缀（server_name_tool_name）
- 缺失 API Key 的 MCP Server 自动跳过，不影响启动

**代价**: 依赖 Node.js 运行环境。每个 MCP Server 占用一个子进程。

---

## ADR-12: 角色人设独立于代码

**状态**: ✅ 已实现 (Phase 1，延续至今)  
**背景**: 角色 Persona 不应硬编码在 Python 代码中。  
**决策**: 

- Persona 文件：`data/prompts/<name>_persona.txt`
- `SystemPromptNode` 在运行时从文件读取
- 人设 + EMOTION_INSTRUCTION + 长期记忆 + RAG 结果 在 MergeNode 中拼接成完整 system prompt
- 角色名、语气、说话风格全部在文本文件中定义

**代价**: 每新增一个角色需要创建一份 persona.txt + 构建 RAG 知识库。加载和切换角色需要重启 Agent 或运行时切换 prompt。

---

## ADR-13: Phase 5.2 — 全量 Bug 修复 + 审计日志

**状态**: ✅ 已实现 (2026-06-24)  
**背景**: 首次全量审计发现 23 个 bug（7 P1 / 7 P2 / 7 P3 / 2 P4），修复 21 个。详见 `docs/phase5.2-bug-fixes-summary.md`。

### 关键决策

| 决策 | 选择 | 理由 |
|------|------|------|
| user_input 注入点 | 上移到 agent.py（引擎前） | MergeNode 不可重入，retry 导致重复追加 |
| retry feedback 防重 | `ctx.extras` 标记互斥 | 两路 retry 路径（"before"/"react"）共享 ReactNode，标记是最小侵入方案 |
| 压缩不阻塞事件循环 | 全链路 async（`chat_async` + `compress_async`） | 项目已有 AsyncOpenAI 客户端，缺 `chat_async()` 方法 |
| 审计日志架构 | LogCollector 事件分派 + 直接调用 | Node 零感知；ContextManager/MemoryProvider 无 emit，直接注入 log_db |
| streaming token 计数 | tiktoken 三层递退（API → tiktoken → 字符粗估） | DeepSeek 不返回 usage 块，主流框架（LiteLLM/LangChain）都用此模式 |
| Node reads/writes | 7 节点全部声明 | BSP 冲突检测从未生效；声明后并行/串行路径全有数据 |
| check_write_permission | 暂不激活（留 Phase 6） | FIELD_WRITERS 节点名过时；收益面窄（主要覆盖 extras 外字段）|

### 后续计划

**Phase 6**: 自研 LangGraph 风格 return-diff 架构（不装 langgraph 包）

已有基础设施已覆盖 LangGraph 的 80%：Graph/GraphEngine、BSP 冲突检测、conditional_edge、FIELD_WRITERS。

只缺一个改动——节点从直接写 ctx 改为返回 dict，`_run_node` 在末尾统一 apply：

```python
# 当前
node.run(ctx, emit)          # 节点内部 ctx.messages = ...

# Phase 6
result = await node.run(ctx, emit)   # 返回 NodeResult(diff={...})
if result.diff:
    await self._apply_diff(ctx, result.diff, name, emit)  # 引擎统一 apply
```

收益：测试零 mock、FIELD_WRITERS 自动生效、LangGraph 兼容。
不动 pip install langgraph，不改现有 GraphEngine。详见 `docs/phase6-return-diff-plan.md`。

---

## ADR-14: Return-Diff 架构重构

**状态**: ✅ Phase 6.1 完成，Phase 6.2 进行中 (2026-06-26)
**背景**: 节点直接写 ctx 导致：(1) 测试需要 mock ctx；(2) FIELD_WRITERS 声明但未强制；(3) 节点间隐式耦合。  
**决策**: 采用 Return-Diff 模式：

1. **NodeResult.diff**: 新增 `diff: dict[str, Any] | None` 字段
2. **GraphEngine._apply_diff**: 引擎统一 apply diff，校验 FIELD_WRITERS
3. **RunContext.snapshot/restore**: 支持 checkpoint 快照
4. **DiffHistory**: SQLite 持久化节点 diff 记录

**替代方案对比**:

| 方案 | 优点 | 缺点 |
|------|------|------|
| **Return-Diff (选择)** | 零 mock 测试、FIELDWRITERS 自动生效、无新依赖 | 节点需重构、ReactNode 流式复杂 |
| 直接写 ctx + 装饰器 | 改动最小 | 测试仍需 mock、强制力弱 |
| LangGraph | 成熟生态 | 重依赖、API 不透明、与现有架构冲突 |

**代价**: 所有节点需重构（8 个节点），但测试覆盖从 416 → 491（+75），架构清晰度大幅提升。

### 已完成组件

| 组件 | 文件 | 状态 |
|------|------|------|
| NodeResult.diff | `node.py` | ✅ |
| RunContext.snapshot/restore | `context.py` | ✅ |
| FIELD_WRITERS 完善 | `context.py` | ✅ |
| GraphEngine._apply_diff | `graph.py` | ✅ |
| DiffHistory | `diff_history.py` | ✅ |
| MemoryNode | `memory_node.py` | ✅ |
| AfterNode | `after.py` | ✅ |
| ReflectNode | `reflect.py` | ✅ |
| RAGVectorNode | `rag_vector.py` | 待迁移 |
| RAGKeywordNode | `rag_keyword.py` | 待迁移 |
| SystemPromptNode | `system_prompt.py` | 待迁移 |
| MergeNode | `merge.py` | 待迁移 |
| ReactNode | `react.py` | 待迁移 |
