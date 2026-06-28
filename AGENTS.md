# CLAUDE.md

Anima Agent is a character-roleplay agent that wraps an LLM in a "persona skin" backed by a local RAG knowledge base.

## Commands

```bash
# Run all tests
python -m pytest tests/ -q

# Run core tests only
python -m pytest tests/test_core_*.py tests/test_nodes_*.py tests/test_graph_*.py tests/test_budgeting.py tests/test_re_reminders.py tests/test_scratchpad.py tests/test_safety_tools.py tests/test_engine_context.py tests/test_permission.py tests/test_registry_find.py tests/test_react_hitl.py -q

# Build vector + keyword libraries for a character
python buildLibrary.py

# Run CLI REPL
python cli.py

# Install deps
pip install -r requirements.txt
```

## 五层架构

```
┌─────────────────────────────────────────────────────────────────┐
│  接口层 (Interface Layer)                                        │
│  FastAPI REST API / WebSocket / CLI REPL / MCP stdio            │
├─────────────────────────────────────────────────────────────────┤
│  UI 层 (UI Layer)                                               │
│  VTuber 前端 / Web 聊天界面 / Desktop App                       │
├─────────────────────────────────────────────────────────────────┤
│  表现层 (Presentation Layer)                                     │
│  TTS: CosyVoice 3.0 / VRM: three-vrm + VRM SDK                │
├─────────────────────────────────────────────────────────────────┤
│  Core 层 (核心引擎)                                              │
│  BSP GraphEngine → 8 节点流水线 → Agent 门面                      │
├─────────────────────────────────────────────────────────────────┤
│  数据层 (Data Layer)                                            │
│  SQLite × 4 + 向量库 + 关键词库 + 文档                           │
└─────────────────────────────────────────────────────────────────┘

依赖方向：上层只能依赖下层（↓），禁止反向依赖（↑）
接口层 → UI 层 → 表现层 → Core 层 → 数据层
```

### 各层职责

| 层 | 状态 | 职责 | 目录 |
|----|------|------|------|
| **接口层** | ✅ CLI 已实现, FastAPI 待开发 | 用户交互入口、协议适配 | `anima/api/` (计划中), `cli.py` |
| **UI 层** | 🔲 待开发 | 可视化界面、3D 渲染窗口 | `frontend/` (计划中) |
| **表现层** | 🔲 待开发 | TTS 语音合成 + 3D 角色动画 | `anima/presentation/` (计划中) |
| **Core 层** | ✅ 完成 | 核心对话引擎 | `anima/core/` |
| **数据层** | ✅ 完成 | 持久化存储 | `anima/data/` |

---

## Core 层架构

### Graph

```
__entry__ → MemoryNode → fan_out → [RAGVectorNode, RAGKeywordNode, SystemPromptNode]
                                 → join → MergeNode → ReactNode → AfterNode → ReflectNode
                                                                                │
                                      ← react (level 2-3, 重生成) ←─────────────┘
                                      ← __entry__ (level 4, 重检索) ←──────────┘
```

### Nodes

| Node | File | Role |
|------|------|------|
| **MemoryNode** | `memory_node.py` | long-term fact prefetch |
| **RAGVectorNode** | `rag_vector.py` | embed + vector search (parallel) |
| **RAGKeywordNode** | `rag_keyword.py` | keyword search (parallel) |
| **SystemPromptNode** | `system_prompt.py` | persona + instruction + memory |
| **MergeNode** | `merge.py` | dedup + merge RAG, inject history |
| **ReactNode** | `react.py` | LLM call + ReAct loop + StreamingToolExecutor + HITL |
| **AfterNode** | `after.py` | emotion/gesture validation |
| **ReflectNode** | `reflect.py` | quality evaluation (analysis scratchpad) + retry decision |

### Node Interface

```python
class Node(ABC):
    reads: set[str] = set()    # fields this node reads (conflict detection)
    writes: set[str] = set()   # fields this node writes

    @abstractmethod
    async def run(self, ctx: RunContext, emit) -> NodeResult:
        """Execute node logic. Return NodeResult(next_node=..., diff=...)."""
```

### Key patterns

- **BSP scheduling**: Parallel nodes within a superstep if no write conflicts
- **Return-Diff Architecture** (Phase 6): Nodes return `NodeResult(diff={...})` instead of writing ctx directly. Engine auto-applies via `_apply_diff` with FIELD_WRITERS enforcement.
- **StreamingToolExecutor**: Read-only tools execute in background during LLM streaming
- **HITL**: `PermissionManager` prompts user for non-read-only tools (execute_python, write_file), remembers per session
- **Re-Reminders**: `<system-reminder>` injected after each tool_call to prevent persona drift
- **Result Budgeting**: 50K char cap per tool output, oversized → truncated + saved to disk
- **Tool Call Snip**: 2K char cap per tool_call arguments, oversized → truncated
- **Fail-Closed tools**: New tools default to serial, non-read-only, non-destructive
- **Multi-timer logging**: BSP parallel nodes have independent timers, batch flush
- **Trust scoring**: regex facts 0.3, LLM facts 0.7, retrieval boost (capped at 0.2)
- **Session rotation**: compress → freeze old session → create new session
- **Log rotation**: auto-archive by size (50MB) or age (30 days)
- **Audit logging**: LogCollector routes emit events → compression_logs, tool_audit, emotion_logs, long_term_facts
- **Token fallback**: tiktoken `estimate_tokens()` when API streaming usage unavailable
- **DiffHistory**: SQLite-backed node diff persistence for replay/debugging

### Agent public methods

```python
agent = Agent.create_default(llm, persona, vs, ks,
    log_db=..., memory_provider=..., session_store=...)

agent.chat("hello")           # sync
agent.chat_stream("hello")    # async generator
agent.compact()               # manual compress → {status, message}
agent.resume(session_id)      # restore old session → bool
agent.reset()                 # clear messages, freeze session
agent.shutdown()              # close all DB connections
```

### Tool System

```python
from animate.core.tools.registry import ToolRegistry
from animate.core.tools.function.time_tool import TimeTool

registry = ToolRegistry()
registry.register_tool(TimeTool())
```

Each tool declares safety attributes:
```python
class MyTool(LocalTool):
    is_read_only: bool = False       # default: has side effects
    is_parallel_safe: bool = False   # default: serial execution
    is_destructive: bool = False     # default: non-destructive
```

### Permissions

```python
from animate.core.agent import PermissionManager

async def callback(name, args):
    return input("Allow? (y/N): ").lower() in ("y", "yes")

pm = PermissionManager(callback=callback)  # auto_mode=True for QQ bot
agent = Agent.create_default(..., permission_manager=pm)
```

---

## 接口层 (Interface Layer)

### FastAPI REST + WebSocket

- **框架**: FastAPI (async 原生, WebSocket 一等公民, 自动 OpenAPI)
- **ASGI**: uvicorn (生产级, 支持热重载)
- **事件格式**: JSON Lines (流式友好, 前端易解析)

### API 端点

```
POST   /api/chat              → 同步对话（等待完整回复）
POST   /api/chat/stream       → SSE 流式对话
WS     /api/ws/chat           → WebSocket 双向流式
GET    /api/sessions          → 会话列表
POST   /api/sessions          → 创建新会话
DELETE /api/sessions/{id}     → 删除会话
GET    /api/health            → 健康检查
```

### 目录

- `anima/api/app.py` — FastAPI 应用入口（计划中）
- `anima/api/routes/` — 路由模块（计划中）
- `cli.py` — CLI REPL 接口（已实现）

---

## 表现层 (Presentation Layer)

### TTS: CosyVoice 3.0

- **部署模式**: 本地 GPU 推理 / 远程 API / Docker 容器
- **客户端**: `TTSClient` ABC + `CosyVoiceClient` 实现
- **流式输出**: `async synthesize()` → `AsyncIterator[bytes]` PCM/OGG
- **情绪映射**: `emotion → (speed, pitch, energy, style_tag)` 映射表
- **集成**: 消费 Agent 事件流 (`text_token`, `emotion.update`)

### 角色模型: VRM + three-vrm

- **渲染**: Three.js r160+ + @pixiv/three-vrm v3
- **表情**: `emotion → VRM Expression 映射`（blend shape 驱动）
- **手势**: `gesture → 骨骼动画 clip`（AnimationMixer）
- **口型**: `viseme 同步`（音频 FFT 或 LLM 标记驱动）
- **事件**: WebSocket 接收 Agent 事件 → 驱动 VRM 状态

### 目录

- `anima/presentation/tts/` — TTS 客户端（计划中）
- `anima/presentation/vrm/` — VRM 控制器（计划中）
- `frontend/src/vrm/` — 前端 VRM 模块（计划中）
- `assets/models/` — VRM 模型文件（计划中）
- `assets/animations/` — 手势动画文件（计划中）

---

## Hard rules

1. **No RAG frameworks.** No LangChain, LlamaIndex, Chroma, FAISS, Qdrant.
2. **Single LLM/embedding entry points** via `animate.core.config`.
3. **Persona lives in a prompt file.** Character voice is in `prompts/<name>_persona.txt`.
4. **No secrets in code or commits.** API keys come from `.env` (gitignored).
5. **All Node dependencies injected.** Constructor for stable deps, `ctx.services` for runtime.
6. **层级依赖只能向下。** 上层可以依赖下层，禁止反向依赖：
   - 接口层 → UI 层 → 表现层 → Core 层 → 数据层 ✅
   - 数据层 → Core 层 ❌ / 表现层 → 接口层 ❌
   - Core 层不得 import `anima/api/`、`anima/presentation/`、`frontend/`
   - 表现层不得 import `anima/api/`

## Where to put things

| Adding... | Put it in... |
|-----------|-------------|
| A new node | `anima/core/agent/nodes/`, register in agent.py `_build_graph` |
| A new tool | New `LocalTool` subclass in `anima/core/tools/function/` |
| A new knowledge file | `data/documents/` — re-run `buildLibrary.py` |
| A change to RAG | `anima/core/rag/` |
| A new LLM/embedding provider | `config.yaml` |
| Persona tweaks | `prompts/<name>_persona.txt` (not Python) |
| A new shared constant | `anima/core/constants.py` |
| Compression params | `config.yaml` → `compress` section |
| Log rotation params | `config.yaml` → `log` section |
| API endpoint (FastAPI) | `anima/api/routes/` (Phase 8) |
| TTS 客户端 | `anima/presentation/tts/` (Phase 7) |
| VRM 控制器 | `anima/presentation/vrm/` (Phase 7) |
| 前端 VRM 模块 | `frontend/src/vrm/` (Phase 7-9) |
| WebSocket 事件处理 | `anima/api/ws/` (Phase 8) |

---

## Phase 进度

### Phase 1-5: 已完成 ✅

| 阶段 | 名称 | 核心成果 |
|------|------|----------|
| Phase 1 | 核心架构 | Node 状态机 + Agent 门面 + EventBus + ToolRegistry |
| Phase 2 | 目录重组 + 数据层 | core/io/data 三层分离 + paths.py + ChatLogDB |
| Phase 3 | BSP 图引擎 | Graph + GraphEngine + 冲突检测 + 条件边 + fan_out/join |
| Phase 3.5 | Before 并行化 | RAGVector + RAGKeyword + SystemPrompt + Merge 四节点并行 |
| Phase 4 | 日志 + 长期记忆 | PhaseEventLogger + ChatLogDB + 事实提取 + 长期记忆注入 |
| Phase 5 | CLI 完整接入 + 日志整改 + 信任分 | /compact /resume CLI + 多计时器日志 + 信任分 + 日志轮转 |
| Phase 5.2 | 全量 Bug 修复 + 审计日志 | 23 个 bug 审计，修复 21 个 |

### Phase 6: Return-Diff 架构重构 ✅ (2026-06-28)

#### Phase 6.1 ✅ (2026-06-26)
- NodeResult.diff field
- RunContext.snapshot/restore
- GraphEngine._apply_diff + FIELD_WRITERS enforcement
- DiffHistory SQLite persistence
- 23 tests

#### Phase 6.2 ✅ (2026-06-28)
- [x] MemoryNode → diff
- [x] AfterNode → diff + 显式 emit emotion.final/gesture.final
- [x] ReflectNode → diff
- [x] RAGVectorNode → diff
- [x] RAGKeywordNode → diff
- [x] SystemPromptNode → diff（无双写）
- [x] _apply_diff 重构（emotion/gesture 去 auto final emit + 去判等）
- [x] MergeNode → diff
- [x] ReactNode → diff 6 字段（方案 A，流式 ctx 直写保留）
- [x] DiffHistory 7 字段 async + WAL + 独立 DB anima/data/trace/
- [x] checkpoint/restore + _capture_inputs + duration_ms
- [x] 8 个边界情况全覆盖
- [x] Agent 兜底 emit emotion.final
- [x] 死字段清理（next_node=, data={}, 后备记忆通路）
- **测试**: 493 passed

### Phase 7: 表现层基础（TTS + VRM）🔲 计划中

| 任务 | 优先级 | 说明 |
|------|--------|------|
| CosyVoice 3.0 集成 | 高 | TTS 语音合成，支持 emotion 情绪映射 |
| VRM 模型加载 | 高 | three-vrm 加载 .vrm 角色模型 |
| 情绪 → 表情映射 | 高 | emotion/gesture → VRM blend shape |
| 音频流式播放 | 中 | TTS 输出 → 音频流 → 播放器 |
| 口型同步 | 中 | 音频 → viseme → VRM 口型动画 |
| 手势动画 | 低 | gesture → VRM 动画 clip |

### Phase 8: 接口层（FastAPI）🔲 计划中

| 任务 | 优先级 | 说明 |
|------|--------|------|
| FastAPI REST API | 高 | /chat, /chat_stream, /health 端点 |
| WebSocket 流式输出 | 高 | 替代 HTTP polling |
| SSE 事件流 | 中 | Server-Sent Events |
| 静态文件服务 | 中 | VRM 模型、音频文件 |
| API Key 认证 | 中 | Bearer token |
| CORS 配置 | 低 | 跨域支持 |

### Phase 9: 桌面应用🔲 计划中

| 任务 | 优先级 | 说明 |
|------|--------|------|
| Electron/Tauri 打包 | 高 | 桌面应用容器 |
| 3D 渲染窗口 | 高 | three.js + VRM 实时渲染 |
| 音频输出 | 高 | TTS 音频播放 |
| 系统托盘 | 中 | 后台运行 |
| 自动更新 | 低 | 版本管理 |

### Phase 6 测试成果

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
