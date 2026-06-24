# Handoff: AniMate Phase 5 — CLI 完整接入 + 日志整改 + 信任分

## Project Overview

AniMate — 角色化 AI Agent 框架，基于 BSP 图引擎。Phase 5 完成了 CLI 命令接入、日志系统整改、信任分系统和多项杂项修复。

Repo: `git@github.com:Ackvl1/AniMate.git` (branch: dev)

## Completed Work

| 模块 | 文件 | 测试 |
|------|------|------|
| Agent compact/resume | `core/agent/agent.py` | 5 |
| Agent shutdown 资源清理 | `core/agent/agent.py` | 5 |
| Agent create_default 扩展 | `core/agent/agent.py` | — |
| PhaseEventLogger 多计时器 | `core/agent/logging.py` | 6 |
| MemoryStore 信任分 | `core/memory/store.py` | 9 |
| ContextManager snip + config | `core/context/manager.py` | 7 |
| ChatLogDB 3 新表 + 轮转 | `core/log/log_db.py` | 11 |
| config.yaml compress + log | `config.yaml` + `core/config.py` | 3 |
| CLI /compact /resume /log | `cli.py` | — |
| _extract_facts 迁移 | `core/agent/agent.py` | 2 |
| _auto_compact 预算均分 | `core/context/manager.py` | 2 |

**新增测试文件：**
- `test_agent_compact_resume.py` — 5 tests
- `test_agent_shutdown.py` — 5 tests
- `test_compact_prompt.py` — 2 tests
- `test_config_compress.py` — 3 tests
- `test_extract_facts_migration.py` — 2 tests
- `test_log_db_extended.py` — 9 tests
- `test_log_rotation.py` — 2 tests
- `test_logging_parallel.py` — 6 tests
- `test_memory_trust.py` — 9 tests
- `test_tool_args_snip.py` — 4 tests

**删除：**
- `core/memory/manager.py` — MemoryManager（死代码）

## Architecture Decisions

- **Agent.compact()** — 公开方法，返回 {status, message, compress_count}，CLI /compact 调用
- **Agent.resume(session_id)** — 公开方法，加载旧 session 的 messages 到 _messages
- **Agent.shutdown()** — 关闭所有 DB 连接（session_store, memory_provider, log_db）
- **Agent.create_default()** — 扩展接受 log_db, memory_provider, session_store 参数
- **CLI Agent 创建** — 改用 create_default + 传入所有子系统，退出时调用 shutdown
- **PhaseEventLogger 重构** — 多计时器（_timers dict）+ batch flush（_event_buffer）
- **信任分** — 默认 0.3，LLM 0.7，检索 boost capped at 0.2，冲突 max 合并
- **tool_call snip** — 2000 chars 阈值，tool_result 保持 500 chars
- **_auto_compact prompt** — 按 token 预算均分（8000 // count），替代硬截 200 字符
- **日志轮转** — ChatLogDB.__init__ 时检查大小/年龄，超限归档为 .bak
- **config.yaml** — compress + log 段，ContextManager 从配置读取默认值
- **_extract_facts** — 改 sync，统一走 MemoryStore（不再写 ChatLogDB.long_term_facts）
- **MemoryManager 删除** — RunServices.memory 类型改 Any

## Data Files

```
animate/data/memory/memory.db     ← 长期事实库（MemoryStore, FTS5）
animate/data/sessions/sessions.db ← session rotation 存储
animate/data/logs/chat_log.db     ← 日志（6 张表）
```

## Test Results

```
416 passed, 2 skipped, 1 warning (61s)
```

## Remaining Work

- [ ] Phase 6: 多角色支持
- [ ] Phase 7: TTS / Vision 集成
- [ ] 事实自动过期（LRU 淘汰）
- [ ] Embedding 相关性排序（事实量 >100 时）

## Security Reminders

- .env 不进 git
- 推 GitHub 前 grep 扫公司关键词
- 用 gh api Git Data API 推送（SSH 被 DPI 拦）
