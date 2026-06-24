"""AfterNode — 校验 emotion/gesture + 应用复合规则（inline marker 版）

ReactNode 已通过 TextMarkerStreamer 实时处理了 (emotion,gesture) 标记并设置了
ctx.emotion/ctx.gesture/ctx.raw_text。AfterNode 只做最终校验和复合规则应用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from animate.core.engine.node import Node, NodeResult
from animate.core.log import setup_logger
from animate.core.constants import KNOWN_EMOTIONS, KNOWN_GESTURES, EMOTION_GESTURE_RULES

if TYPE_CHECKING:
    from animate.core.engine.context import RunContext

logger = setup_logger(__name__)


class AfterNode(Node):
    """Phase 3: 校验最终 emotion/gesture，应用复合规则。

    ReactNode 已在流式过程中解析了 inline marker 并实时发射 text_token 和
    emotion.update 事件。AfterNode 负责：
      - 验证 emotion 是已知值
      - 应用 emotion→gesture 复合规则
      - 备份清理残留的标记（LLM 可能不严格遵循格式）
    """

    KNOWN_EMOTIONS = KNOWN_EMOTIONS
    KNOWN_GESTURES = KNOWN_GESTURES
    EMOTION_GESTURE_RULES = EMOTION_GESTURE_RULES

    async def run(self, ctx: "RunContext", emit) -> NodeResult:
        await emit("node.start", name="after")
        text = ctx.raw_text.strip()
        if not text:
            ctx.final_text = ""
            await emit("node.done", name="after", emotion="", gesture=None, length=0)
            return NodeResult(next_node="reflect")

        # 备份清理：如果 LLM 没按 inline marker 格式输出，raw_text 可能含残留标记
        from animate.core.agent.nodes.marker_streamer import TextMarkerStreamer
        cleaned = TextMarkerStreamer.strip_markers(text)
        ctx.final_text = cleaned

        # 校验 emotion
        if ctx.emotion and ctx.emotion not in self.KNOWN_EMOTIONS:
            logger.info("unknown emotion '%s', fallback to calm", ctx.emotion)
            ctx.emotion = "calm"

        if not ctx.emotion:
            ctx.emotion = "calm"

        # 校验 gesture
        if ctx.gesture and ctx.gesture not in self.KNOWN_GESTURES:
            logger.info("unknown gesture '%s', removed", ctx.gesture)
            ctx.gesture = ""

        # 复合规则：emotion 对 gesture 的限制
        if ctx.gesture:
            allowed = self.EMOTION_GESTURE_RULES.get(ctx.emotion)
            if allowed and ctx.gesture not in allowed:
                fallback = list(allowed)[0]
                logger.info("gesture '%s' not allowed for emotion '%s', corrected to '%s'",
                            ctx.gesture, ctx.emotion, fallback)
                ctx.gesture = fallback

        # 设置最终的 emotion/gesture 为空时的默认值
        if ctx.gesture == "":
            ctx.gesture = None

        logger.info("[%s] after validation: emotion=%s gesture=%s %d chars",
                    ctx.trace_id, ctx.emotion, ctx.gesture, len(ctx.final_text))
        await emit("node.done", name="after",
                   emotion=ctx.emotion, gesture=ctx.gesture, length=len(ctx.final_text))

        return NodeResult(next_node="reflect")
