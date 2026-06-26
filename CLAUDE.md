# CLAUDE.md

AniMate is a character-roleplay agent that wraps an LLM in a "persona skin" backed by a local RAG knowledge base.

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

## Architecture

### Graph

```
__entry__ → MemoryNode → fan_out → [RAGVectorNode, RAGKeywordNode, SystemPromptNode]
                                 → join → MergeNode → ReactNode → AfterNode → ReflectNode
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

## Hard rules

1. **No RAG frameworks.** No LangChain, LlamaIndex, Chroma, FAISS, Qdrant.
2. **Single LLM/embedding entry points** via `animate.core.config`.
3. **Persona lives in a prompt file.** Character voice is in `prompts/<name>_persona.txt`.
4. **No secrets in code or commits.** API keys come from `.env` (gitignored).
5. **All Node dependencies injected.** Constructor for stable deps, `ctx.services` for runtime.

## Where to put things

| Adding... | Put it in... |
|-----------|-------------|
| A new node | `animate/core/agent/nodes/`, register in agent.py `_build_graph` |
| A new tool | New `LocalTool` subclass in `animate/core/tools/function/` |
| A new knowledge file | `data/documents/` — re-run `buildLibrary.py` |
| A change to RAG | `animate/core/rag/` |
| A new LLM/embedding provider | `config.yaml` |
| Persona tweaks | `prompts/<name>_persona.txt` (not Python) |
| A new shared constant | `animate/core/constants.py` |
| Compression params | `config.yaml` → `compress` section |
| Log rotation params | `config.yaml` → `log` section |

## Next Phase (6): Self-Built Return-Diff Architecture (No LangGraph Dependency)

Migrate nodes from directly writing ctx to returning diffs. Existing GraphEngine stays — only change the Node interface and `_run_node`.

```
# Current
node.run(ctx, emit)  → writes ctx.some_field = value

# Phase 6
node.run(ctx, emit) → returns NodeResult(diff={"field": value})
_run_node(root):
    if result.diff:
        await self._apply_diff(ctx, result.diff, name, emit)  # engine applies
```

Benefits: zero-mock testing, FIELD_WRITERS auto-activates, no new dependencies.

### Phase 6.1 ✅ (2026-06-26)
- NodeResult.diff field
- RunContext.snapshot/restore
- GraphEngine._apply_diff + FIELD_WRITERS enforcement
- DiffHistory SQLite persistence
- 23 tests

### Phase 6.2 🔄 (in progress)
- [x] MemoryNode → diff
- [x] AfterNode → diff
- [x] ReflectNode → diff
- [ ] RAGVectorNode → diff
- [ ] RAGKeywordNode → diff
- [ ] SystemPromptNode → diff
- [ ] MergeNode → diff
- [ ] ReactNode → diff
