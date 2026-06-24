from abc import ABC, abstractmethod
from animate.core.agent.response import AgentResponse

class InputAdapter(ABC):
    @abstractmethod
    def receive(self) -> str:
        """阻塞等待用户输入，返回文本。"""

class OutputAdapter(ABC):
    @abstractmethod
    def send(self, response: AgentResponse) -> None:
        """将 Agent 回复呈现给用户。"""