"""Tests for TextMarkerStreamer — inline marker 流式状态机"""

from __future__ import annotations

import pytest
from animate.core.agent.nodes.marker_streamer import TextMarkerStreamer


@pytest.mark.asyncio
async def test_plain_text_no_markers():
    """纯文本直接输出，不产生 emotion.update。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    await streamer.feed("你好世界", emit)
    await streamer.flush(emit)

    assert len(events) == 1
    assert events[0][0] == "text_token"
    assert events[0][1]["text"] == "你好世界"


@pytest.mark.asyncio
async def test_marker_at_start():
    """标记在文本开头。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    await streamer.feed("(happy,wave)你好！", emit)
    await streamer.flush(emit)

    assert len(events) == 2
    assert events[0][0] == "emotion.update"
    assert events[0][1] == {"emotion": "happy", "gesture": "wave"}
    assert events[1][0] == "text_token"
    assert events[1][1]["text"] == "你好！"


@pytest.mark.asyncio
async def test_marker_in_middle():
    """标记在文本中间。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    await streamer.feed("你好。(sad,sigh)不过...", emit)
    await streamer.flush(emit)

    assert len(events) == 3
    assert events[0][0] == "text_token"
    assert events[0][1]["text"] == "你好。"
    assert events[1][0] == "emotion.update"
    assert events[1][1] == {"emotion": "sad", "gesture": "sigh"}
    assert events[2][0] == "text_token"
    assert events[2][1]["text"] == "不过..."


@pytest.mark.asyncio
async def test_multiple_markers():
    """多个标记。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    await streamer.feed("(happy,wave)你好！(sad,sigh)不过...", emit)
    await streamer.flush(emit)

    text_tokens = [e for e in events if e[0] == "text_token"]
    emotion_updates = [e for e in events if e[0] == "emotion.update"]

    assert len(emotion_updates) == 2
    assert emotion_updates[0][1] == {"emotion": "happy", "gesture": "wave"}
    assert emotion_updates[1][1] == {"emotion": "sad", "gesture": "sigh"}
    assert "".join(e[1]["text"] for e in text_tokens) == "你好！不过..."


@pytest.mark.asyncio
async def test_token_boundary_split():
    """标记跨 token 边界。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    await streamer.feed("(happy,", emit)
    await streamer.feed("wave)你好！", emit)
    await streamer.flush(emit)

    assert len(events) == 2
    assert events[0][0] == "emotion.update"
    assert events[0][1] == {"emotion": "happy", "gesture": "wave"}
    assert events[1][0] == "text_token"
    assert events[1][1]["text"] == "你好！"


@pytest.mark.asyncio
async def test_unclosed_marker_at_end():
    """未闭合的标记作为普通文本输出。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    await streamer.feed("你好(", emit)
    await streamer.feed("未完", emit)
    await streamer.flush(emit)

    # unclosed marker should be emitted as text on flush
    assert len(events) >= 1
    combined = "".join(e[1].get("text", "") for e in events if e[0] == "text_token")
    assert "(未完" in combined or "你好(" in combined


@pytest.mark.asyncio
async def test_emotion_only_no_gesture():
    """只有 emotion 没有 gesture。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    await streamer.feed("(happy)你好！", emit)
    await streamer.flush(emit)

    assert events[0][0] == "emotion.update"
    assert events[0][1] == {"emotion": "happy", "gesture": ""}


@pytest.mark.asyncio
async def test_strip_markers():
    """strip_markers 应移除所有标记。"""
    cleaned = TextMarkerStreamer.strip_markers(
        "(happy,wave)你好！(sad,sigh)不过..."
    )
    assert cleaned == "你好！不过..."

    cleaned = TextMarkerStreamer.strip_markers("纯文本")
    assert cleaned == "纯文本"

    cleaned = TextMarkerStreamer.strip_markers("")
    assert cleaned == ""


@pytest.mark.asyncio
async def test_no_marker_only_text():
    """没有标记时只发 text_token。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    for ch in "测试":
        await streamer.feed(ch, emit)
    await streamer.flush(emit)

    combined = "".join(e[1].get("text", "") for e in events if e[0] == "text_token")
    assert combined == "测试"


@pytest.mark.asyncio
async def test_realistic_stream():
    """模拟真实 SSE 流：多个标记 + 跨 token。"""
    streamer = TextMarkerStreamer()
    events = []

    async def emit(type, **data):
        events.append((type, data))

    chunks = [
        "(happy,wa",
        "ve)你好！今天真开心。",
        "(sad,",
        "sigh)不过有点难过。",
        "(excited,fist)加油！",
    ]
    for chunk in chunks:
        await streamer.feed(chunk, emit)
    await streamer.flush(emit)

    emotions = [e[1] for e in events if e[0] == "emotion.update"]
    assert len(emotions) == 3
    assert emotions[0] == {"emotion": "happy", "gesture": "wave"}
    assert emotions[1] == {"emotion": "sad", "gesture": "sigh"}
    assert emotions[2] == {"emotion": "excited", "gesture": "fist"}

    texts = [e[1].get("text", "") for e in events if e[0] == "text_token"]
    full_text = "".join(texts)
    assert "你好！今天真开心。" in full_text
    assert "不过有点难过。" in full_text
    assert "加油！" in full_text
