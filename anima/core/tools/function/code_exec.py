"""ExecutePythonTool — 执行 Python 代码（subprocess 隔离）"""
import subprocess
import sys
import traceback

from anima.core.tools.base import LocalTool


class ExecutePythonTool(LocalTool):
    """执行 Python 代码并返回输出。"""
    name = "execute_python"
    description = "执行一段 Python 代码，返回 stdout 输出。适合数据分析、计算、文件操作等"
    is_read_only = False
    is_parallel_safe = False
    is_destructive = True
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的 Python 代码",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数（默认 10）",
            },
        },
        "required": ["code"],
    }

    def execute(self, code: str, timeout: int = 10) -> str:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            result = ""
            if proc.stdout:
                result += f"输出:\n{proc.stdout}"
            if proc.stderr:
                result += f"错误:\n{proc.stderr}"
            if not result.strip():
                result = "(代码执行完毕，无输出)"
            if proc.returncode != 0 and not proc.stderr:
                result += f"\n退出码: {proc.returncode}"
            return result.strip()
        except subprocess.TimeoutExpired:
            return f"执行超时（{timeout}秒），进程已终止"
        except Exception as e:
            return f"执行失败:\n{traceback.format_exc()}"
