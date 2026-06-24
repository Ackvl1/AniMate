"""Agent 相关的异常定义"""


class AgentError(Exception):
    """Agent 基类异常。"""


class LLMError(AgentError):
    """LLM 调用异常。"""


class ToolError(AgentError):
    """工具执行异常。"""
