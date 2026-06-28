> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 4
> 概要: 日志 + 长期记忆

# PRD: Phase-4 — 可观测日志 + 跨会话长期记忆

## Problem Statement

当前 Anima Agent 的调试和记忆能力有两个空白：

1. **日志系统存在但空转** — `ChatLogDB`（SQLite 聊天日志表）已实现并测试通过，但 Agent 没有一行代码调用它。每次对话的执行过程（RAG 检索了什么、LLM 几轮调用、哪个工具执行了多久、Reflect 给了几分）没有任何可追溯的记录。
2. **长期记忆为零** — `MemoryManager` 只维护一个内存滑动窗口（20 轮会话内上下文），重启进程或 `reset()` 就全部丢失。无法跨会话记住用户偏好、约定事项、已提及的实体关系，导致每轮对话都是"初次见面"状态。

## Solution

### Phase Events Logging
将 `ChatLogDB` 系统连接到 Agent 的事件流（AgentEvent），通过 `EventBus` subscriber 模式实现无侵入式日志。扩展表结构增加 `phase_events` 表记录每个 Node 的执行详情，使开发者能按 `trace_id` 回溯一次 chat 中每个阶段的完整输入/输出/耗时/异常。

### Long-term Memory
在每次 chat 结束时，由 ReflectNode（或独立的 MemoryNode）调用 LLM 从 `ctx.messages` 提取关键事实（用户偏好、约定事项、实体关系）→ 写入 SQLite `long_term_facts` 表 → 下次对话时由 BeforeNode 检索注入 system prompt。

## User Stories

### Logging
1. 作为开发者，我希望每次 chat 结束后自动写入一条 `chat_logs` 记录（trace_id / user_input / response_text / emotion / llm_call_count / tool_calls 摘要 / duration_ms），以便追踪对话历史。
2. 作为开发者，我希望每个 Node 执行结束后自动写入一条 `phase_events` 记录（trace_id / phase_name / input_summary / output_summary / duration_ms / status / error），以便定位问题节点。
3. 作为开发者，我希望工具调用（tool.start / tool.done）也被记录到 `phase_events`，以便追踪 LLM 工具的调用链和耗时。
4. 作为开发者，我希望 ReactNode 的每一轮 ReAct 循环都有独立的 phase_event 记录（react_round_1 / react_round_2 / …），以便观察多轮工具调用的执行顺序。
5. 作为开发者，我希望能通过 CLI 命令 `/log` 查看最近 N 条 chat 日志（含 trace_id 和摘要），以便无需查 DB 就能了解运行状态。
6. 作为开发者，我希望每次 Reflect 评估的结果（level / feedback / score）也被记录到 phase_events，以便分析输出质量变化趋势。

### Long-term Memory
7. 作为角色扮演用户，我希望 Agent 能在第二轮对话时记得我在第一轮提到的喜好（如"我喜欢猫"），以便体验连续的角色互动感。
8. 作为角色扮演用户，我希望 Agent 能跨会话记住我和角色之间的约定（如"下次告诉我天气"），以便不需要重复提示。
9. 作为开发者，我希望长期记忆的提取和注入对用户无感（不需要手动触发），以便不影响交互流畅度。
10. 作为开发者，我希望长期记忆的 SQLite 表可以手工查询和编辑，以便调试或手动修正错误记忆。
11. 作为开发者，我希望长期记忆的注入量可配置（max_facts），以便在 token 预算和上下文质量之间取得平衡。

## Implementation Decisions

### Phase Events Logging

**架构模式**: Event-driven subscriber — 不修改任何 Node 代码，通过 `EventBus.subscribe` 将事件路由到 `PhaseEventLogger`。

| 决策 | 选择 | 理由 |
|------|------|------|
| 事件源 | `AgentEvent` 流 + `Agent._emit` 拦截 | 已经在 Node 级别 emit，无需额外侵入 |
| 存储 | `ChatLogDB` 扩展 → `chat_logs` 表 + 新增 `phase_events` 表 | 同 DB 文件，同 `sqlite3`，事务一致 |
| 时机 | `chat_stream()` 内每次 emit 时写 `phase_events`，结束时写 `chat_logs` | 不依赖多线程异步写入，同步 SQLite 写入 |
| 关联 | `trace_id` 作为关联键 | 已存在于 `RunContext` |
| CLI 查看 | `/log` 命令 → `ChatLogDB.query()` | 复用已有查询接口 |

**表结构变更**:

```
chat_logs (现有)
  + 无变更，字段已覆盖

phase_events (新增)
  id            INTEGER PRIMARY KEY
  trace_id      TEXT NOT NULL        # 关联到 chat_logs
  phase_name    TEXT NOT NULL        # before / react / after / reflect / tool:xxx / react_round_2
  input_summary TEXT DEFAULT ''      # 阶段输入的文本摘要（前 200 字符）
  output_summary TEXT DEFAULT ''     # 阶段输出的文本摘要
  duration_ms   INTEGER DEFAULT 0    # 执行耗时
  status        TEXT DEFAULT 'ok'    # ok / error / skipped
  error         TEXT DEFAULT ''      # 异常堆栈（如有）
  extra         TEXT DEFAULT '{}'    # JSON 扩展字段（例如 Reflect 的 level/feedback）
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

**实现位置**:
- `animate/data/logs/log_db.py` — `ChatLogDB` 增加 `log_phase()` 方法
- `animate/core/agent/agent.py` — `chat_stream()` 内部创建 `PhaseEventLogger`，绑定 emit 事件

**PhaseEventLogger 类**（新增模块 `animate/core/agent/logger_agent.py` 或内联在 agent.py）：
- `__init__(self, log_db: ChatLogDB)` — 接受 ChatLogDB 实例
- `on_phase_start(name: str) → None` — 记录开始时间 + input_summary
- `on_phase_end(name: str, output_summary: str, status: str, error: str = "", extra: dict = None) → None` — 计算 duration，写 phase_events
- `log_chat_summary(ctx: RunContext, trace_id: str, duration_ms: int) → None` — 写 chat_logs

### Long-term Memory

**架构模式**: Post-chat fact extraction via LLM → SQLite → pre-chat retrieval → context injection.

| 决策 | 选择 | 理由 |
|------|------|------|
| 提取时机 | 每次 chat 完成后（`chat_stream` yield done 之前） | 此时 `ctx.messages` 包含完整对话，无需额外 LLM 调用循环 |
| 提取方式 | LLM 调用 `ReflectNode` 风格的 prompt：从对话中抽取事实列表 | 复用已有的 LLM 引用（`self._llm`）和流式/非流式接口 |
| 存储 | SQLite 表 `long_term_facts` | 跟日志同文件，方便管理；无需向量库 |
| 检索 | BeforeNode 在构造 system prompt 时查询所有 facts → 注入 `## 角色记忆` 节 | 复用现有的 prompt 组装逻辑 |
| 去重 | 事实以文本 hash 为唯一键（`fact_hash TEXT UNIQUE`） | 避免同一事实反复插入 |
| 注入上限 | `MAX_FACTS = 10` | 防止 system prompt 膨胀 |
| 重置 | `agent.reset()` 可选参数 `clear_facts=False` | reset 对话记忆不应清除长期记忆 |

**表结构**:
```
long_term_facts
  id            INTEGER PRIMARY KEY
  fact_hash     TEXT UNIQUE NOT NULL   # hashlib.sha256(fact_text.encode()).hexdigest()[:16]
  fact_text     TEXT NOT NULL          # 事实原文（如"用户喜欢猫"）
  source_trace  TEXT NOT NULL          # 来源 chat 的 trace_id
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

**提取 prompt 示例**:
```
从以下对话中提取值得长期记住的事实。
要求：
- 只提取与用户相关的信息（偏好、习惯、约定、关系）
- 不提取通用知识或角色自身的设定
- 每条事实用一句话描述
- 以 JSON 数组格式输出：[{"fact": "..."}, {"fact": "..."}]
- 如果没有新事实值得记录，返回 []

对话：
{formatted_messages}
```

**注入位置**: BeforeNode 的 `_build_system_prompt()` 方法，在 persona 和 RAG 之后追加。

### Implementation Order

1. `ChatLogDB` 追加 `log_phase()` 和 `long_term_facts` 表
2. `PhaseEventLogger` 类 — 订阅 AgentEvent，写 phase_events
3. Agent 集成 — `chat_stream()` 内串联 PhaseEventLogger
4. CLI `/log` 命令 — 查看最近日志
5. 事实提取 — `MemoryNode` 或扩展 `ReflectNode`，chat 结束后调用 LLM 提取事实
6. 事实注入 — `BeforeNode._build_system_prompt()` 读取 long_term_facts 并注入

## Testing Decisions

### 原则
- 只测行为，不测实现。测试验证"记录是否写入 DB"、"事实是否被注入 prompt"，而不是"PhaseEventLogger 调用了哪个方法"
- **TDD**: 每个 test 先 RED（目睹失败），再 GREEN（最小代码通过）
- 对依赖 ChatLogDB 的测试使用 `:memory:` SQLite（已建好 fixture）

### 模块和测试

**tests/test_log_db.py** — 追加测试：
- `test_log_phase_inserts_record` — `log_phase()` 写入后 query 匹配
- `test_log_phase_with_trace_link` — phase_events 通过 trace_id 关联到 chat_logs
- `test_log_phase_extra_json` — extra 字段存 JSON 字符串
- `test_long_term_facts_insert_unique` — 重复事实不会插入（UNIQUE 约束）
- `test_long_term_facts_query_by_text` — 支持按事实文本模糊查询

**tests/test_agent_logging.py**（新增）：
- `test_chat_logs_auto_written` — chat() 后 chat_logs 表有记录
- `test_phase_events_record_before_node` — phase_events 包含 "before" 条目

**tests/test_long_term_memory.py**（新增）：
- `test_facts_extracted_after_chat` — chat() 后 long_term_facts 表有记录
- `test_facts_injected_to_prompt` — 下一轮 chat 的 system prompt 包含事实文本
- `test_duplicate_facts_deduplicated` — 相同事实重复 chat 不会重复插入
- `test_reset_keeps_long_term_facts` — agent.reset() 后事实仍在
- `test_reset_clears_long_term_facts` — agent.reset(clear_facts=True) 后事实清空

## Out of Scope

- 向量化事实检索（使用 VectorStore 做语义匹配）— 初期用 SQLite LIKE 查询足够，5-10 条事实做全量遍历无性能压力
- 事实自动过期（遗忘曲线）— 以后可以通过 `updated_at` 做 LRU 淘汰
- 多角色事实隔离 — 当前只服务 Saki 一个角色，多个角色数据分开存即可
- 记忆的编辑/删除 CLI 命令 — 可以通过 SQLite 命令行手工操作，不紧急
- 非 LLM 提取方式（关键词/模式匹配）— LLM 提取的准确度远高于规则，每次提取代价 ~0.5s 可接受
- 对话摘要压缩（autoCompact）— 那是 session 内的 token 管理，跟跨会话记忆是两回事
- 实时（逐 token）日志 — 当前在 Node 完成时写入即可，不需要高频率

## Further Notes

- `PhaseEventLogger` 的输出可以通过 `/log verbose` 命令展示到 CLI，方便调试
- 事实提取依赖 LLM 的 JSON 输出能力，当前 ReflectNode 已经验证 DeepSeek 可以稳定输出 JSON，复用同一套 `json.loads` 解析逻辑
- 这两项功能的 SQLite 存储共用 `log_db.py` 的数据库连接，不需要额外文件
- 未来考虑：当事实表超过 100 条时引入基于 embedding 的相关性排序，目前全量注入 Top-10
