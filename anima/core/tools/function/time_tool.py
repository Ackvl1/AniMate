"""TimeTool — 获取当前时间的工具"""
from datetime import datetime

from anima.core.tools.base import LocalTool


class TimeTool(LocalTool):
    """获取当前日期和时间。"""
    name = "get_time"
    description = "获取当前日期和时间"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["full", "date", "time"],
                "description": "输出格式：full=完整日期时间，date=仅日期，time=仅时间",
            }
        },
    }

    def execute(self, format: str = "full") -> str:
        now = datetime.now()
        if format == "date":
            return now.strftime("%Y-%m-%d")
        if format == "time":
            return now.strftime("%H:%M:%S")
        return now.strftime("%Y-%m-%d %H:%M:%S")
