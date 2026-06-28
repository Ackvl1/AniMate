> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 4
> 概要: 短期记忆 v2 — Session Rotation 集成

# PRD: 短期记忆重构 + 上下文管理 + Session Rotation

## Status: 基础模块完成，集成测试通过

### 已完成

- [x] TokenCounter — 增量 tiktoken 计数器
- [x] ContextManager — token 追踪 + 渐进压缩（Snip + AutoCompact）+ session rotation
- [x] SessionStore — session 生命周期管理（初始化、冻结、rotation、跨 session 搜索）
- [x] MemoryStore — SQLite + FTS5 事实存储 + 信任评分 + regex 快速提取
- [x] MemoryProvider ABC + DefaultMemoryProvider — 长期记忆插件接口
- [x] MemoryNode — 图引擎接入点，在 fan_out 前检索
- [x] MergeNode — 不 clear，只替换 system prompt
- [x] fact_store / fact_feedback / session_search 工具 schema
- [x] Agent 集成 — SessionStore + ContextManager + MemoryProvider 全部接入
- [x] 369 tests passing

### 未完成

- [ ] /compact CLI 命令
- [ ] /resume CLI 命令
- [ ] config.yaml 压缩参数加载
- [ ] tool_call arguments snip
- [ ] compress_count 重置修复
- [ ] ContextManager.reset() 重置 compress_count
- [ ] test_agent_integration.py 适配新 Agent 接口

### Architecture

```
Agent.__init__:
  self._messages = []
  self._session_store = SessionStore()
  self._session_id = uuid8()
  self._ctx_mgr = ContextManager(llm, session_store)
  self._memory_provider = DefaultMemoryProvider(MemoryStore())
  self._graph = build_graph(MemoryNode, SystemPrompt, RAG*, Merge, React, After, Reflect)

chat_stream:
  1. messages = list(self._messages)
  2. ctx_mgr.update_from_response(last_usage)
  3. if ctx_mgr.need_compress():
       new_sid = ctx_mgr.compress(messages, session_id=self._session_id)
       memory.on_session_switch(new_sid, old_sid)
       self._session_id = new_sid
  4. engine.run()
  5. self._messages.append(user + assistant)
  6. memory.sync_turn(user, assistant)  ← regex 提取
  7. session_store.save_messages(session_id, self._messages)

reset:
  memory.on_session_end(messages)  ← LLM 深度提取
  session_store.finalize(session_id)
  创建新 session
```
