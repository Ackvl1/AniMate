"""AgentResponse, ReflectionSignal — Agent 的最终输出和 Reflection 信号"""

from dataclasses import dataclass, field


@dataclass
class AgentResponse:
    """Agent.chat() 的最终输出。"""
    text: str = ""
    emotion: str = ""
    gesture: str | None = None


@dataclass
class ReflectionSignal:
    """Reflection Phase 的评估信号。"""
    level: int = 0
    feedback: str = ""

    @property
    def needs_retry(self) -> bool:
        return self.level >= 3
