"""ToolRegistry — 工具注册中心"""

import os
import tempfile
from datetime import datetime

from animate.core.log import setup_logger
from animate.core.tools.base import LocalTool

logger = setup_logger(__name__)

RESULT_BUDGET_CHARS = 50000  # 每工具输出预算上限（与 Claude Code 主流标准一致）


class ToolRegistry:
    """管理本地工具和 MCP 工具的统一注册中心。"""

    def __init__(self):
        self._handlers: dict[str, callable] = {}
        self._tools: dict[str, LocalTool] = {}  # 工具实例（用于安全属性查询）
        self._schemas: list[dict] = []

    def register(self, name: str, description: str = "", handler: callable = None,
                 parameters: dict | None = None) -> None:
        """注册一个工具。"""
        self._handlers[name] = handler
        self._schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters or {"type": "object", "properties": {}},
            },
        })
        logger.debug("tool registered: %s", name)

    def register_tool(self, tool: LocalTool) -> None:
        """注册一个 LocalTool 子类实例。"""
        schema = tool.to_schema()
        self._handlers[tool.name] = tool.execute
        self._tools[tool.name] = tool  # 保存实例引用（用于安全属性查询）
        self._schemas.append(schema)
        logger.debug("tool registered: %s", tool.name)

    def find(self, name: str) -> LocalTool | None:
        """按名称查找已注册的 LocalTool 实例。"""
        return self._tools.get(name)

    def list_schemas(self) -> list[dict]:
        return list(self._schemas)

    @property
    def names(self) -> list[str]:
        return list(self._handlers.keys())

    def execute(self, name: str, arguments: dict) -> str:
        handler = self._handlers.get(name)
        if not handler:
            msg = f"错误：未找到工具 '{name}'"
            logger.warning(msg)
            return msg
        try:
            result = handler(**arguments)
            result_str = str(result)
            preview = result_str[:50].replace("\n", "\\n")
            logger.info("tool %s executed: %d chars [%s]", name, len(result_str), preview)

            # Result Budgeting：超长输出截断 + 存盘
            if len(result_str) > RESULT_BUDGET_CHARS:
                return self._budget_result(result_str, name)

            return result_str
        except Exception as e:
            logger.error("tool %s failed: %s", name, e)
            return f"工具 '{name}' 执行失败: {e}"

    @staticmethod
    def _budget_result(result_str: str, tool_name: str) -> str:
        """工具输出超预算时截断 + 存盘 + 返回缩略版。"""
        # 保存完整结果到临时目录
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_dir = os.path.join(tempfile.gettempdir(), "animate_tool_results")
        os.makedirs(tmp_dir, exist_ok=True)
        save_path = os.path.join(tmp_dir, f"{tool_name}_{ts}.txt")
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(result_str)
        except OSError:
            save_path = None

        # 截断到预算字符数
        truncated = result_str[:RESULT_BUDGET_CHARS]

        # 追加提示信息
        total = len(result_str)
        if save_path:
            hint = f"\n[完整结果({total}字符)已保存到 {save_path}]"
        else:
            hint = f"\n[完整结果({total}字符，已截断)]"
        truncated += hint

        logger.info("tool %s result budget: %d chars truncated to %d, saved to %s",
                    tool_name, total, RESULT_BUDGET_CHARS, save_path or "(内存)")
        return truncated
