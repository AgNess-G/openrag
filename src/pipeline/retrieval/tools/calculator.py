"""LangChain tool: safe mathematical expression evaluator."""

from __future__ import annotations

import ast
import operator

from langchain_core.tools import BaseTool

# Safe operators only
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expr: str) -> float:
    """Evaluate a mathematical expression safely using AST."""
    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            op_fn = _SAFE_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op_fn(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op_fn = _SAFE_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op_fn(_eval(node.operand))
        raise ValueError(f"Unsupported expression type: {type(node).__name__}")

    tree = ast.parse(expr.strip(), mode="eval")
    return _eval(tree.body)


class CalculatorTool(BaseTool):
    name: str = "calculator"
    description: str = (
        "Evaluate mathematical expressions safely. "
        "Use for arithmetic, estimates, totals, comparisons, and projections. "
        "Input: a mathematical expression string, e.g. '2 * (3 + 4)' or '100 / 3.5'."
    )

    def _run(self, expression: str) -> str:
        try:
            result = _safe_eval(expression)
            return str(result)
        except Exception as e:
            return f"Error evaluating expression '{expression}': {e}"

    async def _arun(self, expression: str) -> str:
        return self._run(expression)
