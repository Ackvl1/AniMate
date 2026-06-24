> 状态: ✅ 已实现 (2026-06)
> 阶段: Phase 修复
> 概要: 真流式 + CLI 优化 + 代码清理

# 修复：真流式 + CLI 优化 + 代码清理

## 问题域

Phase 4（日志 + 长期记忆）完成后，用户 code review 发现以下问题：

### P0 — 假流式（Bug 1）
`chat_stream()` 通过 `list[AgentEvent]` 收集所有事件，`engine.run()` 完全执行完后才批量 yield。这意味着：
- 所有 `text_token` 被缓存到内存
- 用户在终端等几秒，然后瞬间刷一段话
- 与 "流式" 语义完全不符

### P1 — CLI 初始情绪固定（Bug 2）
`cli.py` 的 `stream_chat()` 调 `output_adapter.stream_start()` 时没传 `emotion`。`ConsoleOutput.stream_start(emotion="calm")` 的默认值就是 `"calm"`，所以初始情绪图标永远是 😶，即使 state 已经有情绪。

### P1 — 每轮新事件循环（Bug 3）
- `cli.py` 主循环每轮 `asyncio.new_event_loop()` → `run_until_complete()` → `loop.close()`
- `agent.py` 的 `chat()` 同步封装也重复同样逻辑
- 性能浪费 + 循环泄漏风险

### P2 — EventBus 冗余
Agent 构造函数创建 `_event_bus = EventBus()`，但实际对话流走的是 `emit` 函数（传到引擎的 EventEmitter）。EventBus 仅被 `reset()` 调用一次 `self._event_bus.emit("agent.reset")`，而**无人 subscribe**。死代码。

## 方案

### 修复 1：asyncio.Queue 实现真流式

将 `list` 替换为 `asyncio.Queue`，emit 实时放入队列，引擎在后台 task 运行，chat_stream 主循环逐条 yield：

```
消费者                      生产者（引擎）
  │                           │
  │   async for ev in chat    │
  │       │                   │
  │       └── await get() ←───┼── emit → await put()
  │       └── await get() ←───┼── emit → await put()
  │       └── ...             │
  │                           │  engine.run() 完成
  │       └── None (哨兵)  ←──┼── finally: put(None)
  │                           │
  │   ← 写日志 + 记忆 + done  │
```

哨兵机制：引擎完成（正常或异常）后 `finally` 块放入 `None`，主循环收到 `None` 退出。

### 修复 2：CLI 情绪传递
`stream_chat()` 初始用 `"calm"`，但 `done` 事件携带情绪后 CLI 应该能直接看到。

### 修复 3：事件循环复用
`cli.py`：`loop` 提到 `while` 循环外创建，每轮只 `run_until_complete` 不重建。
`agent.py` 的 `chat()` 暂不改（仅单元测试和 CLI 调用）。

### 修复 4：删除 EventBus
- 从 `agent.py` 删除 `from ... import EventBus`、`self._event_bus`、`event_bus` property
- `reset()` 中 `self._event_bus.emit("agent.reset")` 改为 `pass`
- 从 `__init__.py` 导出中移除
- `events.py` 保留（可能的外部使用）

## 不修的设计问题
- `FIELD_WRITERS` vs `node.writes` 两套写保护未打通 — BSP 当前 4 个串行节点无冲突，未来扩展再说
- ReflectNode 条件边 mapping 是恒等映射 — 行为正确，路由直接通过

## 验收标准

1. `chat_stream()` 逐 token yield，不批量：消费者在 LLM 输出第一条 token 时就能收到 `text_token` 事件
2. 所有 180+ 单元测试仍然通过
3. CLI 启动/对话/退出正常
4. EventBus 完全从 Agent 中移除
