# Anima Agent 项目状态文档

> **最后更新**：2026-06-28  
> **当前阶段**：Phase 6 全部完成 + session_end 实现  
> **测试状态**：499 passed, 0 failed, 0 skipped  
> **角色**：BanG Dream! 丰川祥子（Oblivionis）

---

## 目录

1. [项目概述](#1-项目概述)
2. [五层架构设计](#2-五层架构设计)
3. [已完成阶段](#3-已完成阶段)
4. [Phase 6 详细成果](#4-phase-6-详细成果)
5. [技术栈](#5-技术栈)
6. [数据库清单](#6-数据库清单)
7. [测试覆盖](#7-测试覆盖)
8. [文件统计](#8-文件统计)
9. [下一阶段规划](#9-下一阶段规划)
10. [硬件需求](#10-硬件需求)

---

## 1. 项目概述

### 1.1 Anima Agent 是什么

Anima Agent 是一个**角色化 AI 对话伙伴**，通过 BSP 图引擎驱动的多节点流水线，将大语言模型（LLM）包装在"角色人格皮肤"之下，配合本地 RAG 知识库实现深度角色扮演对话。

核心特性：
- **BSP 图引擎**：支持并行执行、条件回边、冲突检测
- **真流式输出**：LLM 输出第一个 token 时消费者立即收到 `text_token`
- **11+ 本地工具**：代码执行、文件操作、搜索、天气等
- **RAG 双路检索**：向量检索（numpy 余弦相似度）+ 关键词检索（jieba 倒排索引）
- **HITL 权限管理**：破坏性工具需用户确认，session 内记住
- **情绪系统**：Inline Marker 实时解析 `(emotion,gesture)` 标记
- **信任分系统**：regex 0.3 / LLM 0.7 / 检索晋升 capped 0.2
- **Session 管理**：压缩、轮转、跨 session 检索

### 1.2 当前角色

| 属性 | 值 |
|------|-----|
| 角色名 | 丰川祥子（Toyokawa Sakiko） |
| 来源 | BanG Dream! It's MyGO!!!!! / Ave Mujica |
| Persona ID | Oblivionis |
| Persona 文件 | `anima/data/prompts/toyokawa_sakiko_persona.txt` |
| 知识库 | `anima/data/documents/`（角色知识文档） |
| 情绪集 | calm, happy, sad, angry, surprised, confused, excited, shy, serious, playful |
| 手势集 | nod, shake_head, wave, point, tilt_head, shrug, clap, crossed_arms |

---

## 2. 五层架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│  接口层 (Interface Layer)                                        │
│  FastAPI REST API / CLI REPL / MCP stdio                        │
├─────────────────────────────────────────────────────────────────┤
│  UI 层 (Presentation Layer - 待实现)                              │
│  VTuber 前端 / Web 聊天界面 / Live2D 控制器                       │
├─────────────────────────────────────────────────────────────────┤
│  表现层 (Performance Layer - 待实现)                              │
│  TTS: CosyVoice 3.0 / VRM: three-vrm + VRM SDK                 │
├─────────────────────────────────────────────────────────────────┤
│  Core 层 (核心引擎)                                              │
│  BSP GraphEngine → 8 节点流水线 → Agent 门面                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Engine   │ │ Agent    │ │ RAG      │ │ Memory   │           │
│  │ graph.py │ │ agent.py │ │ rag/     │ │ memory/  │           │
│  │ node.py  │ │ nodes/   │ │          │ │          │           │
│  │ context.py│ │ logging.py│ │          │ │          │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────────┤
│  数据层 (Data Layer)                                            │
│  SQLite × 4: chat_log.db / memory.db / sessions.db / diff_history.db │
│  向量库: .pkl / 关键词库: .pkl / 文档: documents/               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 各层职责

| 层 | 状态 | 职责 | 关键组件 |
|----|------|------|----------|
| **接口层** | ✅ CLI 已实现，FastAPI 待开发 | 用户交互入口 | `cli.py`, FastAPI (计划中) |
| **UI 层** | 🔲 待开发 | 可视化界面 | Web / Desktop |
| **表现层** | 🔲 待开发 | 语音合成 + 3D 角色渲染 | CosyVoice + VRM |
| **Core 层** | ✅ 完成 | 核心对话引擎 | GraphEngine, 8 节点, Agent |
| **数据层** | ✅ 完成 | 持久化存储 | 4 个 SQLite DB + 向量/关键词库 |

### 2.2 Core 层内部架构

```
__entry__ → MemoryNode → fan_out → [RAGVectorNode, RAGKeywordNode, SystemPromptNode]
                                → join → MergeNode → ReactNode → AfterNode → ReflectNode
                                                                                │
                                      ← react (level 2-3, 重生成) ←─────────────┘
                                      ← __entry__ (level 4, 重检索) ←──────────┘
```

**BSP 调度规则**：
- 超级步内无写冲突的节点全并行执行
- 有写冲突的节点延迟到下一步
- `FIELD_WRITERS` 强制执行：越权写入抛 `PermissionError`

---

## 3. 已完成阶段

| 阶段 | 名称 | 测试数 | 完成日期 | 核心成果 |
|------|------|--------|----------|----------|
| **Phase 1** | 核心架构 | 96 | 2026-06 | Node 状态机 + Agent 门面 + EventBus + ToolRegistry |
| **Phase 2** | 目录重组 + 数据层 | 133 | 2026-06 | core/io/data 三层分离 + paths.py + ChatLogDB |
| **Phase 3** | BSP 图引擎 | 180+ | 2026-06 | Graph + GraphEngine + 冲突检测 + 条件边 + fan_out/join |
| **Phase 3.5** | Before 并行化 | 200+ | 2026-06 | RAGVector + RAGKeyword + SystemPrompt + Merge 四节点并行 |
| **Phase 4** | 日志 + 长期记忆 | 250+ | 2026-06 | PhaseEventLogger + ChatLogDB + 事实提取 + 长期记忆注入 |
| **Phase 5** | CLI 完整接入 + 日志整改 + 信任分 | 416 | 2026-06 | /compact /resume CLI + 多计时器日志 + 信任分 + 日志轮转 |
| **Phase 5.2** | 全量 Bug 修复 + 审计日志 | — | 2026-06-24 | 23 个 bug 审计，修复 21 个（7 P1 / 7 P2 / 7 P3 / 2 P4） |
| **Phase 6.1** | Return-Diff 基础 | +23 | 2026-06-26 | NodeResult.diff + RunContext.snapshot + _apply_diff + DiffHistory |
| **Phase 6.2** | Return-Diff 全节点迁移 | 493 | 2026-06-28 | 8 节点全部迁移 + DiffHistory 重写 + 6 bug 修复 |
| **session_end** | 会话结束深度提取 | +6 | 2026-06-28 | LLM 深度事实提取 + 双写 MemoryStore + ChatLogDB |

**累计测试增长**：96 → 133 → 180 → 250 → 416 → 493 → **499**

---

## 4. Phase 6 详细成果

### 4.1 8 节点 Return-Diff 迁移

| # | 节点 | 文件 | diff 字段 | 迁移复杂度 | 说明 |
|---|------|------|-----------|------------|------|
| 1 | MemoryNode | `memory_node.py` | `{memory_facts}` | L=1 | 长期记忆检索 → diff 返回 |
| 2 | RAGVectorNode | `rag_vector.py` | `{rag_vector_chunks}` | L=1 | 向量检索 → diff 返回 |
| 3 | RAGKeywordNode | `rag_keyword.py` | `{rag_keyword_chunks}` | L=1 | 关键词检索 → diff 返回 |
| 4 | SystemPromptNode | `system_prompt.py` | `{system_parts, retry_feedback_injected}` | L=2 | 去双写，只通过 diff |
| 5 | MergeNode | `merge.py` | `{messages}` | L=3 | 不 clear messages，局部构建 |
| 6 | ReactNode | `react.py` | `{messages, raw_text, emotion, gesture, llm_call_count, accumulated_usage}` | L=3 | 方案 A：6 字段 diff，流式直写保留 |
| 7 | AfterNode | `after.py` | `{final_text, emotion, gesture}` | L=1 | 显式 emit emotion.final/gesture.final |
| 8 | ReflectNode | `reflect.py` | `{is_retry, feedback, retry_feedback_injected, llm_call_count, accumulated_usage}` | L=2 | 标记清理 + 路由决策 |

### 4.2 DiffHistory 设计

**从 4 字段同步 → 7 字段异步**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `trace_id` | TEXT | 会话级 trace 标识 |
| `node_name` | TEXT | 节点名称 |
| `diff_json` | TEXT | JSON 序列化的 diff 字典 |
| `inputs_json` | TEXT | 节点输入快照（`_capture_inputs`） |
| `events_json` | TEXT | 事件列表（预留） |
| `duration_ms` | REAL | 节点执行耗时（毫秒） |
| `created_at` | TIMESTAMP | 自动记录时间戳 |

**技术特性**：
- 独立 SQLite 文件：`anima/data/trace/diff_history.db`
- WAL 模式 + `busy_timeout=5000` + `synchronous=NORMAL`
- `asyncio.Lock` 串行化写入
- 缓冲区 100 条自动 flush
- 30 天 retention + `cleanup()` 自动清理
- 双索引：`idx_diff_trace`（trace_id）+ `idx_diff_ts`（时间）

### 4.3 Bug 修复清单

| # | Bug | 根因 | 修复方案 |
|---|-----|------|----------|
| 1 | AfterNode 空分支无 final emit | 引擎 auto-emit 移除后未补偿 | 空文本分支添加显式 emit |
| 2 | SystemPromptNode 双写 | 直接写 ctx + diff 同时存在 | 移除直接写，只通过 diff |
| 3 | ReactNode 冗余 `next_node="after"` | pre-diff 遗留 | 删除两个 return 点的 next_node |
| 4 | Agent 兜底无 final emit | except 分支只写 ctx 不 emit | 显式 emit emotion.final/gesture.final |
| 5 | MemoryNode 死字段 `data=` | Phase 6 废弃 data 字段 | 改为 `diff=` |
| 6 | 后备记忆通路路由错误 | 无 memory_provider 时条件边指向错误 | 动态路由 `"memory" if memory_provider else "__entry__"` |
| 7 | 重复 except 块 | ReactNode 工具执行路径冗余 | 合并重复异常处理 |

### 4.4 边界情况覆盖（8 项）

| # | 场景 | 状态 | 说明 |
|---|------|------|------|
| 1 | 重试重入残余 emotion | ✅ | AfterNode 覆盖 |
| 2 | usage_before 比较逻辑 | ✅ | Diff 覆盖确保幂等 |
| 3 | raw_text 每轮重置 | ✅ | 无跨轮依赖 |
| 4 | ReactNode max-rounds return | ✅ | 两个 return 点返回相同 6 字段 diff |
| 5 | 空文本 → AfterNode fallback | ✅ | 显式 emit emotion.final(value="calm") |
| 6 | DiffHistory buffer flush 时机 | ✅ | 引擎结束时 flush + 缓冲区满自动 flush |
| 7 | Snapshot/restore on exception | ✅ | `_run_node` except 块中 `ctx.restore(snapshot)` |
| 8 | FIELD_WRITERS PermissionError | ✅ | 越权写入显式报错 |

### 4.5 架构决策

**ADR-14: Return-Diff 架构重构**

| 方案 | 优点 | 缺点 |
|------|------|------|
| **Return-Diff（采用）** | 零 mock 测试、FIELD_WRITERS 自动生效、无新依赖 | 节点需重构、ReactNode 流式复杂 |
| 直接写 ctx + 装饰器 | 改动最小 | 测试仍需 mock、强制力弱 |
| LangGraph | 成熟生态 | 重依赖、API 不透明、与现有架构冲突 |

**ReactNode 方案 A vs B**：

| 维度 | 方案 A（采用） | 方案 B |
|------|--------------|--------|
| 核心思路 | 流式中间态仍直接写 ctx，最终通过 diff 返回 | 流式中全部走闭包 nonlocal，最终合并写 diff |
| 优点 | 改动最小，流式语义不变 | 完全消除 ReactNode 内所有 ctx 写入 |
| 缺点 | ReactNode 内仍有 ctx 直写 | 需重构 TextMarkerStreamer 和 StreamingToolExecutor |

---

## 5. 技术栈

### 5.1 核心技术选型

| 层 | 技术 | 说明 |
|----|------|------|
| **LLM** | DeepSeek V4 Flash / Pro | 1M context，主力模型 |
| **LLM** | 智谱 GLM-4.7 / 4.5 | 备选，131K context |
| **LLM** | 阿里通义 Qwen-3 / 2.5 | 备选，131K context |
| **Embedding** | DashScope text-embedding-v4 | 向量检索 |
| **TTS** | CosyVoice 3.0（计划中） | 语音合成 |
| **角色渲染** | VRM + three-vrm（计划中） | 3D 角色模型 |
| **接口层** | FastAPI（计划中） | REST API |
| **图引擎** | BSP（自研） | 并行调度 + 冲突检测 |
| **正则** | regex 库 | 内置 ReDoS timeout 2s |
| **配置** | YAML (config.yaml) | 惰性加载 |
| **日志** | SQLite 7 张表 + 多计时器事件体系 | ChatLogDB |
| **记忆** | SQLite + FTS5 + 信任评分 | MemoryStore |
| **流式** | char-by-char replay + inline marker | asyncio.Queue 桥接 |
| **DiffHistory** | 独立 SQLite + WAL + async | 7 字段持久化 |
| **测试** | pytest | 499 tests |
| **MCP** | stdio 协议 | filesystem / memory / github / brave-search |

### 5.2 本地工具清单（11 个）

| 工具 | 文件 | 说明 |
|------|------|------|
| TimeTool | `time_tool.py` | 时间查询 |
| CalculatorTool | `calculator.py` | 数学计算 |
| CodeExecTool | `code_exec.py` | 代码执行（subprocess 隔离） |
| FileTools | `file_tools.py` | 文件操作 |
| MemoryTools | `memory_tools.py` | 长期记忆查询/存储 |
| WeatherTool | `weather.py` | 天气查询 |
| WebSearchTool | `web_search.py` | 网络搜索 |
| WebExtractTool | `web_extract.py` | 网页内容提取 |
| WikipediaTool | `wikipedia.py` | Wikipedia 查询 |
| ArxivTool | `arxiv.py` | 论文查询 |
| MCPToolWrapper | `mcp/` | MCP Server 工具包装 |

### 5.3 安全属性（Fail-Closed）

| 属性 | 默认值 | 含义 |
|------|--------|------|
| `is_read_only` | `False` | 默认有副作用 |
| `is_parallel_safe` | `False` | 默认不能并发 |
| `is_destructive` | `False` | 默认非破坏性 |

---

## 6. 数据库清单

### 6.1 数据库总览

| 数据库 | 文件路径 | 用途 | 表数量 |
|--------|----------|------|--------|
| **chat_log.db** | `anima/data/logs/chat_log.db` | 聊天日志 + 审计 | 7 表 |
| **memory.db** | `anima/data/memory/memory.db` | 长期记忆 + FTS5 | 1 表 |
| **sessions.db** | `anima/data/sessions/sessions.db` | 会话生命周期 | 1 表 |
| **diff_history.db** | `anima/data/trace/diff_history.db` | 节点 diff 轨迹 | 1 表 |

### 6.2 chat_log.db 7 张表

| 表名 | 用途 |
|------|------|
| `chat_logs` | 聊天消息记录 |
| `phase_events` | 图引擎阶段事件（多计时器） |
| `tool_audit` | 工具调用审计 |
| `emotion_logs` | 情绪变化记录 |
| `long_term_facts` | 长期事实审计层 |
| `compression_logs` | 压缩操作记录 |
| `log_archive` | 日志归档（轮转） |

### 6.3 memory.db

| 特性 | 说明 |
|------|------|
| 存储 | SQLite + FTS5 全文检索 |
| 信任分 | regex 0.3 / LLM 0.7 / 检索晋升 +0.002/次（cap 0.2） |
| 去重 | 文本归一化 + IntegrityError 机制 |
| 工具 | `fact_store`（LLM 主动存储）、`fact_feedback`（±0.05） |

### 6.4 diff_history.db

| 特性 | 说明 |
|------|------|
| Schema | 7 字段（trace_id, node_name, diff_json, inputs_json, events_json, duration_ms, created_at） |
| 模式 | WAL + `busy_timeout=5000` + `synchronous=NORMAL` |
| 写入 | `asyncio.Lock` + 缓冲区 100 条自动 flush |
| 索引 | `idx_diff_trace`（trace_id）+ `idx_diff_ts`（created_at） |
| 保留 | 30 天 retention + `cleanup()` 自动清理 |

---

## 7. 测试覆盖

### 7.1 总览

```
============================= 499 passed ==============================
```

**499 个测试全部通过，零失败，零跳过。**

### 7.2 测试模块明细

| 模块 | 测试文件 | 用例数 | 覆盖内容 |
|------|----------|--------|----------|
| **Agent 基础** | test_core_agent.py | 5 | Agent 创建、chat 基础 |
| **Agent compact/resume** | test_agent_compact_resume.py | 5 | 压缩、恢复、session 管理 |
| **Agent shutdown** | test_agent_shutdown.py | 5 | 关闭流程、DB 连接清理 |
| **Agent integration** | test_agent_integration.py | 8 | 端到端集成 |
| **Agent logging** | test_agent_logging.py | — | 日志事件 |
| **Agent retry** | test_agent_retry_transition.py | — | 重试状态转换 |
| **Core Config** | test_core_config.py | 16 | YAML 配置加载 |
| **Core DataClasses** | test_core_dataclasses.py | 8 | 数据类 |
| **Core LLM** | test_core_llm.py | 9 | LLM 客户端 |
| **Core Memory** | test_core_memory.py | 4 | 记忆系统基础 |
| **Core Nodes** | test_core_nodes.py | 13 | 节点基础 |
| **Core Tools** | test_core_tools.py | 5 | 工具系统 |
| **Core Paths** | test_core_paths.py | — | 路径配置 |
| **Context Manager** | test_context_manager.py | 20 | 上下文管理、压缩 |
| **Token Counter** | test_token_counter.py | 11 | Token 计数 |
| **Graph Engine** | test_graph_engine.py | 7 | 图定义、BSP 调度 |
| **Graph Before** | test_graph_before_parallel.py | — | Before 并行 |
| **Engine Context** | test_engine_context.py | — | 引擎上下文 |
| **Log DB** | test_log_db.py | — | 日志数据库 |
| **Log DB Extended** | test_log_db_extended.py | — | 扩展日志 |
| **Log Rotation** | test_log_rotation.py | 2 | 日志轮转 |
| **Log Collector** | test_log_collector.py | — | 日志收集器 |
| **Logging Parallel** | test_logging_parallel.py | 6 | 并行节点日志 |
| **Marker Streamer** | test_marker_streamer.py | — | 情绪标记解析 |
| **Memory Store** | test_memory_store.py | 25 | 长期记忆存储 |
| **Memory Trust** | test_memory_trust.py | 9 | 信任评分 |
| **Long Term Memory** | test_long_term_memory.py | — | 长期记忆集成 |
| **Model Switch** | test_model_switch.py | 15 | 模型切换 |
| **Session Store** | test_session_store.py | 25 | Session 管理 |
| **Session Save** | test_session_save.py | — | Session 持久化 |
| **Tool Args Snip** | test_tool_args_snip.py | 4 | 参数截断 |
| **Budgeting** | test_budgeting.py | — | 结果预算 |
| **Safety Tools** | test_safety_tools.py | — | 工具安全 |
| **Permission** | test_permission.py | — | 权限管理 |
| **Registry Find** | test_registry_find.py | — | 工具注册 |
| **React HITL** | test_react_hitl.py | — | HITL 交互 |
| **React Thinking** | test_react_thinking.py | — | ReAct 思考 |
| **Re-Reminders** | test_re_reminders.py | — | 角色保持提醒 |
| **Scratchpad** | test_scratchpad.py | — | Analysis Scratchpad |
| **Streaming Fix** | test_streaming_fix.py | — | 流式修复 |
| **B2 Streaming** | test_b2_streaming_usage.py | — | 流式 usage |
| **CLI Commands** | test_cli_commands.py | — | CLI 命令 |
| **Config Compress** | test_config_compress.py | — | 压缩配置 |
| **Compact Prompt** | test_compact_prompt.py | — | 压缩 prompt |
| **Extract Facts** | test_extract_quick_facts.py | — | 快速事实提取 |
| **MCP Paths** | test_mcp_paths.py | — | MCP 路径 |
| **Retry Feedback** | test_retry_feedback.py | — | 重试反馈 |
| **Node Events** | test_node_events.py | — | 节点事件 |
| **B10 B11 B12** | test_b10_b11_b12_fix.py | 10 | 去重 + 压缩异步 |
| **Async Node** | test_async_node.py | — | 异步节点 |
| **Phase 6: NodeResult diff** | test_node_result_diff.py | 5 | NodeResult.diff 字段 |
| **Phase 6: RunContext snapshot** | test_run_context_snapshot.py | 8 | 快照/恢复 |
| **Phase 6: Engine apply_diff** | test_engine_apply_diff.py | 7 | _apply_diff 校验 |
| **Phase 6: DiffHistory** | test_diff_history.py | 6 | DiffHistory 持久化 |
| **Phase 6: MemoryNode diff** | test_node_memory_diff.py | 5 | MemoryNode diff |
| **Phase 6: AfterNode diff** | test_node_after_diff.py | 8 | AfterNode diff |
| **Phase 6: ReflectNode diff** | test_node_reflect_diff.py | 9 | ReflectNode diff |
| **Phase 6: ReactNode diff** | test_node_react_diff.py | 5 | ReactNode 6 字段 diff |
| **Nodes: After** | test_nodes_after.py | 8 | AfterNode 完整行为 |
| **Nodes: Merge** | test_nodes_merge.py | 8 | MergeNode 去重合并 |
| **Nodes: SystemPrompt** | test_nodes_system_prompt.py | 6 | SystemPromptNode |
| **Nodes: RAG Vector** | test_nodes_rag_vector.py | 5 | RAGVectorNode |
| **Nodes: RAG Keyword** | test_nodes_rag_keyword.py | 4 | RAGKeywordNode |
| **Nodes: Reflect** | test_nodes_reflect.py | 7 | ReflectNode 质量评估 |
| **Nodes: React** | test_nodes_react.py | — | ReactNode |
| **Merge No Clear** | test_merge_node_no_clear.py | 6 | MergeNode 不清空 |
| **Session End** | test_session_end_extraction.py | 6 | 会话结束 LLM 提取 |

### 7.3 测试增长趋势

```
Phase 1:    96 tests
Phase 2:   133 tests (+37)
Phase 3:   180 tests (+47)
Phase 3.5: 200 tests (+20)
Phase 4:   250 tests (+50)
Phase 5:   416 tests (+166)
Phase 6.1: 438 tests (+22)
Phase 6.2: 493 tests (+55)
session_end: 499 tests (+6)
```

---

## 8. 文件统计

### 8.1 anima/core/ 源码

| 模块 | 主要文件 | 说明 |
|------|----------|------|
| **engine/** | graph.py, node.py, context.py, diff_history.py | BSP 图引擎核心 |
| **agent/** | agent.py, logging.py, response.py, permission.py | Agent 门面 |
| **agent/nodes/** | 9 个节点文件 + marker_streamer.py | 8 个处理节点 + 流式解析 |
| **rag/** | VectorStore.py, KeywordStore.py, embedder.py, chunker.py | RAG 引擎 |
| **llm/** | client.py, models.py | LLM 客户端 |
| **memory/** | store.py, provider.py, default_provider.py, conversation.py | 记忆系统 |
| **context/** | manager.py, token_counter.py, strategies/ | 上下文管理 |
| **session/** | store.py | Session 管理 |
| **tools/** | base.py, registry.py, defaults.py, function/ (11工具), mcp/ | 工具系统 |
| **log/** | logger.py, log_db.py | 日志基础设施 |
| **config.py, constants.py, errors.py, paths.py** | — | 共享配置 |

**总行数**：约 **5,400 行**（anima/core/ 目录）

### 8.2 tests/ 目录

| 指标 | 值 |
|------|-----|
| 测试文件总数 | **68 个** |
| 测试用例总数 | **499 个** |
| 覆盖模块 | Agent, Engine, RAG, Memory, Tools, Log, Session, CLI |

### 8.3 项目根目录

| 文件 | 说明 |
|------|------|
| `cli.py` | 主入口 CLI REPL |
| `buildLibrary.py` | 知识库构建工具 |
| `config.yaml` | Provider 目录 + 压缩参数 + 日志轮转 |
| `requirements.txt` | Python 依赖 |
| `.env.example` | 环境变量模板 |
| `CLAUDE.md` | 项目开发指南 |
| `README.md` | 项目文档 |

### 8.4 docs/ 目录

| 文件 | 说明 |
|------|------|
| `architecture-decision-records.md` | 14 个架构决策记录（ADR） |
| `phase6-return-diff-plan.md` | Phase 6 迁移计划 |
| `phase6.2-completion-report.md` | Phase 6.2 完成报告 |
| `phase5.2-bug-fixes-summary.md` | Phase 5.2 Bug 修复汇总 |
| `archive/prd/` | 16 个历史 PRD（已实现） |
| `archive/tutorials/` | Phase 1-7 开发教程 |

---

## 9. 下一阶段规划

### 9.1 Phase 7: 表现层基础（TTS + VRM）

| 任务 | 优先级 | 说明 |
|------|--------|------|
| CosyVoice 3.0 集成 | 高 | TTS 语音合成，支持 emotion 情绪映射 |
| VRM 模型加载 | 高 | three-vrm 加载 .vrm 角色模型 |
| 情绪 → 表情映射 | 高 | emotion/gesture → VRM blend shape |
| 音频流式播放 | 中 | TTS 输出 → 音频流 → 播放器 |
| 口型同步 | 中 | 音频 → viseme → VRM 口型动画 |
| 手势动画 | 低 | gesture → VRM 动画 clip |

### 9.2 Phase 8: 接口层（FastAPI）

| 任务 | 优先级 | 说明 |
|------|--------|------|
| FastAPI REST API | 高 | /chat, /chat_stream, /health 端点 |
| WebSocket 流式输出 | 高 | 替代 HTTP polling |
| SSE 事件流 | 中 | Server-Sent Events |
| 静态文件服务 | 中 | VRM 模型、音频文件 |
| API Key 认证 | 中 | Bearer token |
| CORS 配置 | 低 | 跨域支持 |

### 9.3 Phase 9: 桌面应用

| 任务 | 优先级 | 说明 |
|------|--------|------|
| Electron/Tauri 打包 | 高 | 桌面应用容器 |
| 3D 渲染窗口 | 高 | three.js + VRM 实时渲染 |
| 音频输出 | 高 | TTS 音频播放 |
| 系统托盘 | 中 | 后台运行 |
| 自动更新 | 低 | 版本管理 |

### 9.4 技术债务

| 项目 | 说明 | 优先级 |
|------|------|--------|
| ReactNode 流式直写 | 方案 A 保留了 ctx 直写，长期应迁移 | 低 |
| `NodeResult.data` 废弃 | 仍保留向后兼容，可标记 `@deprecated` | 低 |
| DiffHistory events_json | Schema 有字段但未使用，可扩展 | 低 |
| 并发测试 | DiffHistory 多 trace 同时写入场景测试不足 | 中 |

---

## 10. 硬件需求

### 10.1 最低配置

| 组件 | 规格 | 说明 |
|------|------|------|
| **GPU** | NVIDIA RTX 3060+ | 6GB VRAM（CosyVoice 最低要求） |
| **CPU** | 4 核+ | LLM API 调用为主，CPU 压力小 |
| **内存** | 8GB+ | Python + SQLite + numpy |
| **存储** | 10GB+ | 模型权重 + 知识库 + 数据 |

### 10.2 推荐配置

| 组件 | 规格 | 说明 |
|------|------|------|
| **GPU** | NVIDIA RTX 4060 Ti+ | 8GB+ VRAM，TTS + VRM 并行 |
| **CPU** | 8 核+ | 并行节点执行 |
| **内存** | 16GB+ | 大模型 context + 多进程 |
| **存储** | 50GB+ SSD | NVMe SSD 加速模型加载 |

### 10.3 CosyVoice 3.0 特殊需求

| 需求 | 说明 |
|------|------|
| **VRAM** | ≥ 6GB（RTX 3060 起步） |
| **推理时间** | ~1-3 秒/句（取决于 GPU） |
| **支持格式** | WAV, MP3 |
| **情绪映射** | emotion → speaker embedding 微调 |
| **流式支持** | chunk-based streaming TTS |

### 10.4 仅 LLM 模式（无 TTS/VRM）

| 组件 | 规格 | 说明 |
|------|------|------|
| **GPU** | 不需要 | LLM 通过 API 调用 |
| **CPU** | 2 核+ | CLI + SQLite |
| **内存** | 4GB+ | 最小化运行 |
| **网络** | 需要 | API 调用依赖网络 |

---

## 附录

### A. 环境变量

```bash
ANIMATE_LLM_PROVIDER=deepseek        # LLM 提供商
ANIMATE_EMBEDDING_PROVIDER=dashscope  # Embedding 提供商
OPENAI_CHAT_API_KEY=sk-xxx           # DeepSeek API Key
OPENAI_EMBEDDING_API_KEY=sk-xxx      # DashScope API Key
ZAI_API_KEY=sk-xxx                   # 智谱 GLM（可选）
QWEN_API_KEY=sk-xxx                  # 阿里通义 Qwen（可选）
```

### B. CLI 命令

| 命令 | 说明 |
|------|------|
| `/compact` | 手动触发压缩 |
| `/resume` | 恢复旧会话 |
| `/resume <id>` | 恢复指定会话 |
| `/reset` | 清空对话记忆 |
| `/model` | 交互式切换模型 |
| `/model list` | 列出所有模型 |
| `/debug` | 调试模式 |
| `/log chat [n]` | 最近 N 条聊天记录 |
| `/log facts [n]` | 长期记忆 |
| `/log session [id]` | 会话详情 |
| `/log tool [n]` | 工具调用记录 |
| `/help` | 显示帮助 |

### C. 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env

# 3. 构建知识库
python buildLibrary.py

# 4. 启动对话
python cli.py
```

### D. 测试命令

```bash
# 运行全部测试
python -m pytest tests/ -q

# 运行核心测试
python -m pytest tests/test_core_*.py tests/test_nodes_*.py tests/test_graph_*.py -q

# 运行 Phase 6 测试
python -m pytest tests/test_node_*_diff.py tests/test_diff_history.py tests/test_engine_apply_diff.py -q
```

---

> **本文档是 Anima Agent 项目的单一事实来源（Single Source of Truth）。**  
> **所有架构决策、测试状态、文件统计以本文档为准。**
