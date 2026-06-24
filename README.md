# AniMate · 角色化 AI 对话伙伴

> BSP 图引擎 · 真流式输出 · 11+ 工具 · RAG 双路检索 · HITL 权限 · 情绪系统 · SQLite 日志 · 信任分 · Session 管理
>
> 当前角色：BanG Dream! 丰川祥子（Oblivionis）
>
> 源码量：~5,000 行（animate/core/）· 测试：416 个，全部通过

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env：填入对应 provider 的 API Key

# 3. 构建知识库
python buildLibrary.py

# 4. 启动对话
python cli.py
```

### CLI 命令

| 命令 | 说明 |
|------|------|
| `/compact` | 手动触发压缩 |
| `/resume` | 恢复旧会话（交互选择） |
| `/resume <id>` | 直接恢复指定会话 |
| `/reset` | 清空对话记忆 |
| `/model` | 交互式切换模型 |
| `/model list` | 列出所有可用模型 |
| `/model <name>` | 直接切换到指定模型 |
| `/debug` | 调试模式（节点流转 + 工具调用） |
| `/debug verbose` | 详细调试（含情绪切换） |
| `/log chat [n]` | 最近 N 条聊天记录 |
| `/log phase <trace_id>` | 指定 trace 的阶段事件 |
| `/log facts [n]` | 长期记忆（含信任评分） |
| `/log session [id]` | 会话列表/详情 |
| `/log tool [n]` | 工具调用记录 |
| `/log compression [n]` | 压缩记录 |
| `/log clear` | 清空所有日志 |
| `/help` | 显示帮助 |
| `exit` / `quit` | 退出 |

---

## 项目结构

```
AniMate/
├── cli.py                    # 主入口 CLI REPL（流式输出 + HITL 权限）
├── buildLibrary.py           # 知识库构建工具
├── config.yaml               # Provider 目录 + 压缩参数 + 日志轮转
├── animate/
│   └── core/
│       ├── config.py         # YAML 配置加载（惰性）
│       ├── constants.py      # 共享常量（emotion/gesture 列表）
│       ├── errors.py         # AgentError / LLMError / ToolError
│       ├── paths.py          # 数据路径中央配置
│       ├── engine/           # ★ BSP 图引擎
│       │   ├── graph.py      # Graph + GraphEngine（BSP 调度 + 冲突检测）
│       │   ├── node.py       # Node ABC（async + emit + NodeResult）
│       │   └── context.py    # RunContext + RunServices（强类型）
│       ├── agent/            # ★ Agent 框架
│       │   ├── agent.py      # Agent 门面 + compact/resume + create_default
│       │   ├── logging.py    # PhaseEventLogger（多计时器 + batch flush）
│       │   ├── response.py   # AgentResponse / ReflectionSignal
│       │   ├── permission.py # PermissionManager（HITL 权限管理）
│       │   └── nodes/        # ★ 7 个节点
│       │       ├── rag_vector.py     # 向量检索节点（并行）
│       │       ├── rag_keyword.py    # 关键词检索节点（并行）
│       │       ├── system_prompt.py  # 系统 prompt 构建
│       │       ├── merge.py          # 多路检索融合（不 clear messages）
│       │       ├── react.py          # LLM 调用 + ReAct + StreamingToolExecutor
│       │       ├── after.py          # emotion/gesture 校验
│       │       ├── reflect.py        # 质量评估 + 重试决策 + Analysis Scratchpad
│       │       ├── memory_node.py    # 长期记忆检索
│       │       └── marker_streamer.py # 流式 (emotion,gesture) 解析状态机
│       ├── rag/              # RAG 引擎
│       │   ├── VectorStore.py       # numpy 余弦相似度
│       │   ├── KeywordStore.py      # jieba 关键词倒排
│       │   ├── embedder.py          # 多 batch embedding
│       │   └── chunker.py           # 递归分块
│       ├── llm/              # LLM 客户端
│       │   ├── client.py     # OpenAICompatibleClient（同步 + 流式 + 重试）
│       │   └── models.py     # LLMResult, ToolCall
│       ├── memory/           # 记忆系统
│       │   ├── provider.py   # MemoryProvider ABC
│       │   ├── store.py      # MemoryStore（FTS5 + 信任评分 + regex 提取）
│       │   ├── default_provider.py # DefaultMemoryProvider（实现 + 工具注册）
│       │   └── conversation.py # 短期记忆工具函数
│       ├── context/          # 上下文管理
│       │   ├── manager.py    # ContextManager（token 追踪 + 渐进压缩 + session rotation）
│       │   ├── token_counter.py # TokenCounter（增量 tiktoken 计数）
│       │   └── strategies/   # Snip（L1）+ Compact（L4）压缩策略
│       ├── session/          # Session 管理
│       │   └── store.py      # SessionStore（生命周期 + rotation + 跨 session 检索）
│       ├── tools/            # 工具系统
│       │   ├── base.py       # LocalTool ABC（Fail-Closed 安全属性）
│       │   ├── registry.py   # ToolRegistry（含 Result Budgeting 50K）
│       │   ├── defaults.py   # 内置工具注册
│       │   ├── function/     # 11 个本地工具
│       │   └── mcp/          # MCP 服务（stdio 协议）
│       └── log/              # 日志基础设施
│           ├── logger.py     # setup_logger / set_log_level
│           └── log_db.py     # ChatLogDB（7 张表 + 日志轮转）
├── animate/data/             # ★ 数据层
│   ├── documents/            # RAG 知识文档（角色知识库）
│   ├── vectorlibrary/        # 向量库 .pkl
│   ├── keywordlibrary/       # 关键词库 .pkl
│   ├── logs/                 # chat_log.db（6 张表 + compression/tool_audit/emotion）
│   ├── memory/               # memory.db（FTS5 事实库 + 信任分）
│   ├── sessions/             # sessions.db（session 生命周期）
│   └── prompts/              # 角色人设 prompt
├── docs/                     # 项目文档
│   ├── README.md             # 本文档
│   ├── architecture-decision-records.md  # 架构决策记录
│   └── archive/              # 历史文档归档
│       ├── prd/              # 16 个历史 PRD（已实现，status 标注）
│       ├── tutorials/        # Phase 1-7 开发教程
│       ├── html/             # 架构图 HTML
│       ├── handoff/          # 交接文档
│       └── claude/           # 旧 Claude skill
└── tests/                    # 416 个测试
```

---

## 核心架构

### Pipeline

```
__entry__ → MemoryNode → fan_out → [RAGVectorNode, RAGKeywordNode, SystemPromptNode]
                                → join → MergeNode → ReactNode → AfterNode → ReflectNode
                                                                                │
                                      ← react (level 2-3, 重生成) ←─────────────┘
                                      ← __entry__ (level 4, 重检索) ←──────────┘
```

### BSP 图引擎

```
                    ┌──────────────────────┐
                    │    __entry__          │
                    └──────┬───────────────┘
                           │
                    ┌──────▼──────┐
                    │  Memory     │  ← MemoryNode（长期记忆检索）
                    └──────┬──────┘
                           │ fan_out
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐   ┌────────────┐   ┌────────────┐
   │RAGVector │   │RAGKeyword  │   │SystemPrompt│  ← 3 路并行
   └────┬─────┘   └─────┬──────┘   └─────┬──────┘
        └──────────────┬─────────────────┘
                       │ join
                       ▼
                 ┌──────────┐
                 │  Merge   │  ← 去重合并 + user input
                 └────┬─────┘
                      │
                 ┌──────────┐
                 │  React   │  ← LLM + ReAct + Tool + HITL
                 └────┬─────┘
                      │
                 ┌──────────┐
                 │  After   │  ← emotion/gesture 校验
                 └────┬─────┘
                      │
                 ┌───────────┐
                 │  Reflect  │  ← 质量评估 + 重试决策
                 └─────┬─────┘
                  ┌────┴────┐
                  ▼         ▼
              (结束)     react/before (重试/重检索)
```

### 关键设计

| 特性 | 实现 |
|------|------|
| **BSP 调度** | 超级步内无冲突节点全并行，冲突节点延迟一步 |
| **流式输出** | `asyncio.Queue` 桥接 emit 回调和 `yield`，char-by-char |
| **StreamingToolExecutor** | 只读工具在 LLM 流失时后台预执行，与聊天文本并行 |
| **HITL 权限** | 非只读工具（execute_python, write_file）首次需用户批准，session 内记住 |
| **Fail-Closed 工具** | 安全默认值（不并行、有副作用），schema 暴露给 LLM |
| **Result Budgeting** | 50K 字符上限，超限截断 + 存盘 |
| **Tool Call Snip** | 2K 字符上限截断超大 arguments |
| **System Re-Reminders** | 多轮 tool_call 后注入角色保持提醒 |
| **Analysis Scratchpad** | ReflectNode 先 `<analysis>` 分析再 `<summary>` 输出 JSON |
| **多计时器日志** | BSP 并行节点各自独立计时，batch flush 不阻塞事件循环 |
| **信任分系统** | regex 0.3 / LLM 0.7 / 检索晋升 capped 0.2 / 冲突 max 合并 |
| **Session Rotation** | 压缩时冻结旧 session，创建新 session + 父指针 |
| **日志轮转** | 按大小（50MB）+ 按时间（30 天）自动归档 |
| **代码执行** | subprocess 隔离，可超时杀死死循环 |
| **ReDoS 防护** | `regex` 库 + 2 秒 timeout |

---

## 测试覆盖

416 个测试，全部通过（38s）

### 测试模块

| 模块 | 文件 | 测试数 |
|------|------|--------|
| Agent compact/resume | test_agent_compact_resume.py | 5 |
| Agent shutdown | test_agent_shutdown.py | 5 |
| Agent integration | test_agent_integration.py | 8 |
| Core Agent | test_core_agent.py | 5 |
| Core Config | test_core_config.py | 16 |
| Core DataClasses | test_core_dataclasses.py | 8 |
| Core LLM | test_core_llm.py | 9 |
| Core Memory | test_core_memory.py | 4 |
| Core Nodes | test_core_nodes.py | 13 |
| Core Tools | test_core_tools.py | 5 |
| Context Manager | test_context_manager.py | 20 |
| Graph Engine | test_graph_engine.py | — |
| Log DB | test_log_db.py + extended | — |
| Log Rotation | test_log_rotation.py | 2 |
| Logging Parallel | test_logging_parallel.py | 6 |
| Marker Streamer | test_marker_streamer.py | — |
| Memory Store | test_memory_store.py | 25 |
| Memory Trust | test_memory_trust.py | 9 |
| Merge Node No Clear | test_merge_node_no_clear.py | 6 |
| Model Switch | test_model_switch.py | 15 |
| Session Store | test_session_store.py | 25 |
| Token Counter | test_token_counter.py | 11 |
| Tool Args Snip | test_tool_args_snip.py | 4 |
| CLI Commands | test_cli_commands.py | — |

---

## 开发里程碑

### Phase 1: 核心架构
- Node 状态机 + Agent 门面 + EventBus + ToolRegistry
- **测试**: 96 → 全部通过

### Phase 2: 目录重组 + 数据层
- core/io/data 三层分离 + paths.py + ChatLogDB
- **测试**: 133 → 全部通过

### Phase 3: BSP 图引擎
- Graph + GraphEngine + 冲突检测 + 条件边 + fan_out/join
- **测试**: 180+ → 全部通过

### Phase 3.5: Before 并行化
- RAGVector + RAGKeyword + SystemPrompt + Merge 四节点并行
- **测试**: 200+ → 全部通过

### Phase 4: 日志 + 长期记忆
- PhaseEventLogger + ChatLogDB + 事实提取 + 长期记忆注入
- **测试**: 250+ → 全部通过

### Phase 5: CLI 完整接入 + 日志整改 + 信任分
- /compact /resume CLI + 多计时器日志 + 信任分 + 日志轮转 + 杂项修复
- **测试**: 416 → 全部通过

---

## 配置

### Provider 目录（config.yaml）

```yaml
llm:
  deepseek:
    name: DeepSeek
    base_url: https://api.deepseek.com/v1
    models: [deepseek-v4-flash, deepseek-v4-pro]
    default: deepseek-v4-flash
  zhipu:
    name: 智谱 GLM
    base_url: https://open.bigmodel.cn/api/paas/v4
    models: [glm-4.7, glm-4.5, glm-4v-flash]
  qwen:
    name: 阿里通义 Qwen
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    models: [qwen-3, qwen-2.5-72b-instruct]

compress:
  threshold: 0.70        # 触发压缩的 token 比例
  head_rounds: 5         # 保护的最早轮数
  tail_rounds: 10        # 保护的最近轮数
  compact_reserve: 30000 # 摘要预留 token
  max_failures: 3        # 连续失败上限

log:
  max_db_size_mb: 50     # DB 文件大小上限（MB）
  max_age_days: 30       # 最早记录年龄上限（天）
```

### 环境变量（.env）

```
ANIMATE_LLM_PROVIDER=deepseek
ANIMATE_EMBEDDING_PROVIDER=dashscope
OPENAI_CHAT_API_KEY=sk-xxx...
OPENAI_EMBEDDING_API_KEY=sk-xxx...
ZAI_API_KEY=sk-xxx...         # 智谱 GLM 可选
QWEN_API_KEY=sk-xxx...        # 阿里通义 Qwen 可选
```

---

## 技术栈

| 层 | 选型 |
|---|------|
| LLM | DeepSeek V4 Flash（1M context）/ Pro / 智谱 GLM / 阿里 Qwen |
| Embedding | DashScope text-embedding-v4 |
| 工具执行 | subprocess（隔离 + 可超时） |
| 正则 | regex（内置 ReDoS timeout） |
| 配置 | YAML（config.yaml 惰性加载） |
| 日志 | SQLite 7 张表（ChatLogDB）+ 多计时器事件体系 |
| 记忆 | SQLite + FTS5（MemoryStore）+ 信任评分 |
| 图引擎 | BSP 调度 + 异步生成器 + 冲突检测 |
| 流式 | char-by-char replay + inline (emotion,gesture) marker |
| 测试 | pytest（416 tests） |
| MCP | stdio 协议（filesystem / memory / github / brave-search） |

---

## 许可

MIT
