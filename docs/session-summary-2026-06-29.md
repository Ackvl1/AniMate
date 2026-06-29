# 2026-06-29 Session Summary

> **日期**: 2026-06-29  
> **测试状态**: 532 passed, 1 failed (pre-existing MCP), 2 skipped  
> **工作时长**: ~3 小时  

---

## 今日完成

### 1. Bug 修复：cli.py 路径错误

**问题**: `cli.py` 引用 `animate/data/prompts/saki_persona.txt`，但包已改名 `anima`  
**修复**: 3 处 `animate/` → `anima/`  
**文件**: `cli.py` lines 436, 437, 440  

### 2. Bug 修复：session_search SQLite 跨线程问题

**问题**: `SessionSearchTool` 被标记为 `is_parallel_safe=True`，导致在 `run_in_executor` 线程池中执行，与主线程的 SQLite 连接冲突  
**错误**: `SQLite objects created in a thread can only be used in that same thread`  
**修复**: `is_parallel_safe = False`（1 行改动）  
**文件**: `anima/core/tools/function/memory_tools.py` line 64  
**分析过程**: grill-me 流程，对比 4 种方案（独立连接 / aiosqlite / Lock / 禁用并行），最终选择最简方案  

### 3. FTS5 trigram 全文索引升级

**需求**: session_search 从 Python 子串匹配升级为 FTS5 全文索引  
**决策**: FTS5 trigram tokenizer（零依赖、中/英/日三语通用）  
**实现**:
- 新增 `session_messages` 表（id, session_id, role, content, msg_index）
- 新增 `session_messages_fts` 虚拟表（trigram tokenizer）
- `init_session()` / `save_messages()` 自动同步 FTS5 索引
- `search_ancestors()` 升级为 FTS5 MATCH + BM25 排序 + 上下文窗口
- 新增 Browse 模式（空 query → 返回最近 session 列表）

**文件**:
- `anima/core/session/store.py` — schema + search_ancestors + _sync_messages + _get_context + _browse_sessions
- `tests/test_session_fts5.py` — 12 个新测试
- `tests/test_session_store.py` — 3 个旧测试适配
- `docs/PRD-session-search-fts5.md` — PRD 文档
- `docs/architecture-decision-records.md` — ADR-15 更新为"已实现"

**已知 Trade-off**: FTS5 trigram 需要 3+ 字符查询，1-2 字符短词搜不到

### 4. 清理旧残留

**删除**:
- `animate/` 目录（旧包名残留，4 个 DB 文件）
- `diff_history.db`（根目录旧残留，760 行 vs anima/ 的 5013 行）

### 5. 技术调研

#### regex 事实提取质量问题
**现状**: 15 个 regex pattern 提取质量差，8 条中只有 1 条有效事实  
**问题**: 无疑问句过滤、无最小长度、无去重  

#### 记忆衰减机制调研
**主流方案**:
- Mem0: 检索时重排（不删除），最近访问 boost 1.5x，未用 dampen 0.3x
- FadeMem: 双层架构（LTM/STM）+ 基于重要性的衰减
- TTL: 时间-based 删除 + salience floor
- LRU: N 天未检索 → 删除

**建议**: 利用现有 trust_score + 加 `last_accessed_at` 字段，trust < 0.4 且 4 天未检索 → 删除

#### execute_python 阻塞问题
**问题**: `subprocess.run()` 同步阻塞事件循环，卡住时 agent 冻结  
**建议**: 改用 `asyncio.create_subprocess_exec` + 加全局 tool call 上限  

---

## 测试变化

```
Baseline (2026-06-28): 499 passed
After session_search FTS5: 532 passed (+33)
  - test_session_fts5.py: +12 (新建)
  - test_session_store.py: +1 (适配)
  - 其他测试自动受益于 FTS5 升级
```

---

## 后续计划

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | execute_python 改异步 | 防止 agent 冻结 |
| P0 | 全局 tool call 上限 | 防止 LLM 无限重试 |
| P1 | regex 提取质量改进 | 过滤疑问句、最小长度、去重 |
| P1 | 记忆衰减机制 | last_accessed_at + trust < 0.4 且 4 天未检索 → 删除 |
| P2 | FTS5 2-gram 回退 | 解决 1-2 字符短词召回问题 |
| P2 | Scroll 模式 | session_search 第三期 |

---

## 技术决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| session_search 线程安全 | `is_parallel_safe=False` | 1 行改动，无代码重复，预执行收益可忽略 |
| FTS5 tokenizer | trigram | 唯一零依赖三语方案 |
| FTS5 存储模式 | 自存储（非 content=） | 避免 rebuild 复杂度 |
| 记忆衰减策略 | TTL + LRU 混合 | 复用现有 trust_score，最小改动 |
