> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 5
> 概要: 日志系统全面整改 — 并行兼容 + CLI 接入

# PRD: 日志系统全面整改 — 并行兼容 + 数据补全 + CLI 接入

## Problem Statement

AniMate 的图引擎 (BSP) 已迭代到 7 个并行/串行节点 + session rotation + 长期记忆，但日志系统停留在 Phase 4 的原始设计，存在 10+ 个问题，覆盖三个维度：数据正确性、覆盖面、工程接入。

### 具体问题

**1. BSP 并行节点的耗时数据全是垃圾（🔴）**

`PhaseEventLogger` 使用单 `_current_node` 计时器。当 BSP fan_out 并行执行 RAGVector / RAGKeyword / SystemPrompt 时，三个节点并发发射 `node.start`，单计时器无法区分并行，前两个节点的 `duration_ms` 被截断到几乎 0。所有串行节点（merge → react → after → reflect）的耗时正确，但占 ~50% 的 RAG 并行节点数据不可信。

**2. CLI 未接入任何新模块（🟠）**

`cli.py` 的 `main()` 用 `Agent.create_default()` 创建 Agent，该工厂方法不传 `log_db`、`memory_provider`、`session_store`。结果：
- Agent 内部自行创建 ChatLogDB（路径相同，但独立实例）
- MemoryProvider 和 SessionStore 完全未初始化
- 长期记忆和 session rotation 在 CLI 中零作用

**3. 两套事实库并行（🟠）**

`ChatLogDB.long_term_facts` 表（Phase 4 旧路）和 `MemoryStore.facts` 表（FTS5 新路）同时存在。CLI 的 `/log facts` 命令查的是旧表，`MemoryProvider` 写的是新表。即使接入了 MemoryProvider，CLI 也看不到数据。

**4. Agent.shutdown() 泄漏资源（🟠）**

`Agent.shutdown()` 只释放 MCP 客户端，不关闭 `ChatLogDB`、`SessionStore`、`MemoryProvider`。每个 Agent 实例泄漏 3 个 SQLite 连接。在重复 reset 的场景下可能导致 WAL 文件膨胀。

**5. `tool.denied` 事件被静默忽略（🟡）**

ReactNode 的 HITL 拒绝发射 `emit("tool.denied", ...)`，但 `PhaseEventLogger.handle_event()` 没有对应的处理分支。HITL 拒绝调用没有任何 DB 审计记录。

**6. `emotion.update` 事件被忽略（🟡）**

流式过程中每轮 emotion/gesture 变化通过 `emotion.update` 事件实时输出，但 PhaseEventLogger 不处理该事件类型。情绪变化时间线无法从 DB 回溯。

**7. 节点异常时 `status` 一律写 `"ok"`（🟡）**

所有 node 的内部异常都被 catch 并退化为空兜底，但 `node.done` emit 不携带错误状态。`phase_events` 表的 `error` 和 `status` 字段始终为默认值，节点级别的失败在 DB 中不可见。

**8. 图引擎异常不进 DB（🟡）**

`agent.py` 的 `_run_engine()` 外层 catch 只写了 `logger.error()`，没有写入 `chat_logs` 表。引擎崩溃时，chat_logs 记录里只有 fallback response，无任何崩溃标记。

**9. `_summarize_node` 缺少 memory 节点 case（🔵）**

MemoryNode 的 `node.done` 携带 `count` 字段，但 `_summarize_node` 没有 `"memory"` 分支，回退到 `str(extra)`，输出格式为 `"{'count': 3}"`。

**10. SQLite 写入在异步热路径上同步阻塞（🔵）**

`handle_event` → `_end_node` → `self._db.log_phase()` 每条事件都执行一次完整的 `INSERT` + `commit()`。7 个节点 + N 次 tool call 产生 7+N 次同步磁盘 IO，阻塞 asyncio 事件循环。

**11. 没有日志轮转（🔵）**

`chat_log.db`、`memory.db`、`sessions.db` 只增不删，长期运行的进程会让 DB 文件无限增长。CLI 只有手动 `/log clear`，没有自动归档或大小限制。

**12. ReactNode 的 `duration_ms` 被 tool.start 截断（🔵）**

ReActNode 发射 `tool.start` 时，`_handle_node_start("tool:xxx")` 调用 `_end_node("react")`，提前终止了 ReactNode 的计时器。ReactNode 的 phase_events 记录的实际是"首次 tool call 前的时间"而非全耗时。

## Solution

分三个 Workstream 并行推进，每个 Workstream 独立可测试、独立可部署：

### Workstream A — BSP 并行日志引擎（修 P0 + 防 P2/P3）

**核心思想：弃用单 `_current_node` 计时器，改为多计时器 + 延迟写入。**

PhaseEventLogger 不再在 `_handle_node_start` 时结束上一个节点，而是维护 `_node_timers: dict[str, float]` 字典，每个节点独立计时。`node.done` 时才结束指定节点的计时并写入 DB。

并行节点同时有多个活跃计时器叠加，互不干扰。串行节点同样支持（同时只有一个活跃计时器）。

同时利用这个重构，把之前缺失的事件类型（`emotion.update`、`tool.denied`、`compression.*`、`session.*`）统一加进去，不额外增加架构负担。

数据库写入改为批量写入 + 延迟 flush，不在事件循环热路径上做同步 commit。

### Workstream B — CLI 全模块接入 + 事实库统一

`cli.py` 创建 Agent 时传递 `log_db`、`memory_provider`、`session_store`。废弃 `ChatLogDB.long_term_facts` 表，统一走 `MemoryStore.facts`。CLI 的 `/log facts` 命令改为查询 `MemoryStore`。Agent.shutdown() 关闭所有资源。

新增 `/log session`、`/log compression` 命令。

### Workstream C — 新数据库表 + 审计能力

- `compression_logs` 表记录每次压缩的时间、压缩前/后 token、head/tail/middle 轮数、是否成功、rotated session_id
- `tool_audit` 表记录每次工具调用的入参、耗时、输出截断、HITL 状态（approved/denied）
- `emotion_log` 表记录每轮 emotion/gesture 变化时间线

现有 `chat_logs` 表增加 `engine_crashed` 和 `node_failures` 字段。

---

## User Stories

### Workstream A

1. 作为一名开发者，我希望 RAGVectorNode / RAGKeywordNode / SystemPromptNode 并行执行时各自的 `duration_ms` 在 phase_events 中准确，不互相干扰
2. 作为一名开发者，我希望并行节点的开始和结束事件独立追踪，不会因为单个计时器导致第一个启动的节点被截断
3. 作为一名开发者，我希望 `tool.denied` 事件被记录到 DB，以便审计用户拒绝了哪些工具调用
4. 作为一名开发者，我希望 `emotion.update` 事件被记录到 DB，以便后期分析情绪变化趋势
5. 作为一名开发者，我希望节点抛异常时 `phase_events` 的 `status` 字段写 `"error"`，`error` 字段记录异常摘要
6. 作为一名开发者，我希望图引擎抛异常时 `chat_logs` 表能记录崩溃标记，而不是用 fallback 回复掩盖
7. 作为一名开发者，我希望日志写入使用批量 flush，不在 async 事件循环热路径上做同步 SQLite commit
8. 作为一名开发者，我希望 ReactNode 的 `duration_ms` 反映 LLC 全部耗时（含工具执行），而非只到第一次 tool call
9. 作为一名开发者，我希望旧日志参数（log 目录、flush 间隔）可从 config.yaml 读取

### Workstream B

10. 作为一名 CLI 用户，我希望启动时 Agent 自动加载长期记忆和 session 管理，不需要手动配置
11. 作为一名 CLI 用户，我希望 `/log facts` 显示的是当前 MemoryProvider 中的事实（含 trust_score），而不是旧的孤立表
12. 作为一名 CLI 用户，我希望 `/log facts` 输出中能看到事实的信任评分和分类
13. 作为一名 CLI 用户，我希望 `Agent.reset()` 后能通过 `/log session` 查看历史 session 列表
14. 作为一名 CLI 用户，我希望 `/log session <id>` 能查看指定 session 的消息摘要
15. 作为一名 CLI 用户，我希望 `/log compression` 能查看每次压缩的前后 token 对比
16. 作为一名开发者，我希望 Agent.shutdown() 关闭所有 DB 连接（log_db、session_store、memory_provider）
17. 作为一名开发者，我希望 `create_default` 工厂方法接受可选的 log_db / memory_provider / session_store 参数
18. 作为一名测试者，我希望 CLI 集成测试验证 memory provider 和 session store 的正常初始化

### Workstream C

19. 作为一名开发者，我希望每次压缩操作在 `compression_logs` 中写入一条记录，包含压缩前/后 token、head/tail/middle 轮数、是否成功、目标 session_id
20. 作为一名开发者，我希望每次工具调用在 `tool_audit` 表中写入记录，包含工具名、入参 JSON、耗时 ms、HITL 状态（approved/denied/auto）、输出截断
21. 作为一名开发者，我希望 `emotion_log` 表能按 trace 查询，看到每轮对话中的情绪变化时间线
22. 作为一名开发者，我希望 `chat_logs` 表新增 `engine_crashed` 字段，标记引擎异常退出
23. 作为一名开发者，我希望 `chat_logs` 表新增 `node_failures` 字段，记录本轮节点失败列表
24. 作为一名开发者，我希望所有新表有适当的索引，支持按 trace_id 和时间范围查询

### 跨 Workstream

25. 作为一名开发者，我希望所有表增加 `created_at` 索引，支持按时间范围清理旧数据
26. 作为一名开发者，我希望日志轮转策略可配置：按大小（max_db_size_mb）或按时间（max_age_days），超出时自动归档或清理
27. 作为一名开发者，我希望日志文件路径集中在 `animate/core/paths.py` 中，不分散在各模块
28. 作为一名测试者，我希望 Workstream 之间有明确的接口契约，不耦合

---

## Implementation Decisions

### Workstream A — 并行日志引擎

**文件变更：** logging.py（重写）、可能小改 engine/graph.py（补 event 发射）

**PhaseEventLogger 重构：**

保持对外接口不变（`on_chat_start`、`handle_event`、`on_chat_end`），内部实现改为多计时器：

```python
# 旧：单 _current_node 指针 + 单 _node_timers dict
# 新：独立计时 + 延迟写入

class PhaseEventLogger:
    def __init__(self, db):
        self._timers: dict[str, float] = {}    # name → start_time，多个可并存
        self._event_buffer: list[dict] = []     # 延迟写入缓冲区
        
    def _start_node(self, name: str):
        """启动节点计时。允许多个节点同时计时（BSP 并行）。"""
        self._timers[name] = time.monotonic()
    
    def _end_node(self, name: str, ...):
        """结束指定节点的计时。写入 event_buffer（非立即 commit）。"""
        start = self._timers.pop(name, None)
        self._event_buffer.append({...})
    
    def _flush(self):
        """批量写入 + 单次 commit。"""
```

**事件覆盖范围扩展：**

`handle_event` 新增处理以下事件类型：

| 事件类型 | 动作 |
|----------|------|
| `emotion.update` | 写入 emotion_log 缓冲区 |
| `tool.denied` | 写入 tool_audit 缓冲区 |
| `compression.start` | 记录压缩上下文 |
| `compression.done` | 写入 compression_logs |
| `session.finalize` | 记录 session 轮换 |

**Node 状态传播：**

node 发射 `node.done` 时若处于异常路径，在 extra 中携带 `status: "error"` 和 `error: str`。PhaseEventLogger 识别后将 error 写入 phase_events。

**react 计时截断修复：**

react 发射 `tool.start` 时不再调用 `_end_node` 结束自己是自然结果——多计时器设计下，`tool.start` 只创建新计时器，不影响已有的 react 计时器。

**热路径优化：**

- `_end_node` 只 append 到 buffer，不 commit
- `_flush` 在 `on_chat_end` 时调用一次，合并所有缓冲写入 + 单次 commit
- 配置项 `log.flush_interval` 控制中间 flush 时机（默认每 10 条事件或 chat_end 时）

### Workstream B — CLI 全接入

**文件变更：** cli.py（Agent 创建部分）、agent.py（create_default + shutdown）、paths.py（数据库路径）

**Agent.create_default 扩展：**

```python
@classmethod
def create_default(cls, llm, persona, vector_store, keyword_store, 
                   enable_mcp=True, permission_manager=None,
                   log_db=None, memory_provider=None, session_store=None): ...
```

**cli.py Agent 创建改为：**

```python
from animate.core.session.store import SessionStore
from animate.core.memory.default_provider import DefaultMemoryProvider
from animate.core.memory.store import MemoryStore
from animate.core.paths import db_dir

session_store = SessionStore(db_dir / "sessions.db")
memory_store = MemoryStore(db_dir / "memory.db")
memory_provider = DefaultMemoryProvider(memory_store)
log_db = ChatLogDB()

agent = Agent(
    llm=llm, persona=persona,
    vector_store=vector_store,
    keyword_store=keyword_store,
    tools=tools, mcp_clients=mcp_clients,
    permission_manager=perm_mgr,
    log_db=log_db,
    memory_provider=memory_provider,
    session_store=session_store,
)
```

**agent.py shutdown 扩展：**

```python
def shutdown(self):
    for client in self._mcp_clients:
        try: client.stop()
        except: pass
    self._mcp_clients.clear()
    if self._session_store:
        try: self._session_store.close()
        except: pass
    if self._memory_provider:
        try: self._memory_provider.shutdown()
        except: pass
    # ChatLogDB 由 PhaseEventLogger 持有，在 shutdown 时关闭
    if self._phase_logger:
        try: self._phase_logger.close()
        except: pass
```

**事实库统一：**

- `ChatLogDB.long_term_facts` 表和 `query_facts`/`add_fact` 等方法标记为 `@deprecated`
- CLI 的 `/log facts` 改为查询 `MemoryStore.facts` 表
- 旧的 `long_term_facts` 表只读保留，不写入新数据

**CLI 新增命令：**

| 命令 | 功能 |
|------|------|
| `/log session` | 列出所有 session（含已冻结），显示 active/frozen 状态 |
| `/log session <id>` | 查看指定 session 的消息摘要和轮换历史 |
| `/log compression` | 列出最近压缩记录（时间、前后 token、是否成功） |
| `/log tool` | 列出最近工具调用记录（工具名、耗时、HITL 状态） |

### Workstream C — 新表 + 审计

**ChatLogDB 新增表：**

```sql
-- 压缩日志
CREATE TABLE IF NOT EXISTS compression_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    compress_count INTEGER DEFAULT 0,
    success     INTEGER DEFAULT 1,
    before_tokens INTEGER DEFAULT 0,
    after_tokens  INTEGER DEFAULT 0,
    head_rounds INTEGER DEFAULT 0,
    middle_msgs INTEGER DEFAULT 0,
    tail_rounds INTEGER DEFAULT 0,
    old_session_id TEXT DEFAULT '',
    new_session_id TEXT DEFAULT '',
    error_msg   TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 工具审计
CREATE TABLE IF NOT EXISTS tool_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    round_num   INTEGER DEFAULT 0,
    tool_name   TEXT NOT NULL,
    input_args  TEXT DEFAULT '{}',
    output_summary TEXT DEFAULT '',
    output_length INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    hitl_status TEXT DEFAULT 'auto',    -- approved | denied | auto
    status      TEXT DEFAULT 'success', -- success | error | blocked
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 情绪变化日志
CREATE TABLE IF NOT EXISTS emotion_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    sequence    INTEGER DEFAULT 0,
    emotion     TEXT DEFAULT '',
    gesture     TEXT DEFAULT '',
    source      TEXT DEFAULT 'inline',    -- inline | after_refine
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**chat_logs 表新增列：**

```sql
ALTER TABLE chat_logs ADD COLUMN engine_crashed INTEGER DEFAULT 0;
ALTER TABLE chat_logs ADD COLUMN node_failures TEXT DEFAULT '[]';
```

**索引：**

```sql
CREATE INDEX IF NOT EXISTS idx_compression_trace ON compression_logs(trace_id);
CREATE INDEX IF NOT EXISTS idx_toolaudit_trace ON tool_audit(trace_id);
CREATE INDEX IF NOT EXISTS idx_emotion_trace ON emotion_logs(trace_id);
CREATE INDEX IF NOT EXISTS idx_compression_created ON compression_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_toolaudit_created ON tool_audit(created_at);
```

**写入时机：**

- `compression_logs`：ContextManager.compress() 结束时写入（成功或失败）
- `tool_audit`：ReactNode 每个 tool 执行完后写入（含 HITL 状态）
- `emotion_logs`：每次 `emotion.update` 事件时写入
- `chat_logs.engine_crashed`：`_run_engine` 的 except 块中设置
- `chat_logs.node_failures`：PhaseEventLogger 记录所有 `status != "ok"` 的 node

---

## Testing Decisions

### Workstream A 测试

- 好的测试：独立创建 PhaseEventLogger，发射模拟事件序列，验证 DB 中写入的 duration_ms 正确
- 并行场景：同时发射 `node.start`(a/b/c)，验证三个 `node.done` 都有自己的 duration_ms，互不干扰
- 错误场景：发射 `node.done` 携带 error 信息，验证 status/error 字段正确
- 回退：无 PhaseEventLogger 时 Pipeline 不受影响

**测试文件：**
- `tests/test_logging_parallel.py` — 多计时器 + 并行节点时序验证
- `tests/test_logging_events.py` — 新增事件类型覆盖

### Workstream B 测试

- 好的测试：mock Agent 构造参数，验证 shutdown 调用了所有 close/shutdown 方法
- CLI 命令测试：创建 Agent + MemoryProvider，验证 `/log facts` 输出包含 trust_score
- `/log session`：创建 session_store 并写入 session，验证列表和详情输出

**测试文件：**
- `tests/test_cli_logging_integration.py` — CLI 日志命令的端到端验证

### Workstream C 测试

- 好的测试：直接操作 ChatLogDB 的新方法，验证表创建和 CRUD
- compression_logs：写入一条压缩记录，验证查询返回值正确
- tool_audit：写入多条工具调用，验证按 trace_id 筛选正确

**测试文件：**
- `tests/test_log_db_extended.py` — 新表的 CRUD 测试

---

## Out of Scope

- Grafana/Loki/ELK 等外部日志系统集成（留到之后的可观测性 PRD）
- 异步写日志到独立文件（如 Hermes 的 gateway.log 模式）
- token 级别的流式文本持久化（`text_token` 仍跳过）
- 日志加密相关
- Web Dashboard 查看日志
- 视觉化 emotion 趋势图

---

## Further Notes

- **向后兼容**：旧 `ChatLogDB` 表只增不删，`long_term_facts` 标记为 `@deprecated` 但不删除
- **性能预期**：批量 flush 后每条 chat 的 DB 写入从 15+ 次 commit 降为 1 次
- **配置化**：所有新表的 flush 间隔、日志轮转大小可在 `config.yaml` 配置
- **Workstream 依赖**：B 依赖 A 的 shutdown 扩展，C 依赖 A 的 handle_event 扩展。但 A 和 C 可以并行开发（A 先合并，C 基于 A 的接口）
