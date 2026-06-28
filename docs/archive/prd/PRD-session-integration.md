> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 4/5
> 概要: Session Rotation 集成 + 工具注册 + CLI

# PRD: Session Rotation 集成 + 工具注册 + CLI + 轻量提取

## Problem Statement

短期记忆、上下文管理、session 存储的基础模块已就绪（TokenCounter、ContextManager、SessionStore、MemoryStore、MemoryProvider ABC、MemoryNode），但这些模块之间的连线没有接通。Agent.chat_stream() 还是旧流程，session rotation、工具注册、CLI 命令等核心功能未实现。

## Solution

完成以下集成和新功能：

### A. Agent 集成 Session Rotation

Agent.__init__ 新增：
- `self._session_store = SessionStore(db_path=...)`
- `self._session_id = uuid8()` + `session_store.init_session(self._session_id, [])`
- `self._ctx_mgr = ContextManager(llm=self._llm, session_store=self._session_store)`

Agent.chat_stream() 新流程：
1. `messages = list(self._messages)` (复制)
2. `ctx_mgr.update_from_response(last_usage)`
3. if need_compress → compress(messages) → session rotation → on_session_switch
4. engine.run()
5. self._messages.append(user+assistant)
6. `session_store.save_messages(session_id, self._messages)` (每轮持久化)
7. `memory.sync_turn(user, assistant)`
8. `ctx_mgr.update_from_response(usage)`

compress 方法变更：
- 接受 session_id + session_store 参数
- 压缩成功时：finalize 旧 session → init 新 session → return new_session_id
- 压缩失败时：不旋转，compress_count 不递增

### B. fact_store + session_search 工具

fact_store schema（通过 MemoryProvider.get_tool_schemas()）：
- action: add | search | list | update | remove
- content (add): str
- query (search): str
- fact_id (update/remove): int
- category: user_pref | project | general

session_search schema（Agent 注册）：
- query: str
- limit: int (default 5)

工具通过 ToolRegistry 注册，ReactNode 自动暴露给 LLM。

### C. 轻量 regex 提取替换 LLM 提取

MemoryStore 新增 `extract_quick_facts(message: str) -> list[int]`
- 使用正则模式匹配偏好、约定、记住指令
- 中文 + 英文模式
- Agent post-turn 调用（替换 _extract_facts）
- LLM 提取仅在 on_session_end 时触发

### D. CLI /compact + /resume

/compact: 调用 ctx_mgr.compress()，显示压缩次数
/resume <session_id>: 加载旧 session 的 messages 到 self._messages

### E. config.yaml 压缩参数

```yaml
compress:
  threshold: 0.70
  head_rounds: 5
  tail_rounds: 10
  compact_reserve: 30000
  max_failures: 3
```

### F. compress 失败时 compress_count 不递增

_auto_compact 返回 bool 表示是否成功，外层判断。

### G. tool_call arguments Snip

Snip 除了替换大 tool_result，还替换大 tool_call arguments。

### H. MemoryProvider.initialize() 接入

Agent.__init__ 调用 memory_provider.initialize(session_id, session_store)

## User Stories

1. 作为用户，压缩后旧对话可通过 /resume 恢复。
2. 作为用户，/compact 手动触发压缩。
3. 作为用户，LLM 可通过 fact_store 工具管理长期记忆。
4. 作为用户，LLM 可通过 session_search 工具回溯历史对话。
5. 作为开发者，Agent 每轮自动持久化 messages 到 SessionStore。
6. 作为开发者，compress 成功才旋转 session。
7. 作为开发者，每轮 post-turn 用 regex 快速提取事实。
8. 作为开发者，所有压缩参数从 config.yaml 加载。

## Testing Decisions

- Session rotation 测试：验证压缩后 session_id 变化、旧 session 被冻结、新 session 有压缩后消息
- fact_store 测试：验证 add/search/list/update/remove 全流程
- session_search 测试：验证跨 session 搜索
- extract_quick_facts 测试：验证中英文 regex 匹配
- /compact 测试：验证调用 compress + session rotation
- /resume 测试：验证加载旧 session 消息
- config.yaml 加载测试：验证参数覆盖

## Out of Scope

- 异步压缩（并发写问题）
- 多实例 session 并发锁
- 压缩提示的 roleplay 定制
- 用户自定义压缩 prompt

## Further Notes

- 所有新测试使用 SessionStore/MemoryStore 的 :memory: SQLite
- fact_store 和 session_search 的 schema 一旦定下就不能轻易改（LLM 学习）
- compress 的 LLM 摘要调用使用主模型，不引入辅助模型
