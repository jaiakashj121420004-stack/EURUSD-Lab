"""nylab.hyp_dsl -- the safe hypothesis-condition evaluator (ARCHITECTURE.md S5, ROADMAP 3.1).
Covers: dotted-access translation, correct boolean/comparison semantics against a real day
table, and -- the whole point of "safe" -- that it refuses anything outside its whitelist
rather than silently running it.
"""
import pandas as pd
import pytest

from nylab.hyp_dsl import DSLError, evaluate, parse, preprocess_dots, referenced_columns, validate


def test_dotted_access_translates_to_flat_column_names():
    assert preprocess_dots("day.open") == "day_open"
    assert preprocess_dots("lon.high") == "lon_high"
    assert preprocess_dots("pre_takes_lon_high") == "pre_takes_lon_high"  # already flat, untouched


def test_dotted_access_never_touches_numeric_literals():
    # "0.2" must stay "0.2" -- the dot-rewrite requires a letter/underscore on both sides.
    assert preprocess_dots("asia_range < quantile(asia_range, 0.2)") == "asia_range < quantile(asia_range, 0.2)"


def test_evaluate_flat_and_dotted_forms_agree():
    ns = {"lon_high": pd.Series([1.1, 1.2, 1.3]), "lon_low": pd.Series([1.0, 1.05, 1.1])}
    flat = evaluate("lon_high > lon_low", ns)
    dotted = evaluate("lon.high > lon.low", ns)
    assert (flat == dotted).all()
    assert flat.tolist() == [True, True, True]


def test_boolean_and_not_operators():
    ns = {"a": pd.Series([True, True, False, False]), "b": pd.Series([True, False, True, False])}
    assert evaluate("a and not b", ns).tolist() == [False, True, False, False]
    assert evaluate("a or b", ns).tolist() == [True, True, True, False]


def test_quantile_and_median_functions():
    ns = {"x": pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])}
    assert evaluate("x > median(x)", ns).tolist() == [False, False, False, True, True]
    lo = evaluate("quantile(x, 0.0)", ns)
    assert lo == 1.0


@pytest.mark.parametrize("bad_expr", [
    "__import__('os').system('echo hi')",
    "os.system('echo hi')",
    "(lambda: 1)()",
    "[x for x in range(3)]",
    "open('/etc/passwd')",
    "eval('1+1')",
])
def test_disallowed_expressions_are_rejected(bad_expr):
    with pytest.raises(DSLError):
        tree = parse(bad_expr)
        validate(tree)


def test_attribute_access_is_neutralized_not_exploitable():
    """`a.__class__` never reaches ast.Attribute at all -- the dot-rewrite turns it into the
    single flat identifier `a___class__` first, which then just fails as an unknown column at
    evaluate() time. Confirms there is no attribute-access escape hatch through the dot
    convenience syntax, even though validate() alone (which only checks node SHAPES, not
    whether a Name actually resolves) doesn't reject it."""
    with pytest.raises(DSLError):
        evaluate("a.__class__", {"a": pd.Series([1, 2, 3])})


def test_disallowed_function_call_is_rejected():
    with pytest.raises(DSLError):
        validate(parse("len(x)"))


def test_unknown_column_name_is_rejected_at_eval_time():
    with pytest.raises(DSLError):
        evaluate("nonexistent_column > 0", {"x": pd.Series([1])})


def test_referenced_columns_excludes_function_names():
    tree = parse("asia_range < quantile(asia_range, 0.2)")
    validate(tree)
    assert referenced_columns(tree) == {"asia_range"}


def test_referenced_columns_with_dotted_syntax():
    tree = parse("pre_takes_lon_high and not lon.dir > 0")
    cols = referenced_columns(tree)
    assert "pre_takes_lon_high" in cols
    assert "lon_dir" in cols
