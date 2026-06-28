# ADR: Phase 5.1 — 自动压缩全线修复

## Status

Accepted (2026-06-24)

## Context

Phase 5 实现了 `ContextManager` 压缩引擎和 CLI 命令，但自动触发链路从未接通。`update_from_response()` 未被调用、`_accumulated` 语义错误（覆盖而非累加）、流式 API 未获取 usage 数据——三个断裂点叠加，导致长对话 token 无限膨胀。

## Decision

全线打通自动压缩链路，分 7 个修改点：

| # | 修改 | 原理 |
|---|------|------|
| 1 | `update_from_response`: `=` → `+=` | API 返回单次 token 数，需累加，非覆盖 |
| 2 | `compress()` 成功后 `_accumulated = 0` | 压缩后 session 旋转，旧累计值不再有意义 |
| 3 | `/compact` 去掉 `need_compress()` 守卫 | 用户期望强制压缩，非条件触发 |
| 4 | `model_limit` 从 config.yaml 读取 | 避免硬编码 1M，按实际模型配置 |
| 5 | `_build_kwargs` 加 `stream_options` + 流式处理 usage chunk | OpenAI/DeepSeek API 支持 `include_usage` 获取实际 token |
| 6 | RunContext.accumulated_usage + ReactNode 累加 + agent.py post-turn 调用 | 完整数据链路从 API 到 ContextManager |
| 7 | 修测试造假：去掉 `_accumulated = 800_000` 绕过 | 不再通过内部属性强制触发 |

## Consequences

- 压缩链路不再断裂，`need_compress()` 可正常返回 True
- `/compact` 始终尝试压缩
- 流式响应 final chunk 获取实际 token 数，不依赖估算
- ReAct 多轮调用中所有 LLM 调用的 usage 累加计入本轮总 token
- 测试不再绕过真实路径

## Risks

- `stream_options: {"include_usage": True}` 在 DeepSeek 上的兼容性未验证（OpenAI 确认支持）
- 模型切换后阈值仍不更新（需后续 PRD 处理）
