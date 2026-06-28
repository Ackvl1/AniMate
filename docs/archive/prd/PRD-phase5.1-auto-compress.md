> 状态: ✅ 已实现 (2026-06)
> 阶段: ?
> 概要: 

# PRD: Phase 5.1 — 自动压缩全线修复

## Problem Statement

Phase 5 实现了 `ContextManager`、流式管道、CLI `/compact`/`/resume` 命令，但自动压缩链路存在 3 个实现断裂，导致 **`need_compress()` 永远返回 False**，长对话（500+ 轮）持续膨胀不压缩：

1. **`update_from_response()` 从未被调用** — 代码写了 API，但 agent.py 的 chat_stream() post-turn 没有调它
2. **`_accumulated = total` 而非 `+= total`** — 语义错误，导致只能跟踪最后一次 LLM 调用的 token 数，无法累积
3. **`/compact` 命令被 `need_compress()` 挡住** — 用户期望强制压缩，实际变成"阈值到了才压"，但阈值永远到不了
4. **`model_limit` 硬编码 1M** — 不匹配实际模型窗口（如 DeepSeek V4 Flash 1M、Pro 64K）
5. **流式响应未获取 usage** — `stream_options: {"include_usage": True}` 未传，导致 API 不返回实际 token 数
6. **压缩后 `_accumulated` 不重置** — 旧 token 计数残留，可能触发重复压缩

## Solution

全线打通自动压缩链路：从流式 API 拿实际 usage → 累加 → 阈值检查 → 自动触发 → 压缩后重置。

### 数据流

```
OpenAI/DeepSeek 流式响应
  │  stream_options: {"include_usage": True}
  │  final chunk → chunk.usage.total_tokens
  ▼
LLM Client (client.py)
  │  yield {"type": "usage", "total_tokens": N}
  ▼
ReactNode (react.py)
  │  ctx.accumulated_usage += usage.total_tokens  每轮累加
  ▼
Agent chat_stream post-turn (agent.py)
  │  self._ctx_mgr.update_from_response({"total_tokens": ctx.accumulated_usage})
  │  self._ctx_mgr._accumulated += total_tokens
  │  if need_compress(): compress()
  ▼
ContextManager (manager.py)
  │  compress success → _accumulated = 0
```

## User Stories

1. 作为用户，我希望聊天 500+ 轮后系统自动压缩历史，而不是一直膨胀直到 API 报错
2. 作为用户，我希望 `/compact` 始终强制触发压缩，不管阈值到没到
3. 作为用户，我希望压缩完成后能看到压缩结果（成功/跳过/失败）
4. 作为开发者，我希望 token 追踪从流式 API 拿实际 usage，不靠估算
5. 作为开发者，我希望 `_accumulated` 正确累加（`+=`），而非覆盖（`=`）
6. 作为开发者，我希望模型窗口大小从 config.yaml 配置，不改代码
7. 作为开发者，我希望压缩成功后 `_accumulated` 重置为 0，避免重复压缩
8. 作为开发者，我希望 `compact()` 方法不再依赖 `need_compress()` 守卫
9. 作为开发者，我希望切换模型后阈值可以更新（动态配置接口）

## Implementation Decisions

### 模块变更

**`animate/core/config.yaml`**
- `compress` 段新增 `model_limit: 1000000`（默认 1M，按实际模型调整）

**`animate/core/config.py`**
- `get_compress_config()` 增加 `model_limit` 返回值

**`animate/core/context/manager.py`** (3 处修改)
- `update_from_response()`: `_accumulated = total` → `_accumulated += total` (line 51)
- `compress()` 成功末尾: `self._accumulated = 0` (重置累计值)
- 构造函数 `_model_limit` 从 config.yaml 的 `compress.model_limit` 读取，保留参数覆盖

**`animate/core/llm/client.py`** (2 处修改)
- `_build_kwargs()`: `stream=True` 时追加 `"stream_options": {"include_usage": True}`
- `chat_stream_async()` 流式循环: 最后一个 chunk 可能 `choices=[]`（usage-only chunk），处理 `chunk.usage` 并 yield `{"type": "usage", "total_tokens": ...}`
- `chat_stream()` (同步): 同理处理 usage chunk

**`animate/core/llm/models.py`**
- `LLMResult` 新增 `usage: dict | None = None` 字段（非流式路径备用）

**`animate/core/agent/nodes/react.py`** (2 处修改)
- `_stream_round()` 的 `handle_event()` 闭包: 处理 `event["type"] == "usage"` → 累加到 `ctx.accumulated_usage`
- `_stream_round()` 返回前: 将 `pending_usage` 附到返回值或 ctx

**`animate/core/engine/context.py`**
- `RunContext` 新增 `accumulated_usage: int = 0` 字段（跨 ReAct 多轮累加）

**`animate/core/agent/agent.py`** (2 处修改)
- `compact()`: 去掉 `need_compress()` 守卫，直接调 `compress()`
- `chat_stream()` post-turn: 在 yield `done` 前调 `self._ctx_mgr.update_from_response({"total_tokens": ctx.accumulated_usage})`

**`cli.py`**
- 无修改（`/compact` 已经调 `agent.compact()`）

### 技术细节

- OpenAI/DeepSeek 流式响应中，设置了 `stream_options: {"include_usage": True}` 后，最后一个 chunk 的 `choices` 可能为 `[]`（空列表），此时 `chunk.usage` 包含完整 usage
- 当前代码 `chunk.choices[0]` 会在空列表时 IndexError，需加空检查
- ReAct 多轮场景：一轮对话可能有最多 10 次 LLM 调用，`accumulated_usage` 累加所有 round 的 token 数，post-turn 一次传给 ContextManager
- `model_limit` 默认 1M（DeepSeek V4 Flash），用户按实际模型在 config.yaml 调整
- 压缩成功后重置 `_accumulated = 0`：新 session 重新开始累积

## Testing Decisions

### 测试原则

- 测试外部行为：LLM 响应的 usage 是否被正确捕获、累加、触发压缩
- `client.py` 的 usage 捕获用 mock OpenAI chunk 测试
- `ContextManager` 的累加行为直接构造 `update_from_response({"total_tokens": N})` 验证
- `agent.py` 的压缩触发用 mock LLM 验证 post-turn 调用

### 需要修改的测试

| 测试文件 | 修改内容 |
|---------|---------|
| `tests/test_agent_compact_resume.py` | 去掉 `_accumulated = 800_000` 造假；改为真实的 `update_from_response()` 调用 |
| `tests/test_context_manager.py` | `update_from_response` 测试验证 `+=` 而非 `=`；多轮累加测试 |
| `tests/test_agent_logging.py` | 如果测试了压缩后日志，验证 `_accumulated` 重置 |

### 预期新增/修改测试数

约 5-8 个测试点（大部分已存在，只需修正语义）。

## Out of Scope

- 模型切换后动态更新阈值（后续做，目前配最保守的模型窗口）
- token 估算 fallback（`include_usage` 不可用时的替补方案）
- 压缩进度显示（已有，不处理）
- Session rotation 变更（已有，不处理）

## Further Notes

- 这个 PRD 不引入新架构，只修 6 个实现 bug
- 参考 PRD-short-term-memory-context.md（原始设计）和 PRD-phase5-cli-logging-trust.md（接入计划）
- 现有测试 `test_agent_compact_resume.py:36` 用 `_accumulated = 800_000` 绕过——修复后必须改成真实的 token 累加路径
