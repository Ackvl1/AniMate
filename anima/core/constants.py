"""Anima Agent 核心常量 —  emotion/gesture 列表（单一数据源）"""

# ── 情绪列表 ──────────────────────────────────────────────

KNOWN_EMOTIONS: set[str] = {
    "calm", "happy", "sad", "angry", "surprised",
    "confused", "excited", "pleased", "cold",
}

# ── 姿势列表 ──────────────────────────────────────────────

KNOWN_GESTURES: set[str] = {
    "wave", "thinking", "point", "celebrate",
    "nod", "shake", "sigh", "cry", "clap",
    "jump", "dance", "fist", "turn_away", "head_down",
    "stomp", "shrug",
}

# ── emotion → 允许的 gesture 映射 ───────────────────────

EMOTION_GESTURE_RULES: dict[str, set[str]] = {
    "happy": {"celebrate", "clap", "jump", "wave", "dance", "nod"},
    "sad": {"sigh", "cry", "head_down", "shake"},
    "angry": {"fist", "turn_away", "point", "stomp", "shake"},
    "calm": {"nod", "thinking", "wave", "point", "shrug"},
    "pleased": {"celebrate", "clap", "wave", "nod", "dance"},
    "cold": {"turn_away", "point", "stomp", "fist"},
    "surprised": {"jump", "wave"},
    "excited": {"celebrate", "clap", "jump", "dance", "wave"},
    "confused": {"thinking", "shrug", "head_down"},
}

# ── 供 LLM 阅读的 emotion/gesture 说明文本 ──────────────

EMOTION_INSTRUCTION_TEXT = (
    "请以角色身份回复。在句子中自然切换表情/姿势时，使用以下格式嵌入标记：\n\n"
    "(emotion,gesture)回复内容\n\n"
    "示例：\n"
    "(happy,wave)你好！今天真开心呢。\n"
    "(sad,sigh)不过想起上次的事有点难过。\n"
    "(excited,fist)但还是要加油！\n\n"
    f"emotion 可选: {', '.join(sorted(KNOWN_EMOTIONS))}\n"
    f"gesture 可选: {', '.join(sorted(KNOWN_GESTURES))}\n\n"
    "如果全程无需表情切换，可以直接回复纯文本而不使用标记。\n\n"
    "【思考提示】如果需要调用工具，先自然地说一句你在做什么（如'让我查一下天气'），"
    "然后我会自动帮你完成。调用后结合结果继续回复。"
)
