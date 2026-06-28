# PRD: 记忆系统增强 — 提取时机 + 覆盖度 + 衰减

## Problem Statement

1. sync_turn 仅 5 个 regex pattern，大部分对话事实漏提取
2. on_session_end 仅在 reset 触发，压缩、退出时不提取
3. 信任分无衰减，过时事实不会降权

## Solution

1. sync_turn 扩展到 15 pattern
2. 压缩时 on_session_end 提取（用压缩前完整消息）
3. 退出时 on_session_end 提取
4. 查询时信任分时间衰减（age_days * 0.01）

## User Stories

1. 作为用户，我希望压缩对话历史时，系统自动提取其中的长期记忆事实
2. 作为用户，我希望退出应用程序时，系统不会丢失当前会话的长期记忆
3. 作为用户，我希望更多的自然语言表达能被 regex 快速提取（如"我住在XX"、"我工作于XX"）
4. 作为系统，我希望长期未被检索的事实逐渐降低权重

## Implementation Decisions

### 1. sync_turn 15 patterns

保留现有 5 个，新增 10 个：

| # | 类型 | 正则 | 示例 |
|---|------|------|------|
| 1 | 偏好 | `我(们)?(喜欢\|偏好\|需要\|想(要\|用))(.+)` | 我喜欢猫 |
| 2 | 偏好(中英) | `我(们)?的?(favorite\|首选\|默认)\s*(是)?(.+)` | 我默认用Python |
| 3 | 偏好(英) | `I\s+(prefer\|like\|love\|use\|want\|need)\s+(.+)` | I prefer Python |
| 4 | 偏好(英) | `my\s+(favorite\|preferred\|default)\s+\w+\s+is\s+(.+)` | my favorite is Python |
| 5 | 命令 | `记住(.+)` | 记住我喜欢猫 |
| 6 | 住址 | `我住在(.+)` | 我住在北京 |
| 7 | 工作 | `我在(.+)(工作\|上班\|公司)` | 我在阿里工作 |
| 8 | 职业 | `我是(.+)(工程师\|设计师\|程序员\|医生\|老师\|学生)` | 我是前端工程师 |
| 9 | 拥有 | `我有(\w+)(只\|个\|台\|辆)(.+)` | 我有一只猫 |
| 10 | 计划 | `我(打算\|计划\|准备\|想要)(.+)` | 我打算学钢琴 |
| 11 | 习惯 | `我(每天\|经常\|偶尔)(.+)` | 我每天跑步 |
| 12 | 关系 | `我(妈妈\|爸爸\|朋友\|同事\|老板)(.+)` | 我朋友在北京 |
| 13 | 负偏好 | `我(不(?:太\|怎么)?(?:喜欢\|想\|要))(.+)` | 我不喜欢香菜 |
| 14 | 位置 | `我(在\|去)([^，。,\.]{2,15})` | 我在上海 |
| 15 | 状态 | `我(最近\|刚刚\|已经)(.+)` | 我最近很忙 |

### 2. 压缩时提取

```python
# chat_stream 中，compress_async 之前
if self._ctx_mgr.need_compress() and self._memory_provider:
    # 用压缩前完整消息做深度提取
    self._memory_provider.on_session_end(self._messages, llm=self._llm)
```

### 3. 退出时提取

```python
def shutdown(self):
    # 退出时提取长期记忆
    if self._memory_provider and self._messages:
        self._memory_provider.on_session_end(self._messages, llm=self._llm)
    # ... 关闭连接
```

### 4. 信任分衰减

在 search_facts 查询中加入年龄衰减：

```sql
effective_score = trust_score - (julianday('now') - julianday(created_at)) * 0.01
                    + MIN(retrieval_count * 0.02, 0.2)
```

有效分不低于 0.05，防止负分。

## Testing Decisions

| 测试 | 类型 | 说明 |
|------|------|------|
| sync_turn 15 pattern 覆盖 | 单元 | 每种 pattern 的匹配/不匹配测试 |
| 压缩时 on_session_end 触发 | 集成 | mock LLM，验证压缩前调用 |
| 退出时 on_session_end 触发 | 集成 | 验证 shutdown 里调用 |
| 信任分衰减 | 单元 | 插入旧事实 → 查询 → 验证 effective_score 下降 |
| 全量回归 | 全量 | 499 passed → 500+ passed |

## Out of Scope

- 每轮 LLM 提取（已确认不需要）
- resume 触发提取（resume 是继续而非结束）
- 衰减永久写入（只查询时计算，不修改存储值）

## Implementation Order

1. sync_turn 15 pattern（最简单，独立）
2. 信任分衰减（纯 SQL，独立）
3. 压缩时 on_session_end（依赖 agent.py）
4. 退出时 on_session_end（依赖 agent.py）
5. 更新测试
6. 文档更新（README + AGENTS.md + completion report）
