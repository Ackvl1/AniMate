# PRD: Session End LLM 深度事实提取

## Problem Statement

当前 `on_session_end()` 是空操作——Agent.reset() 调了但啥都不发生。会话结束时，对话中的有价值信息（用户偏好、项目细节、关系信息）随 session 冻结而丢失。regex 提取（`extract_quick_facts`）只能捕获特定模式（"我喜欢X"），覆盖面有限。

## Solution

实现 `DefaultMemoryProvider.on_session_end()`：会话结束时调 LLM 从完整对话中深度提取跨会话有价值的长期事实，存入 MemoryStore（trust=0.7）+ ChatLogDB（审计层）。

## User Stories

1. 作为用户，我希望会话结束时系统自动记住我提到的偏好和事实，下次对话能用上
2. 作为用户，我希望寒暄和命令消息不被提取为事实
3. 作为用户，我希望角色的表演性台词不被错误提取为用户事实
4. 作为开发者，我希望提取失败不阻断 reset 流程
5. 作为开发者，我希望提取的事实有更高的信任分（0.7）区别于 regex 提取（0.3）
6. 作为开发者，我希望事实同时写入状态层和审计层

## Implementation Decisions

### 1. 提取范围

从完整对话（user + assistant）输入 LLM，prompt 约束"只提取关于 user 的稳定事实，persona 表演台词不入库"。

### 2. LLM 调用方式

同步 `self._llm.chat()`。reset 是 CLI 低频操作，可阻塞 2-3 秒。

### 3. Prompt 形态

通用 fact 提取 + 注入 persona 领域关键词作为关注提示。fact 文本保持第三人称客观。

### 4. 去重策略

文本归一化（全/半角 + 缩写展开 + 去尾标点）后精确匹配。MemoryStore.add_fact() 的 IntegrityError 机制自动处理。

### 5. 最小轮数

user 消息 ≥ 4 条（过滤命令消息凑数）。

### 6. trust_score

硬编码 0.7（LLM 提取 > regex 的 0.3）。

### 7. 双写

MemoryStore.add_fact()（状态层）+ ChatLogDB.add_fact()（审计层），与 fact_store 工具同路径。

### 8. 领域关键词注入

persona → 领域关键词映射，注入 prompt 让 LLM 关注相关领域。不让 LLM 扮演 persona。

## File Changes

| 文件 | 改动 |
|------|------|
| `animate/core/memory/default_provider.py` | 新增 `on_session_end()` override + `_format_conversation()` + `_normalize_fact()` + `EXTRACT_PROMPT_TEMPLATE` + `_DOMAIN_KEYWORDS` |
| `animate/core/agent/agent.py` | `__init__` 传 `persona_name` 给 provider |
| `animate/core/memory/provider.py` | 不改（ABC 已有空方法） |
| `tests/test_session_end_extraction.py` | 新增 6 个测试 |

## Testing Decisions

- 测试 LLM mock：验证调用次数、解析结果、trust_score、双写、异常吞掉
- 6 个用例：跳过少于 4 条、正常提取、persona 台词不入库、归一化去重、LLM 失败不崩溃、双写验证

## Out of Scope

- 异步 LLM 调用（reset 不急）
- 动态 trust_score（硬编码 0.7）
- 事实冲突合并逻辑（依赖现有 IntegrityError 机制）
- session_end 的 DiffHistory 记录（不属于 diff 链）
