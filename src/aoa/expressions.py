"""Safe arithmetic expressions for objectives and constraints (never eval user code)."""

from __future__ import annotations

import ast
import math
from typing import Any


class ExpressionError(ValueError):
    """Raised when an expression is not in the supported arithmetic subset."""


_BINARY = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.Pow: lambda left, right: left**right,
    ast.Mod: lambda left, right: left % right,
}
_UNARY = {ast.UAdd: lambda value: value, ast.USub: lambda value: -value}
_FUNCTIONS = {
    "abs": abs,
    "sqrt": math.sqrt,
    "log": math.log,
    "exp": math.exp,
    "min": min,
    "max": max,
}


def _parse(expression: str) -> ast.Expression:
    if len(expression) > 200:
        raise ExpressionError("Expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ExpressionError("Expression syntax is invalid") from error
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ExpressionError("Expression is too complex")
    return tree


def validate_expression(expression: str, allowed_names: set[str]) -> None:
    tree = _parse(expression)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in allowed_names and node.id not in _FUNCTIONS:
            raise ExpressionError(f"Unknown name in expression: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise ExpressionError("Only abs, sqrt, log, exp, min, and max calls are allowed")
            if node.keywords:
                raise ExpressionError("Keyword arguments are not supported")
        elif isinstance(node, ast.BinOp) and type(node.op) not in _BINARY:
            raise ExpressionError("This arithmetic operator is not supported")
        elif isinstance(node, ast.UnaryOp) and type(node.op) not in _UNARY:
            raise ExpressionError("This unary operator is not supported")
        elif isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ExpressionError("Only numeric constants are allowed")
        elif not isinstance(
            node,
            (ast.Expression, ast.Load, ast.Name, ast.Call, ast.BinOp, ast.UnaryOp, ast.Constant, *tuple(_BINARY), *tuple(_UNARY)),
        ):
            raise ExpressionError("Expression contains an unsupported construct")


def evaluate_expression(expression: str, values: dict[str, float]) -> float:
    tree = _parse(expression)

    def visit(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in values:
                return float(values[node.id])
            raise ExpressionError(f"Unknown value in expression: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = float(visit(node.left)), float(visit(node.right))
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ExpressionError("Exponents must be between -12 and 12")
            return _BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](float(visit(node.operand)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
            args = [float(visit(argument)) for argument in node.args]
            if not args or (node.func.id in {"abs", "sqrt", "log", "exp"} and len(args) != 1):
                raise ExpressionError(f"Invalid number of arguments for {node.func.id}")
            return _FUNCTIONS[node.func.id](*args)
        raise ExpressionError("Expression contains an unsupported construct")

    try:
        result = float(visit(tree))
    except (ArithmeticError, OverflowError, ValueError) as error:
        raise ExpressionError(f"Could not evaluate expression: {error}") from error
    if not math.isfinite(result):
        raise ExpressionError("Expression returned a non-finite number")
    return result
