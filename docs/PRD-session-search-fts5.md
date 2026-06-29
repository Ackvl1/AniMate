# PRD: Session Search — FTS5 全文索引升级

## Problem Statement

当前 `SessionSearchTool` 的搜索实现在 `session/store.py:search_ancestors` 采用**Python 子串匹配**遍历所有祖先 session 的全量消息 JSON：

```python
# 每次搜索：遍历所有 session → 反序列化全量 messages JSON → Python in 子串匹配
msgs = json.loads(row["messages"])
for m in msgs:
    if query in str(m.get("content", "")):  # O(N) 线性扫描
        results.append(...)
```

三个核心问题：

1. **无索引，O(S×M×L) 复杂度**：S 个 session、M 条消息、L 字符长度。压缩越多次，session 链越长，每次搜索都重新遍历——最差情况下每次搜索反序列化数 MB 的 JSON
2. **无相关性排序**：匹配结果按祖先链遍历顺序返回（离根最近的 session 排在前面），不按匹配质量排序，用户难以找到真正相关的对话
3. **无上下文**：只返回匹配的单条消息，不带前后对话上下文，用户需要手动翻找才能理解匹配片段的含义

会话搜索会随压缩轮数累积而线性变慢，且中文/日文/英文混合查询用子串匹配召回质量不稳定。虽然英文反向兼容，但项目未来需要支持英文和日文角色对话，搜索引擎需要三语通用。

## Solution

将 `search_ancestors` 从 Python 子串遍历升级为 **SQLite FTS5 全文索引 + trigram tokenizer**，并提供三种查询模式（对标 Hermes 的 Discovery/Scroll/Browse 三模式），沿用现有 memory.db 的 FTS5 技术栈，不引入新依赖。

### 为什么 FTS5 trigram

| Tokenizer | 中文 | 英文 | 日文 | 额外依赖 |
|---|---|---|---|---|
| unicode61 | ❌ 逐字拆分 | ✅ 空格分词 | ❌ 逐字拆分 | 0 |
| jieba | ✅ | ⚠️ | ❌ 不认识日语 | jieba |
| **trigram** | ✅ 3-gram | ✅ 3-gram | ✅ 3-gram | **0** |

trigram 是唯一零依赖、三语通用的方案。精度不如专用分词器，但 session 搜索不是语义搜索——用户搜 "认证" 命中包含 `认证` 的消息即可，不需要 jieba 级别的精准分词。

## User Stories

1. 作为 LLM Agent，我希望通过 `session_search` 快速查到历史对话中的关键信息，以便在回答时引用过去的上下文
2. 作为 LLM Agent，我希望搜索结果按相关性排序而非按 session 时间顺序，以便优先看到最匹配的内容
3. 作为 LLM Agent，我希望搜索结果包含匹配消息的前后对话，以便理解信息的完整语境
4. 作为用户，我希望 session 搜索在 10+ 轮压缩后仍然保持快速，而不是越来越慢
5. 作为用户，我希望搜索支持中文、英文、日文混合查询，不同语言的角色对话都能被检索
6. 作为调试者，我希望能够浏览最近的 session 列表（不输入查询词），以便了解对话历史结构
7. 作为 LLM Agent，我希望搜索结果保持 5000 字符上限（Result Budgeting 兼容），避免返回超长结果撑爆上下文

## Implementation Decisions

### 1. FTS5 trigram 索引

采用 trigram tokenizer，作为唯一零依赖、三语通用的方案。

**2-gram 回退策略**：trigram 对太短的查询词（如 "TO"、"AI"）可能有漏召回。虽然方案内，但可先不做，因为对英文短词召回率的影响小于新增的 BM25 排序带来的收益。

### 2. 消息存储持久化

每次 `save_messages()` 时自动同步 FTS5 索引。利用 FTS5 的 `content=` 模式，FTS5 表直接从原始表读取数据，无需手动同步内容。只在消息内容变更时才需要 rebuild（目前不会有）。有空的看是否需要迁移现有数据。

### 3. 三种查询模式

对标 Hermes 的 Discovery / Scroll / Browse 三模式，Anima 实现：

- **Search（搜索）**：`query` 参数必填 → FTS5 MATCH → 按 rank 排序 → 返回匹配消息 ± 上下文窗口 → 支持 `limit` 参数限制结果数
- **Browse（浏览）**：无 `query` → 返回最近 N 个 session 的摘要（首条消息预览 + 时间戳）→ 供 LLM 了解历史结构
- **Scroll（翻页）**：`session_id` + `around_message_id` / `offset` → 返回指定位置的消息上下文 → 供 LLM 深入查看某段对话

第一期仅实现 Search + Browse。Scroll 使用场景有限（用户极少通过 LLM 工具逐条翻看历史消息），可后续按需添加。

### 4. Search 返回结构

直接 JSON 序列化为字符串返回给 LLM，兼容 Result Budgeting 的 5000 字符截断。

### 5. Tool schema 变更

`SessionSearchTool.parameters` 新增字段支持多模式。

## Testing Decisions

### 测试边界

- 空查询 → Browse 模式，返回 session 列表
- 中文/英文/日文混合查询 → FTS5 trigram 命中
- 极短查询词（1-2 字符）→ 不崩溃，返回合理结果或空
- 无匹配结果 → 返回空列表 + 提示信息
- 大量 session（20+）→ 祖先链遍历 + 搜索仍快速
- 搜索结果超 5000 字符 → Result Budgeting 自动截断

### 测试风格

与现有 `test_session_store.py` 风格一致：创建 SessionStore → 写入消息 → 搜索 → 断言结果结构。

## Further Notes

- FTS5 trigram 对短词（1-2 字符）天然支持弱——这是已知 Trade-off，不处理
- 消息表写入逻辑在 `save_messages()` 中，不需要额外的事务管理
- 未来 Scroll 模式可通过 `msg_index BETWEEN ? AND ?` 实现上下文窗口翻页
