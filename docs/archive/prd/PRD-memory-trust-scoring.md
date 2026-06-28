> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 5
> 概要: 长期记忆信任分 + 检索晋升

# PRD: 长期记忆信任分 + 检索晋升机制

## Problem Statement

当前 `MemoryStore` 所有事实统一使用 `trust_score=0.5`，缺少来源区分和晋升通路。Regex 低置信提取、LLM 主动存储、用户反馈三种来源混在一起无法区分优先级。

具体问题：
- regex 误提取的噪音（"别走"提取出"走"）和 LLM 主动记的高置信事实都被 0.5 打平
- 一条事实被检索 100 次仍然是初始分，利用率不会影响排名
- 相同内容的事实两条来源冲突时，后写入的不覆盖信任分（先到 0.5 的先赢）

## Solution

三类改动：

1. **按来源设初始信任分**——regex 提取 → 0.3，LLM `fact_store` 工具 → 0.7，默认值改为 0.3
2. **检索晋升**——每次搜索命中后 `retrieval_count++`，ORDER BY 加入检索量 boost 因子（系数 0.002，上限 0.2）
3. **冲突合并**——相同内容的事实写入时，信任分取 `max(已有, 新传入)`

## User Stories

1. 作为 MemoryStore 使用者，我不希望 noisy regex 事实污染搜索结果，所以 regex 事实初始分应当低于 LLM 主动存储的事实
2. 作为 LLM 用户，当我主动调用 `fact_store` 工具存储一条事实时，这条事实的信任分应当高于 regex 自动提取的
3. 作为系统设计者，当 regex 先存了一条事实（0.3）、LLM 后调 `fact_store` 存了相同内容时，信任分应当提升到 0.7 而非保持 0.3
4. 作为系统设计者，当 LLM 先存了事实（0.7）、regex 后命中相同内容时，信任分应当保持 0.7 而非降级
5. 作为长期用户，一条事实被频繁检索命中时，它的排序权重应当自然提升
6. 作为系统设计者，检索量的 boost 应当有上限，防止热事实无限碾压高质量的冷事实

## Implementation Decisions

### 修改模块

**`animate/core/memory/store.py`** — MemoryStore：
- `add_fact()` 签名增加可选参数 `trust_score: float | None = None`
  - 传入时使用传入值
  - 不传入时使用 `self._default_trust`（改为 0.3）
  - IntegrityError 分支改为：`UPDATE facts SET trust_score = MAX(trust_score, ?) WHERE content = ?`
- `search_facts()` SQL 的 ORDER BY 增加检索 boost，使用 CASE 表达式实现 cap
- `search_facts()` 返回结果前遍历结果，每条事实 `retrieval_count++`
- `_default_trust` 默认值从 0.5 → 0.3

**`animate/core/memory/default_provider.py`** — DefaultMemoryProvider：
- `_handle_fact_store()` 中 `action == "add"` 时，显式传入 `trust_score=0.7`
- 其他路径（sync_turn、extract_quick_facts）不变，走默认 0.3

### 不变模块

- `MemoryProvider` ABC 不修改（接口不变）
- `MemoryNode`、`SystemPromptNode` 不修改（它们只消费 `memory_facts`，不触碰信任分）
- `fact_feedback` 工具逻辑不修改（仍然是 ±0.05 调整）
- Agent 集成层不修改

### Schema

**facts 表不迁移**——不增列、不改列类型，所有改动在应用层。

### 数据流

```
用户说"我喜欢喝咖啡"
  → sync_turn() → extract_quick_facts("我喜欢喝咖啡")
    → add_fact("用户喜欢喝咖啡", category="user_pref")
      → trust_score=0.3 (new default)

LLM 决定存 "用户喜欢用 DeepSeek"
  → fact_store tool {action: "add", content: "用户喜欢用 DeepSeek"}
    → _handle_fact_store() → add_fact("用户喜欢用 DeepSeek", trust_score=0.7)
      → trust_score=0.7

LLM 尝试存 "用户喜欢喝咖啡"
  → IntegrityError caught
    → UPDATE facts SET trust_score=MAX(trust_score, 0.7) WHERE content="用户喜欢喝咖啡"
    → 信任分从 0.3 提升到 0.7

每日对话后：
  search_facts("咖啡") 命中 "用户喜欢喝咖啡"
    → UPDATE facts SET retrieval_count += 1
    → ORDER BY boost: 原 0.7 + 检索增长期贡献 (capped at 0.2)
```

## Testing Decisions

### 测试原则
- 测 MemoryStore 的行为变化，不测系统集成
- 每个新逻辑有独立测试：默认分、自定义分、冲突合并、检索晋升
- 现有 `test_memory_store.py` 中的 25 个测试全部回归通过（改动不破坏已有行为）

### 测试模块

修改 `tests/test_memory_store.py`：

| 测试 | 说明 |
|------|------|
| `test_default_trust_0_3` | 不传 trust_score 时默认 0.3 |
| `test_custom_trust` | 传入 trust_score=0.7 时使用 0.7 |
| `test_merge_trust_upgrade` | 冲突时新信任分更高 → 提升 |
| `test_merge_trust_no_downgrade` | 冲突时新信任分更低 → 不降级 |
| `test_retrieval_count_increment` | search_facts 命中后 retrieval_count +1 |
| `test_retrieval_boost_in_order` | retrieval_count 影响排序（高 retrieval 排前面） |
| `test_retrieval_boost_capped` | 1000 次检索不会无限碾压（cap 有效） |

## Out of Scope

- 时间衰减（留到未来，当前通过 search 次数自然晋升）
- `/compact` CLI、`/resume` CLI（已在 HANDOFF 待办，非本 PRD）
- LLM 深度提取 `on_session_end()`（上文已论证不做了）
- 现有 0.5 旧数据的迁移（最终清库测试）
- `retrieval_count` 在 `list_facts()` 中的排序影响（只改 search）

## Further Notes

- `search_facts()` 的 `retrieval_count++` 是副作用，目前只被 `DefaultMemoryProvider.prefetch()` 调用，不存在并发问题。未来如果多线程调用，需要加事务或队列
- `fact_feedback` 工具（±0.05）和检索晋升（capped at +0.2）是两条独立的晋升路径，前者由 LLM 显式触发，后者由使用频率自动触发
- boost 系数 0.002 和 cap 0.2 的参数值可根据后续测试效果调整，当前是初始推荐值
