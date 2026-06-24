> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 5
> 概要: CLI 完整接入 + 日志整改 + 信任分 + 杂项修复

# PRD: AniMate Phase 5 — CLI 完整接入 + 日志整改 + 信任分 + 杂项修复

## Problem Statement

AniMate 经历 Phase 2-4 后，核心管线（BSP 图引擎 + 流式输出 + 短期记忆 + 长期记忆）已就绪（371 tests），但有 4 类遗留问题阻碍实际使用：

1. **CLI 缺关键命令** — `/compact`（手动压缩）、`/resume`（恢复旧 session）未实现；`config.yaml` 压缩参数未暴露；CLI 启动时不初始化 MemoryProvider / SessionStore，长期记忆和 session rotation 零作用
2. **日志系统缺陷** — BSP 并行节点耗时数据错误（单计时器）；tool_call arguments/results 未入库；节点异常时 status 仍写 "ok"；SQLite 同步写阻塞事件循环；无日志轮转；两套事实库并行（ChatLogDB.long_term_facts vs MemoryStore.facts）
3. **信任分无来源区分** — regex 误提取和 LLM 主动存储的事实都是 0.5，无晋升通路
4. **工具参数截断缺失** — L1 Snip 只截 tool_result（500 chars），不截超大 tool_call arguments；`_auto_compact` 摘要 prompt 每条消息截断 200 字符可能丢关键上下文

## Solution

分 4 个 Workstream 并行推进，每个 WS 独立可测试、独立可部署：

### Workstream A — CLI 命令 + 配置 + 模块接入

- 新增 `/compact` 命令：调用 `Agent.compact()` 公开方法
- 新增 `/resume` 命令：不传参→交互选择 session；传 `<id>`→直接恢复
- `config.yaml` 新增 `compress` 段，暴露压缩参数
- CLI 启动时创建 MemoryProvider / SessionStore / LogDB 并传入 Agent
- `Agent.shutdown()` 关闭所有 DB 连接

### Workstream B — 日志系统整改

- PhaseEventLogger 重构：多计时器 + 延迟写入 + 批量 flush
- 事件覆盖扩展：`tool.denied`、`emotion.update`、`compression.*`、`session.*`
- tool_call arguments/results 完整入库（tool_audit 表）
- 节点异常时 status/error 正确写入
- ReactNode duration_ms 截断修复
- 新增表：compression_logs、tool_audit、emotion_logs
- chat_logs 新增 engine_crashed、node_failures 字段
- 废弃 ChatLogDB.long_term_facts，统一到 MemoryStore
- 日志轮转：按大小 + 按时间

### Workstream C — 信任分系统

- 按来源设初始信任分：regex → 0.3，LLM fact_store → 0.7
- 检索晋升：search_facts 命中后 retrieval_count++，ORDER BY 加 boost（系数 0.002，cap 0.2）
- 冲突合并：相同内容写入时 trust_score = max(已有, 新传入)

### Workstream D — 杂项修复

- tool_call arguments snip：阈值 2,000 chars，截断后替换为 `[参数过长，已省略]`
- `_auto_compact` 摘要 prompt：按 token 预算均分，不再硬截 200 字符
- `_extract_facts` 迁移：agent.py 旧事实提取逻辑统一到 MemoryStore

---

## User Stories

### Workstream A — CLI 命令 + 配置

1. 作为用户，我希望敲 `/compact` 手动触发压缩，终端显示压缩结果（成功/跳过/失败）
2. 作为用户，我希望 `/resume` 不传参时列出所有 session（ID、状态、消息数、创建时间），我选择编号恢复
3. 作为用户，我希望 `/resume <id>` 直接恢复指定 session 的对话到当前会话
4. 作为用户，我希望恢复旧 session 后下一轮对话自动带历史上下文
5. 作为开发者，我希望压缩参数（threshold、head_rounds、tail_rounds 等）从 config.yaml 读取，不改代码
6. 作为 CLI 用户，我希望启动时 Agent 自动加载长期记忆和 session 管理
7. 作为开发者，我希望 `Agent.shutdown()` 关闭所有 DB 连接（log_db、session_store、memory_provider）

### Workstream B — 日志整改

8. 作为开发者，我希望 RAGVector / RAGKeyword / SystemPrompt 并行执行时各自的 duration_ms 互不干扰
9. 作为开发者，我希望每次工具调用的 arguments 和 results 完整记录到 tool_audit 表
10. 作为开发者，我希望 `/log tool` 能查看最近工具调用记录（名称、耗时、HITL 状态）
11. 作为开发者，我希望节点抛异常时 phase_events 的 status 写 "error"，error 字段记录异常摘要
12. 作为开发者，我希望图引擎崩溃时 chat_logs 记录 engine_crashed 标记
13. 作为开发者，我希望 ReactNode 的 duration_ms 反映全部耗时（含工具执行），不被 tool.start 截断
14. 作为开发者，我希望日志写入使用批量 flush，不在 async 热路径上同步 commit
15. 作为开发者，我希望 `/log facts` 显示 MemoryStore 中的事实（含 trust_score），不再查旧表
16. 作为开发者，我希望 `/log session` 列出所有 session，`/log session <id>` 查看详情
17. 作为开发者，我希望 `/log compression` 查看压缩记录
18. 作为开发者，我希望日志 DB 有轮转策略（按大小/时间），不会无限增长
19. 作为开发者，我希望 tool_audit 存完整 arguments（不受 snip 影响），用于调试

### Workstream C — 信任分

20. 作为系统，regex 低置信提取的事实初始信任分应为 0.3
21. 作为系统，LLM 通过 fact_store 工具主动存储的事实初始信任分应为 0.7
22. 作为系统，相同内容重复写入时信任分取 max(已有, 新传入)，不降级
23. 作为系统，频繁被检索命中的事实排序权重应自然提升（有上限）
24. 作为开发者，我希望 boost 系数和 cap 可配置

### Workstream D — 杂项修复

25. 作为开发者，我希望超大 tool_call arguments（>2,000 chars）被 snip，不撑爆 context
26. 作为开发者，我希望 `_auto_compact` 摘要 prompt 按 token 预算分配，不硬截 200 字符
27. 作为开发者，我希望 agent.py 的 `_extract_facts` 统一走 MemoryStore，不再写旧表

---

## Implementation Decisions

### Workstream A — CLI 命令 + 配置

**Agent.compact() 公开方法**

```python
# agent.py 新增
def compact(self) -> dict:
    """手动触发压缩。返回 {status, message, compress_count}"""
    if not self._ctx_mgr.need_compress():
        return {"status": "skip", "message": "未达压缩阈值", "compress_count": self._ctx_mgr._compress_count}
    new_sid = self._ctx_mgr.compress(self._messages, session_id=self._session_id)
    if new_sid:
        if self._memory_provider:
            self._memory_provider.on_session_switch(new_sid, self._session_id)
        self._session_id = new_sid
        return {"status": "ok", "message": f"压缩完成 (#{self._ctx_mgr._compress_count})", "session_id": new_sid}
    return {"status": "error", "message": "压缩失败（LLM 摘要异常）", "compress_count": self._ctx_mgr._compress_count}
```

**Agent.resume() 公开方法**

```python
# agent.py 新增
def resume(self, session_id: str) -> bool:
    """恢复旧 session 的消息到当前会话。返回是否成功。"""
    if not self._session_store:
        return False
    messages = self._session_store.load(session_id)
    if not messages:
        return False
    self._messages = messages
    return True
```

**config.yaml 新增 compress 段**

```yaml
compress:
  threshold: 0.70
  head_rounds: 5
  tail_rounds: 10
  compact_reserve: 30000
  max_failures: 3
```

ContextManager 构造时从 config 读取，保留当前默认值作为 fallback。

**CLI /compact 命令**

```python
if cmd == "/compact":
    result = agent.compact()
    if result["status"] == "ok":
        print(f"🗜️ {result['message']}")
    elif result["status"] == "skip":
        print(f"⏭ {result['message']}")
    else:
        print(f"⚠ {result['message']}")
    return True
```

**CLI /resume 命令**

```python
if cmd == "/resume":
    if len(parts) > 1:
        # 直接恢复
        sid = parts[1]
        ok = agent.resume(sid)
        print(f"✅ 已恢复 session {sid}" if ok else f"⚠ 未找到 session {sid}")
    else:
        # 交互选择
        sessions = agent._session_store.list_sessions()
        if not sessions:
            print("📭 无可用 session")
            return True
        # 显示列表 + 选择
        ...
    return True
```

**CLI 模块接入**

cli.py main() 创建 Agent 时传入 log_db、memory_provider、session_store：

```python
from animate.core.session.store import SessionStore
from animate.core.memory.default_provider import DefaultMemoryProvider
from animate.core.memory.store import MemoryStore

session_store = SessionStore(db_dir / "sessions.db")
memory_store = MemoryStore(db_dir / "memory.db")
memory_provider = DefaultMemoryProvider(memory_store)
log_db = ChatLogDB()

agent = Agent(llm=llm, persona=persona, ...,
    log_db=log_db, memory_provider=memory_provider, session_store=session_store)
```

**Agent.shutdown() 扩展**

```python
def shutdown(self):
    for client in self._mcp_clients:
        try: client.stop()
        except: pass
    if self._session_store:
        try: self._session_store.close()
        except: pass
    if self._memory_provider:
        try: self._memory_provider.shutdown()
        except: pass
    if self._phase_logger:
        try: self._phase_logger._db.close()
        except: pass
```

### Workstream B — 日志整改

**PhaseEventLogger 重构：多计时器**

```python
class PhaseEventLogger:
    def __init__(self, db):
        self._db = db
        self._timers: dict[str, float] = {}     # 多个并存
        self._event_buffer: list[dict] = []      # 延迟写入

    def _start_node(self, name: str):
        self._timers[name] = time.monotonic()

    def _end_node(self, name: str, ...):
        start = self._timers.pop(name, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        self._event_buffer.append({...})

    def _flush(self):
        """批量写入 + 单次 commit"""
        for entry in self._event_buffer:
            self._db.log_phase(**entry)
        self._event_buffer.clear()
```

**handle_event 扩展**

| 事件类型 | 动作 |
|----------|------|
| `node.start` | `_start_node(name)` — 不再结束上一个 |
| `node.done` | `_end_node(name, ...)` — 只结束指定节点 |
| `tool.start` | `_start_node(f"tool:{name}")` + 记录 arguments |
| `tool.done` | `_end_node(f"tool:{name}", ...)` + 记录 results |
| `tool.denied` | 写入 tool_audit (hitl_status="denied") |
| `emotion.update` | 写入 emotion缓冲区 |
| `reflect.result` | `_end_node("reflect", ...)` — 已有，保持 |

**ReactNode duration_ms 修复**

多计时器下，`tool.start` 只创建新计时器，不结束 react 计时器。react 的 `node.done` 在所有 tool 执行完后才到达，duration_ms 自然包含工具执行时间。

**tool_audit 表**

```sql
CREATE TABLE IF NOT EXISTS tool_audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id      TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    input_args    TEXT DEFAULT '{}',      -- 完整 arguments（不受 snip 影响）
    output_summary TEXT DEFAULT '',
    output_length INTEGER DEFAULT 0,
    duration_ms   INTEGER DEFAULT 0,
    hitl_status   TEXT DEFAULT 'auto',    -- approved | denied | auto
    status        TEXT DEFAULT 'success', -- success | error
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**compression_logs 表**

```sql
CREATE TABLE IF NOT EXISTS compression_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT NOT NULL,
    compress_count  INTEGER DEFAULT 0,
    success         INTEGER DEFAULT 1,
    before_tokens   INTEGER DEFAULT 0,
    after_tokens    INTEGER DEFAULT 0,
    head_rounds     INTEGER DEFAULT 0,
    middle_msgs     INTEGER DEFAULT 0,
    tail_rounds     INTEGER DEFAULT 0,
    old_session_id  TEXT DEFAULT '',
    new_session_id  TEXT DEFAULT '',
    error_msg       TEXT DEFAULT '',
    duration_ms     INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**emotion_logs 表**

```sql
CREATE TABLE IF NOT EXISTS emotion_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    sequence    INTEGER DEFAULT 0,
    emotion     TEXT DEFAULT '',
    gesture     TEXT DEFAULT '',
    source      TEXT DEFAULT 'inline',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**chat_logs 新增列**

```sql
ALTER TABLE chat_logs ADD COLUMN engine_crashed INTEGER DEFAULT 0;
ALTER TABLE chat_logs ADD COLUMN node_failures TEXT DEFAULT '[]';
```

**事实库统一**

废弃 `ChatLogDB.long_term_facts` 表及相关方法（`add_fact`、`query_facts`、`count_facts`、`clear_facts`、`delete_fact`、`query_facts_by_text`），标记 `@deprecated`。

- `agent.py:_extract_facts()` → 改为调 `MemoryStore.add_fact()`
- `agent.py:chat_stream` fallback → 改为调 `MemoryStore.list_facts()`
- `cli.py:/log facts` → 改为查 `MemoryStore`

**日志轮转**

```yaml
log:
  max_db_size_mb: 50
  max_age_days: 30
```

ChatLogDB 初始化时检查 DB 文件大小和最早记录时间，超出时归档（重命名）或清理。

**批量 flush 策略**

- `_end_node` 只 append 到 buffer，不 commit
- `on_chat_end` 时调 `_flush()`，合并所有缓冲写入 + 单次 commit
- 中间 flush：buffer 超过 20 条时自动 flush（防内存泄漏）

### Workstream C — 信任分

**MemoryStore 变更**

`add_fact()` 签名增加 `trust_score: float | None = None`：
- 传入时使用传入值
- 不传入时使用 `self._default_trust`（改为 0.3）
- IntegrityError 分支：`UPDATE facts SET trust_score = MAX(trust_score, ?) WHERE content = ?`

`search_facts()` ORDER BY 增加检索 boost：

```sql
SELECT f.*, (f.trust_score + MIN(f.retrieval_count * 0.002, 0.2)) AS effective_score
FROM facts f
JOIN facts_fts ft ON ft.rowid = f.fact_id
WHERE facts_fts MATCH ?
ORDER BY effective_score DESC
LIMIT ?
```

命中后 `retrieval_count++`：

```python
self._conn.execute(
    "UPDATE facts SET retrieval_count = retrieval_count + 1 WHERE fact_id = ?",
    (row["fact_id"],),
)
```

**DefaultMemoryProvider 变更**

`_handle_fact_store()` 中 `action == "add"` 时显式传入 `trust_score=0.7`。

### Workstream D — 杂项修复

**tool_call arguments snip**

在 `ContextManager._snip_tool_results()` 中增加对 assistant 消息 tool_call arguments 的截断：

```python
SNIP_THRESHOLD = 2000  # 比 tool_result 的 500 高，因为 arguments 通常更长

for i in indices:
    m = messages[i]
    if m.get("role") == "assistant" and m.get("tool_calls"):
        for tc in m["tool_calls"]:
            args_str = tc.get("function", {}).get("arguments", "")
            if len(args_str) > SNIP_THRESHOLD:
                tc["function"]["arguments"] = args_str[:SNIP_THRESHOLD] + "[参数过长，已省略]"
    elif m.get("role") == "tool" and len(str(m.get("content", ""))) > 500:
        m["content"] = "[工具结果较长，已压缩]"
```

**_auto_compact 摘要 prompt 优化**

替换硬截 200 字符为按 token 预算均分：

```python
# 旧：content = str(m.get("content", ""))[:200]
# 新：按消息数均分预算
total_budget = 8000  # 约 2K tokens 的摘要输入预算
per_msg = total_budget // max(len(middle_msgs), 1)
for m in middle_msgs:
    content = str(m.get("content", ""))[:per_msg]
    prompt += f"\n{m.get('role', 'unknown')}: {content}"
```

**_extract_facts 迁移**

```python
# agent.py _extract_facts() 改为：
if self._memory_provider:
    for item in facts_list:
        fact_text = item.get("fact", "")
        if fact_text and len(fact_text) > 3:
            self._memory_provider.handle_tool_call("fact_store", {
                "action": "add", "content": fact_text,
            })
```

---

## Testing Decisions

### Workstream A 测试

| 测试文件 | 内容 |
|---------|------|
| `tests/test_agent_compact.py` | Agent.compact()：阈值未达→skip、压缩成功→返回 session_id、压缩失败→error |
| `tests/test_agent_resume.py` | Agent.resume()：有效 session→messages 恢复、无效 session→False、无 session_store→False |
| `tests/test_cli_compact_resume.py` | CLI /compact 输出、/resume 列表显示、/resume <id> 直接恢复 |
| `tests/test_config_compress.py` | config.yaml 压缩参数加载、默认值 fallback |
| `tests/test_agent_shutdown.py` | shutdown 调用所有 close/shutdown 方法 |

### Workstream B 测试

| 测试文件 | 内容 |
|---------|------|
| `tests/test_logging_parallel.py` | 多计时器并行节点 duration_ms 互不干扰 |
| `tests/test_logging_tool_audit.py` | tool_audit 写入/查询、完整 arguments 记录、HITL 状态 |
| `tests/test_logging_events.py` | emotion.update、tool.denied、compression.* 事件覆盖 |
| `tests/test_logging_error.py` | 节点异常 status="error"、engine_crashed 标记 |
| `tests/test_logging_flush.py` | 批量 flush、buffer 满自动 flush |
| `tests/test_log_db_extended.py` | compression_logs、tool_audit、emotion_logs CRUD |
| `tests/test_log_rotation.py` | DB 轮转：大小限制、时间限制、归档 |
| `tests/test_fact_unification.py` | MemoryStore 替代 ChatLogDB.long_term_facts |

### Workstream C 测试

| 测试文件 | 内容 |
|---------|------|
| `tests/test_memory_trust.py` | 默认分 0.3、自定义分 0.7、冲突 max 合并、检索 boost、cap 验证 |

### Workstream D 测试

| 测试文件 | 内容 |
|---------|------|
| `tests/test_tool_args_snip.py` | arguments > 2K→截断、< 2K→不截、tool_result > 500→截断 |
| `tests/test_compact_prompt.py` | 摘要 prompt 按预算均分、空 middle→跳过 |
| `tests/test_extract_facts_migration.py` | _extract_facts 写入 MemoryStore 而非 ChatLogDB |

### 预期新增测试数

约 40-50 个新测试。

---

## Out of Scope

- Grafana/Loki/ELK 等外部日志系统集成
- 异步写日志到独立文件
- token 级别流式文本持久化（text_token 仍跳过）
- 日志加密
- Web Dashboard
- emotion 趋势可视化
- 向量化事实检索（embedding 相关性排序）
- 多角色事实隔离
- 记忆的编辑/删除 CLI 命令（通过 SQLite 手工操作）

---

## Further Notes

- **向后兼容**：旧 ChatLogDB 表只增不删，long_term_facts 标记 @deprecated
- **性能预期**：批量 flush 后每条 chat 的 DB 写入从 15+ 次 commit 降为 1 次
- **配置化**：compress 段 + log 段所有参数从 config.yaml 读取
- **WS 依赖**：A 无依赖可先行；B 依赖 A 的 shutdown 扩展；C 无依赖可与 A 并行；D 依赖 B 的事实库统一
- **tool_audit 存完整 arguments**：不受 snip 影响，用于调试
- **retrieval_count++**：只在 prefetch 路径触发，list_facts 不触发
- **session_id 碰撞**：8 位 hex（4.3×10⁹ 种），不改
- **MemoryNode 时间衰减**：当前不做，通过 search 次数自然晋升替代
