"""受限公式求值器。"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from math import ceil, floor, log

from assetrush.engine.errors import FormulaError
from assetrush.engine.state import Money

FormulaScalar = int | float | bool
FormulaValue = FormulaScalar | tuple["FormulaValue", ...]
FormulaContext = Mapping[str, FormulaValue]
FormulaFunction = Callable[..., FormulaValue]
EffectSpec = Mapping[str, object]


def clamp(value: FormulaScalar, lower: FormulaScalar, upper: FormulaScalar) -> FormulaScalar:
    return max(lower, min(value, upper))


ALLOWED_FUNCS: Mapping[str, FormulaFunction] = {
    "ceil": ceil,
    "clamp": clamp,
    "floor": floor,
    "log": log,
    "max": max,
    "min": min,
    "round": round,
    "sum": sum,
}


def evaluate_formula(formula: str, variables: FormulaContext) -> FormulaValue:
    """安全求值 config 公式。

    只接受 Python expression AST 的白名單節點；不得執行任意程式碼。
    """
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"invalid formula syntax: {formula}") from exc
    return _eval(tree.body, variables)


def resolve_amount(spec: EffectSpec, variables: FormulaContext) -> Money:
    """從 effect spec 取出固定金額或公式金額。"""
    if "amount" in spec:
        return _money_from_value(spec["amount"], "amount")
    for key in ("formula", "amount_formula"):
        value = spec.get(key)
        if isinstance(value, str):
            return _money_from_value(evaluate_formula(value, variables), key)
    raise FormulaError("effect spec must contain amount, formula, or amount_formula")


def _eval(node: ast.AST, variables: FormulaContext) -> FormulaValue:
    if isinstance(node, ast.Constant):
        return _constant(node.value)
    if isinstance(node, ast.Name):
        try:
            return variables[node.id]
        except KeyError as exc:
            raise FormulaError(f"unknown variable: {node.id}") from exc
    if isinstance(node, ast.BinOp):
        return _eval_binop(node, variables)
    if isinstance(node, ast.UnaryOp):
        return _eval_unaryop(node, variables)
    if isinstance(node, ast.Call):
        return _eval_call(node, variables)
    if isinstance(node, ast.Compare):
        return _eval_compare(node, variables)
    if isinstance(node, ast.IfExp):
        condition = _eval(node.test, variables)
        return _eval(node.body if bool(condition) else node.orelse, variables)
    if isinstance(node, ast.Tuple | ast.List):
        return tuple(_eval(element, variables) for element in node.elts)

    raise FormulaError(f"forbidden formula node: {type(node).__name__}")


def _constant(value: object) -> FormulaValue:
    if isinstance(value, bool | int | float):
        return value
    raise FormulaError(f"unsupported constant: {value!r}")


def _eval_binop(node: ast.BinOp, variables: FormulaContext) -> FormulaValue:
    left = _number(_eval(node.left, variables))
    right = _number(_eval(node.right, variables))

    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        return left * right
    if isinstance(node.op, ast.Div):
        return left / right
    if isinstance(node.op, ast.FloorDiv):
        return left // right
    if isinstance(node.op, ast.Mod):
        return left % right
    if isinstance(node.op, ast.Pow):
        return left**right

    raise FormulaError(f"forbidden operator: {type(node.op).__name__}")


def _eval_unaryop(node: ast.UnaryOp, variables: FormulaContext) -> FormulaValue:
    operand = _number(_eval(node.operand, variables))
    if isinstance(node.op, ast.UAdd):
        return +operand
    if isinstance(node.op, ast.USub):
        return -operand
    raise FormulaError(f"forbidden unary operator: {type(node.op).__name__}")


def _eval_call(node: ast.Call, variables: FormulaContext) -> FormulaValue:
    if not isinstance(node.func, ast.Name):
        raise FormulaError("only direct function calls are allowed")
    function = ALLOWED_FUNCS.get(node.func.id)
    if function is None:
        raise FormulaError(f"forbidden function: {node.func.id}")
    if node.keywords:
        raise FormulaError("keyword arguments are not allowed")
    args = [_eval(arg, variables) for arg in node.args]
    return function(*args)


def _eval_compare(node: ast.Compare, variables: FormulaContext) -> FormulaValue:
    left = _number(_eval(node.left, variables))
    for operator, comparator in zip(node.ops, node.comparators, strict=True):
        right = _number(_eval(comparator, variables))
        if isinstance(operator, ast.Lt):
            matched = left < right
        elif isinstance(operator, ast.LtE):
            matched = left <= right
        elif isinstance(operator, ast.Gt):
            matched = left > right
        elif isinstance(operator, ast.GtE):
            matched = left >= right
        elif isinstance(operator, ast.Eq):
            matched = left == right
        elif isinstance(operator, ast.NotEq):
            matched = left != right
        else:
            raise FormulaError(f"forbidden comparator: {type(operator).__name__}")
        if not matched:
            return False
        left = right
    return True


def _number(value: FormulaValue) -> FormulaScalar:
    if isinstance(value, bool | int | float):
        return value
    raise FormulaError(f"expected numeric value, got {value!r}")


def _money_from_value(value: object, source: str) -> Money:
    if isinstance(value, bool):
        raise FormulaError(f"{source} must be numeric")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    raise FormulaError(f"{source} must resolve to a number")
