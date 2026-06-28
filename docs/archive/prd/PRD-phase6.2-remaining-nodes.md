# PRD: Phase 6.2 剩余节点 Return-Diff 迁移（方案 A）

## Problem Statement

Phase 6.1 完成了 Return-Diff 基础设施（NodeResult.diff, RunContext.snapshot/restore, GraphEngine._apply_diff, DiffHistory），Phase 6.2 已迁移 3 个节点（MemoryNode, AfterNode, ReflectNode）。剩余 5 个节点仍直接写 ctx，状态变更不可追踪、不可审计、不可回滚。

## Solution

将剩余 5 个节点迁移到 Return-Diff 架构。采用方案 A：ReactNode diff 含全部 6 字段（含 emotion/gesture），`_apply_diff` 移除 emotion/gesture 的 auto final emit，AfterNode 显式 emit emotion.final/gesture.final。emotion/gesture 的 `setattr` 去掉 `if current != value` 判断，与 messages/EXTRAS_FIELDS 分支风格对齐。

## User Stories

1. 作为开发者，我希望 RAGVectorNode 返回 diff，使得向量检索结果可通过 diff 机制追踪
2. 作为开发者，我希望 RAGKeywordNode 返回 diff，使得关键词检索结果可通过 diff 机制追踪
3. 作为开发者，我希望 SystemPromptNode 返回 diff，使得 system_parts 和 retry_feedback_injected 可通过 diff 机制追踪
4. 作为开发者，我希望 MergeNode 返回 diff，使得 messages 组装结果可通过 diff 机制追踪
5. 作为开发者，我希望 ReactNode 返回 diff，使得 LLM 调用结果（messages, token 计数, emotion, gesture, raw_text）可通过 diff 机制追踪
6. 作为系统，我希望 emotion.final 事件仅在 AfterNode 校验后发射一次，使得最终情绪语义明确
7. 作为系统，我希望 gesture.final 事件仅在 AfterNode 校验后发射一次，使得最终姿态语义明确
8. 作为 VTuber 前端，我希望流式中实时接收 emotion.update 事件，使得表情可实时切换
9. 作为开发者，我希望 DiffHistory 完整记录每步 diff，使得对话状态可纯 diff 回放
10. 作为开发者，我希望迁移后全量测试通过，使得现有功能不受影响

## Implementation Decisions

### 1. ReactNode diff 字段集（6 字段）

ReactNode 在两个 return 点（正常结束、达到最大轮数）统一返回：

- `messages`：run() 局部变量，含完整 ReAct 循环历史
- `raw_text`：ctx.raw_text，由 _stream_round 每轮写入
- `emotion`：ctx.emotion，由 tracking_emit 流式写入
- `gesture`：ctx.gesture，由 tracking_emit 流式写入
- `llm_call_count`：ctx.llm_call_count，由 _stream_round 每轮累加
- `accumulated_usage`：ctx.accumulated_usage，由 _stream_round 每轮累加

流式 ctx 直写全部保留（实时 UI、AfterNode 读取）。diff 是流式最终态的快照。

### 2. `_apply_diff` emotion/gesture 分支重构

移除 auto final emit，去掉 `if current != value` 判断，与 messages/EXTRAS_FIELDS 分支风格对齐：

```python
else:
    if field in ("emotion", "gesture"):
        setattr(ctx, field, value)
    else:
        current = getattr(ctx, field, None)
        if current != value:
            setattr(ctx, field, value)
```

理由：
- 消除 dead getattr 计算
- emotion/gesture 由 AfterNode 校验保证语义，引擎不做判等
- 为将来去掉 ReactNode 流式 ctx 直写预留（diff 成为唯一写入路径时已 ready）

### 3. AfterNode 显式 emit emotion.final / gesture.final

AfterNode 的两个 return 分支（空文本分支、正常分支）都显式 emit：

- 空文本分支：emit emotion.final(value="calm"), gesture.final(value=None)
- 正常分支：emit emotion.final(value=emotion), gesture.final(value=gesture)

时序保证：emit 在 node.run() 内部执行（先于 NodeResult 返回），`_apply_diff` 在返回后执行。两者无冲突。

### 4. ReactNode 删除 next_node="after"

ReactNode 的两个 return 点当前带 `next_node="after"`，但 ReactNode → AfterNode 是 direct 边，引擎不看 NodeResult.next_node。删除以保持一致（其他已迁移节点如 AfterNode、ReflectNode 也不带冗余 next_node）。

### 5. FIELD_WRITERS 校验

6 字段的 FIELD_WRITERS 允许写入者：

| 字段 | 允许写入节点 | ReactNode 在列？ |
|------|-------------|-----------------|
| messages | system_prompt, merge, react | ✅ |
| raw_text | react | ✅ |
| emotion | system_prompt, react, after | ✅ |
| gesture | react, after | ✅ |
| llm_call_count | react, reflect | ✅ |
| accumulated_usage | react, reflect | ✅ |

### 6. 迁移顺序

1. RAGVectorNode（L=1）
2. RAGKeywordNode（L=1）
3. SystemPromptNode（L=2）
4. _apply_diff 重构 + AfterNode 显式 emit（L=1）
5. MergeNode（L=3）
6. ReactNode（L=3，方案 A 下 holder 不需要，流式写 ctx 保留）

### 7. 边界情况

在迁移过程中顺带处理，不单独开阶段：
- retry 重入时 ctx.emotion 残留（现状行为，B 不引入新问题）
- usage_before 比较逻辑（diff 覆盖确保落盘，幂等无损）
- raw_text 每轮重置（现状行为，无下游依赖）

## Testing Decisions

### 测试策略（C：混合）

- RAGVectorNode / RAGKeywordNode：适配现有测试（太简单，不写专项）
- SystemPromptNode：适配现有测试 + retry feedback diff 断言
- MergeNode：写专项测试 test_node_merge_diff.py（多输入聚合逻辑需验证）
- ReactNode：写专项测试 test_node_react_diff.py（流式+工具循环+diff 6 字段）

### 红测入口（按依赖顺序）

1. test_node_react_diff.py::test_react_returns_six_field_diff — 断言 diff 含 6 字段且值匹配 ctx 终态
2. test_node_react_diff.py::test_react_no_next_node — 断言 next_node 为 None
3. test_node_after_diff.py::test_after_emits_emotion_final_explicitly — 断言 AfterNode emit emotion.final 一次
4. test_engine_apply_diff.py::test_apply_diff_no_auto_emit_for_emotion — 断言 _apply_diff 写 emotion 后不 emit emotion.final
5. 适配 test_engine_apply_diff.py 旧断言
6. 适配 test_nodes_after.py

### 测试不改的文件

- test_marker_streamer.py：测 emotion.update（流式事件），ReactNode 流式 emit 行为不动
- test_log_collector.py：LogCollector 吃 emotion.update，不受影响

## Out of Scope

- ReactNode 流式 ctx 直写去掉（将来渐进迁移，本次不动）
- EmotionNode 独立节点（已讨论，暂不实施）
- DiffHistory 纯 diff 回放功能（仅确保存储完整，回放功能后续单独做）
- 前端 emotion.final 消费逻辑（前端已通过 done 事件获取最终情绪）
- Phase 6.5 边界情况处理（8 个问题的系统性处理）
- Phase 6.6 全量测试 + B4 激活

## Further Notes

- 方案 A vs B 的选择依据：Plan A 的 diff 完整性为 DiffHistory 纯 diff 回放预留，多改 2 个文件换来 diff 链 100% 完整
- emotion.final 语义从"引擎自动"变为"AfterNode 显式"——这是有意的契约变化，需文档化
- 伏笔：`_apply_diff` 对 emotion/gesture 去掉判等，为将来去掉 ReactNode 流式 ctx 直写预留
