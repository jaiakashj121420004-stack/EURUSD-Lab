"""nylab.hyp_dsl -- the safe hypothesis-condition DSL (ARCHITECTURE.md S5, ROADMAP 3.1).

"The DSL is a whitelist evaluator (column names, numbers, and/or/not, comparisons, abs,
quantile(col, q), median(col)) -- never eval raw strings." This module never calls Python's
eval()/exec() on anything: it parses the expression into an ast.Expression (parsing is inert --
it does not run code) and then walks that tree BY HAND with its own recursive evaluator, so
there is no path from a hypothesis YAML file to arbitrary Python execution, no matter what
someone writes into `condition`/`outcome`/`baseline`.

Dotted convenience syntax ("day.x", "lon.x", "<session>.x") is supported by a text-level
rewrite BEFORE parsing: `name.attr` -> `name_attr`, which is exactly the day-table's own column
naming convention (lon_high, asia_range, ...). Plain flat column names (as used throughout
ARCHITECTURE.md's own example, e.g. "pre_takes_lon_high") pass through untouched.
"""
from __future__ import annotations

import ast
import operator
import re

import pandas as pd

_DOT_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\.([A-Za-z_]\w*)(?![\w.])")

_CMP_OPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
    ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
}
_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_ALLOWED_FUNCS = ("abs", "quantile", "median")

# Every AST node type this DSL is willing to walk. Anything else (Attribute, Subscript,
# Lambda, comprehensions, Call with a non-whitelisted func, ...) is rejected at validate()
# time, before evaluation ever runs.
_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Name, ast.Load, ast.Constant, ast.Call,
)


class DSLError(ValueError):
    """Raised for anything the safe evaluator refuses to parse, validate, or run."""


def preprocess_dots(expr: str) -> str:
    """`day.open` -> `day_open`. Never touches numeric literals like `0.2` (the regex requires
    a letter/underscore, not a digit, on both sides of the dot)."""
    return _DOT_RE.sub(r"\1_\2", expr)


def parse(expr: str) -> ast.Expression:
    try:
        return ast.parse(preprocess_dots(expr), mode="eval")
    except SyntaxError as e:
        raise DSLError(f"could not parse expression {expr!r}: {e}") from e


def validate(tree: ast.Expression) -> None:
    """Walks the WHOLE tree and raises DSLError on the first disallowed node. Call this before
    evaluate() on any expression sourced from a file, so a bad hypothesis YAML fails loudly at
    load time rather than at eval time (or, worse, not at all)."""
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise DSLError(f"disallowed expression element: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise DSLError(f"disallowed function call -- only {_ALLOWED_FUNCS} are allowed")


def referenced_columns(tree: ast.Expression) -> set[str]:
    """Every Name used as a DATA reference (i.e. NOT as the function part of a whitelisted
    Call) -- used by nylab.hyp_loader to check available_at_h for look-ahead (RESEARCH_PROTOCOL
    S3)."""
    call_func_ids = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and id(n) not in call_func_ids}


def _eval(node, ns: dict):
    if isinstance(node, ast.Expression):
        return _eval(node.body, ns)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in ns:
            raise DSLError(f"unknown column or name: {node.id!r}")
        return ns[node.id]
    if isinstance(node, ast.UnaryOp):
        val = _eval(node.operand, ns)
        if isinstance(node.op, ast.Not):
            return (not val) if isinstance(val, bool) else ~val
        if isinstance(node.op, ast.USub):
            return -val
        raise DSLError("unsupported unary operator")
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, ns) for v in node.values]
        op = operator.and_ if isinstance(node.op, ast.And) else operator.or_
        result = vals[0]
        for v in vals[1:]:
            result = op(result, v)
        return result
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN_OPS:
            raise DSLError("unsupported binary operator")
        return _BIN_OPS[type(node.op)](_eval(node.left, ns), _eval(node.right, ns))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ns)
        result = None
        for op_node, comparator in zip(node.ops, node.comparators):
            if type(op_node) not in _CMP_OPS:
                raise DSLError("unsupported comparison operator")
            right = _eval(comparator, ns)
            piece = _CMP_OPS[type(op_node)](left, right)
            result = piece if result is None else (result & piece)
            left = right
        return result
    if isinstance(node, ast.Call):
        fname = node.func.id
        args = [_eval(a, ns) for a in node.args]
        if fname == "abs":
            return args[0].abs() if isinstance(args[0], (pd.Series,)) else abs(args[0])
        if fname == "quantile":
            return args[0].quantile(args[1])
        if fname == "median":
            return args[0].median()
        raise DSLError(f"unsupported function: {fname}")
    raise DSLError(f"disallowed expression element: {type(node).__name__}")


def evaluate(expr: str, ns: dict):
    """Parse + validate + evaluate `expr` against namespace `ns` (usually {column_name:
    pd.Series}). Raises DSLError on anything outside the whitelist -- callers that already
    called validate() at load time will not normally hit this, but evaluate() enforces it
    itself too, so there is no way to skip validation and still get arbitrary execution."""
    tree = parse(expr)
    validate(tree)
    return _eval(tree, ns)
