from __future__ import annotations

import sys

from animate.io.IOBase import InputAdapter, OutputAdapter
from animate.core.agent.response import AgentResponse

DEFAULT_EMOTION_ICONS = {
    "calm": "😶", "pleased": "🌸", "cold": "❄️",
    "happy": "😊", "sad": "😢", "angry": "😠",
    "surprised": "😲", "confused": "🤔", "excited": "🎉",
    "proud": "😏", "worried": "😟", "shy": "🥺",
    "grateful": "🙏", "annoyed": "😤", "hopeful": "✨",
    "lonely": "🥀", "curious": "🤨", "analytical": "🧐",
}


class ConsoleInput(InputAdapter):
    def __init__(self, prompt: str = "> "):
        self._prompt = prompt

    def receive(self) -> str:
        try:
            return input(self._prompt)
        except EOFError:
            print("\n[输入已关闭]")
            return ""


class ConsoleOutput(OutputAdapter):
    def __init__(self, character_name: str = "Saki",
                 emotion_icons: dict | None = None):
        self._character_name = character_name
        self._emotion_icons = (emotion_icons
                               if emotion_icons is not None
                               else DEFAULT_EMOTION_ICONS.copy())
        self._streaming = False

    def send(self, response: AgentResponse) -> None:
        icon = self._emotion_icons.get(response.emotion, "😶")
        print(f"{self._character_name} {icon}:{response.text}")

    def stream_start(self, emotion: str = "calm") -> None:
        """开始流式输出，打印角色名+表情图标，不换行。"""
        icon = self._emotion_icons.get(emotion, "😶")
        print(f"{self._character_name} {icon}:", end="", flush=True)
        self._streaming = True

    def stream_token(self, token: str) -> None:
        """流式输出一个 token（不换行）。"""
        if not self._streaming:
            return
        print(token, end="", flush=True)

    def stream_end(self) -> None:
        """结束流式输出，换行。"""
        if self._streaming:
            print()
            self._streaming = False
