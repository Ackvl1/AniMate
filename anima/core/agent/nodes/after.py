"""AfterNode — 校验 emotion/gesture + 应用复合规则（inline marker 版）

ReactNode 已通过 TextMarkerStreamer 实时处理了 (emotion,gesture) 标记并设置了
ctx.emotion/ctx.gesture/ctx.raw_text。AfterNode 只做最终校验和复合规则应用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from anima.core.engine.node import Node, NodeResult
from anima.core.log import setup_logger
from anima.core.constants import KNOWN_EMOTIONS, KNOWN_GESTURES, EMOTION_GESTURE_RULES

if TYPE_CHECKING:
    from anima.core.engine.context import RunContext

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

    reads = {"raw_text", "emotion", "gesture"}
    writes = {"final_text", "emotion", "gesture"}

    async def run(self, ctx: "RunContext", emit) -> NodeResult:
        await emit("node.start", name="after")
        text = ctx.raw_text.strip()
        if not text:
            await emit("emotion.final", value="calm")
            await emit("gesture.final", value=None)
            await emit("node.done", name="after", emotion="calm", gesture=None, length=0)
            return NodeResult(diff={"final_text": "", "emotion": "calm", "gesture": None})

        # 备份清理：如果 LLM 没按 inline marker 格式输出，raw_text 可能含残留标记
        from anima.core.agent.nodes.marker_streamer import TextMarkerStreamer
        cleaned = TextMarkerStreamer.strip_markers(text)

        # 校验 emotion
        emotion = ctx.emotion
        if emotion and emotion not in self.KNOWN_EMOTIONS:
            logger.info("unknown emotion '%s', fallback to calm", emotion)
            emotion = "calm"
        if not emotion:
            emotion = "calm"

        # 校验 gesture
        gesture = ctx.gesture
        if gesture and gesture not in self.KNOWN_GESTURES:
            logger.info("unknown gesture '%s', removed", gesture)
            gesture = ""

        # 复合规则：emotion 对 gesture 的限制
        if gesture:
            allowed = self.EMOTION_GESTURE_RULES.get(emotion)
            if allowed and gesture not in allowed:
                fallback = list(allowed)[0]
                logger.info("gesture '%s' not allowed for emotion '%s', corrected to '%s'",
                            gesture, emotion, fallback)
                gesture = fallback

        # 设置最终的 emotion/gesture 为空时的默认值
        if gesture == "":
            gesture = None

        await emit("emotion.final", value=emotion)
        await emit("gesture.final", value=gesture)
        logger.info("[%s] after validation: emotion=%s gesture=%s %d chars",
                    ctx.trace_id, emotion, gesture, len(cleaned))
        await emit("node.done", name="after",
                   emotion=emotion, gesture=gesture, length=len(cleaned))

        return NodeResult(
            diff={"final_text": cleaned, "emotion": emotion, "gesture": gesture},
        )
