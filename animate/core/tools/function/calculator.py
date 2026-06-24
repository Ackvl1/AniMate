"""CalculatorTool — 数学计算器"""
import ast
import operator
from typing import Any

from animate.core.tools.base import LocalTool


class CalculatorTool(LocalTool):
    """计算数学表达式。支持加减乘除、幂运算等。"""
    name = "calculator"
    description = "计算数学表达式，返回计算结果。支持 + - * / ** // % 等运算符"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "数学表达式，如 '2 + 3 * 4'",
            }
        },
        "required": ["expression"],
    }

    # 安全运算白名单
    _OPERATORS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def execute(self, expression: str) -> str:
        try:
            result = self._safe_eval(expression)
            return str(result)
        except Exception as e:
            return f"计算错误: {e}"

    def _safe_eval(self, expr: str) -> Any:
        tree = ast.parse(expr.strip(), mode="eval")
        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.UnaryOp):
            op = self._OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的操作符: {type(node.op).__name__}")
            return op(self._eval_node(node.operand))
        if isinstance(node, ast.BinOp):
            op = self._OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的操作符: {type(node.op).__name__}")
            return op(self._eval_node(node.left), self._eval_node(node.right))
        raise ValueError(f"不支持的表达式: {type(node).__name__}")
