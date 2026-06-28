> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 2
> 概要: 目录重构 + 数据层 + 日志

# PRD: Anima Agent 架构重构 Phase 2 — 目录重组 + 数据层 + 日志

## Problem Statement

当前 Anima Agent 项目启动已优化至 ~5s，流式输出已实现，但有以下结构性问题阻碍后续多模态和 VTuber 路线：

1. `node_modules/` 位于项目根目录，是 Python 项目中的异物，与项目气质不搭
2. `animate/rag/` 游离于 `animate/core/` 之外，RAG 作为核心推理管线的一部分应归属 core
3. 数据文件（文档、向量库、关键词库）与代码混杂，没有独立的数据层
4. 每次 chat 的详细日志没有持久化存储，无法后续分析对话质量
5. BeforeNode 的日志级别过高，刷屏干扰用户体验

## Solution

对项目目录结构进行分层重构，将关注点分离为：核心代码（core）、I/O 适配（io）、数据存储（data）。

## User Stories

1. 作为一名开发者，我希望 MCP 依赖从项目根目录移到 `core/tools/mcp/` 子目录，这样项目根目录只保留 Python 项目文件
2. 作为一名开发者，我希望 `animate/rag/` 移入 `animate/core/rag/`，这样所有核心推理代码在同一层级
3. 作为一名开发者，我希望数据文件（文档、向量库、关键词库）统一放在 `animate/data/` 层，这样数据与代码分离
4. 作为一名开发者，我希望每次 chat 的输入输出、耗时、情绪变化写入 SQLite 日志库，这样后续可以分析对话质量
5. 作为一名用户，我希望 BeforeNode 的详细消息长度日志降至 DEBUG 级别，这样控制台不被刷屏干扰
6. 作为一名开发者，我希望 `buildLibrary.py` 仍然能正常工作，数据路径更新后知识库构建不受影响

## Implementation Decisions

### 模块变更

| 操作 | 模块 | 说明 |
|------|------|------|
| 新建 | `animate/core/tools/mcp/package.json` | 声明 MCP 依赖（filesystem + memory） |
| 移动 | `animate/core/tools/mcp/node_modules/` | 从根目录 `node_modules/` 迁移至此 |
| 更新 | `animate/core/tools/mcp/manager.py` | `_node_modules()` 路径改为本地 node_modules |
| 删除 | 根目录 `package.json` + `node_modules/` | 不再需要 |
| 移动 | `animate/rag/` → `animate/core/rag/` | RAG 归入 core |
| 新建 | `animate/data/` | 数据层根目录 |
| 移动 | `animate/rag/documents/` → `animate/data/documents/` | 知识库源文件 |
| 移动 | `animate/rag/vectorlibrary/` → `animate/data/vectorlibrary/` | 向量数据库 pkl |
| 移动 | `animate/rag/keywordLibrary/` → `animate/data/keywordLibrary/` | 关键词库 pkl |
| 新建 | `animate/data/logs/` | 日志数据库目录 |
| 新建 | `animate/data/logs/log_db.py` | SQLite 日志数据库模块 |
| 更新 | `cli.py` | RAG 加载路径改为 `animate/data/` |
| 更新 | `buildLibrary.py` | 数据路径改为 `animate/data/` |
| 更新 | `animate/core/logger.py` | 默认日志级别改为 INFO（BeforeNode 的详细日志降至 DEBUG） |
| 更新 | `animate/core/agent/nodes/before.py` | 消息长度日志改为 `logger.debug()` |

### 数据层结构

```
animate/data/
├── documents/
│   └── Saki/         知识库源 Markdown 文件
├── vectorlibrary/
│   └── Saki.pkl      向量数据库
├── keywordLibrary/
│   └── Saki.pkl      关键词倒排索引
└── logs/
    └── chat_log.db   SQLite 日志数据库
```

### SQLite 日志表结构

```sql
CREATE TABLE chat_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    user_input TEXT,
    response_text TEXT,
    emotion TEXT,
    gesture TEXT,
    llm_call_count INTEGER,
    total_duration_ms INTEGER,
    tool_calls TEXT,       -- JSON 数组
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 路径引用

所有数据路径从硬编码改为中央配置，新增 `animate/core/paths.py` 模块统一管理。

## Testing Decisions

### 测试原则
- 测试外部行为，不测试实现细节
- 每个测试只测一件事
- 使用真实文件路径（临时目录），不 mock 文件系统

### 要测试的模块

| 模块 | 测试内容 |
|------|---------|
| `animate/core/tools/mcp/manager.py` | `_node_modules()` 路径解析正确性 |
| `animate/data/logs/log_db.py` | 写入/查询/清空日志 |
| `cli.py`（集成测试） | RAG 数据路径更新后能正常加载 |
| `animate/core/paths.py` | 各数据目录路径解析 |

### 现有测试不受影响

现有 133 个测试在 `tests/` 目录下，重构后 import 路径变更可能导致测试失败。需同步更新测试文件中的路径引用。

## Out of Scope

- 流式输出的进一步优化（已经在 Phase 1 完成）
- EmotionNode 的实现（将在 Phase 3 进行）
- 图引擎替换 while 循环（将在 Phase 3 进行）
- 多模态支持（Phase 4+）
- 可视化日志分析工具

## Further Notes

日志数据库设计为最小可用版本，后续可扩展为：
- 对话评分（用户可对回复点赞/点踩）
- 情绪变化趋势分析
- 工具调用成功率统计
- 模型切换频率监控
