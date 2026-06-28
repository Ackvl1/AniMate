"""TextMarkerStreamer — inline (emotion,gesture) 标记的流式解析状态机。

将 LLM 的 SSE 流中形如 (happy,wave)的标记解析为 emotion.update 事件，
其余纯文本逐字发射为 text_token 事件。支持跨 token 边界的标记切分。
"""

from __future__ import annotations


class TextMarkerStreamer:
    """状态机：在流式文本中检测并解析 (emotion,gesture) 标记。

    用法：
        streamer = TextMarkerStreamer()
        for chunk in llm_stream:
            await streamer.feed(chunk, emit_fn)
        await streamer.flush(emit_fn)

    发射的事件：
        - ("text_token", {"text": "..."}) — 纯文本片段
        - ("emotion.update", {"emotion": "...", "gesture": "..."}) — 标记解析
    """

    def __init__(self):
        self._buffer = ""
        self._in_marker = False
        self._marker_buf = ""

    async def feed(self, chunk: str, emit_fn) -> None:
        """处理一个流式 chunk，发射解析出的 text_token 和 emotion.update 事件。"""
        self._buffer += chunk
        await self._process(emit_fn)

    async def flush(self, emit_fn) -> None:
        """流结束时刷新剩余内容。

        - 未闭合的标记 → 作为普通文本发射
        - 残留的 text_buf → 发射为 text_token
        """
        if self._in_marker:
            # 未闭合的标记：将标记前缀作为普通文本发射
            await emit_fn("text_token", text="(" + self._marker_buf)
        elif self._buffer:
            await emit_fn("text_token", text=self._buffer)
        self._buffer = ""
        self._marker_buf = ""
        self._in_marker = False

    async def _process(self, emit_fn) -> None:
        """处理缓冲区中的全部内容。使用 find 定位标记边界。"""
        while self._buffer:
            if not self._in_marker:
                # 找下一个 (
                idx = self._buffer.find("(")
                if idx == -1:
                    # 无标记，整段发射为文本
                    await emit_fn("text_token", text=self._buffer)
                    self._buffer = ""
                    break
                if idx > 0:
                    # ( 之前的纯文本先发射
                    await emit_fn("text_token", text=self._buffer[:idx])
                # 进入标记模式，剥离 (
                self._in_marker = True
                self._marker_buf = ""
                self._buffer = self._buffer[idx + 1:]
                # 继续循环处理标记内容
            else:
                # 在标记内，找 )
                idx = self._buffer.find(")")
                if idx == -1:
                    # 尚未闭合，累积到 marker_buf
                    self._marker_buf += self._buffer
                    self._buffer = ""
                    break
                # 找到 )：解析标记
                self._marker_buf += self._buffer[:idx]
                emotion, gesture = self._parse_marker(self._marker_buf)
                await emit_fn("emotion.update", emotion=emotion, gesture=gesture)
                self._in_marker = False
                self._marker_buf = ""
                self._buffer = self._buffer[idx + 1:]  # 剥离 ) 后的部分继续循环

    @staticmethod
    def _parse_marker(raw: str) -> tuple[str, str]:
        """解析标记内容。"""
        parts = [p.strip() for p in raw.split(",")]
        emotion = parts[0] if parts else "calm"
        gesture = parts[1] if len(parts) > 1 else ""
        return emotion, gesture

    @staticmethod
    def strip_markers(text: str) -> str:
        """从完整文本中仅剥离 (emotion,gesture) 格式标记，保留正常括号文本。"""
        import re
        # 匹配 (单词,单词) 格式，其中单词由字母/数字/下划线组成
        return re.sub(r"\(\s*(\w+)\s*,\s*(\w+)\s*\)", "", text).strip()
