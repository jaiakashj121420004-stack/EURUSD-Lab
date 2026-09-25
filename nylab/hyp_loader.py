"""nylab.hyp_loader -- load hypothesis YAML files (ARCHITECTURE.md S5, ROADMAP 3.1/3.3).

"The hypothesis loader rejects a hypothesis whose condition uses a column with
available_at_h > decision_time_h" (RESEARCH_PROTOCOL.md S3) -- that check happens HERE, at
load time, not buried inside the stats engine, so a look-ahead bug in a hypothesis file fails
loudly the moment it's loaded, before it can ever produce a number.

Only `condition` is checked against decision_time_h. `outcome` and `baseline` describe the
FUTURE result being tested (e.g. `ny_drive` at available_at_h=16 for a decision_time_h=9.5
hypothesis) -- that's the whole point of a hypothesis, not a leak.
"""
from __future__ import annotations

import dataclasses
import glob
import os

import yaml

from nylab import config as _cfg
from nylab import hyp_dsl
from nylab import sessions as _sessions_mod
from nylab.days import COLUMN_DOCS

# ROADMAP 5.4: a hypothesis's condition may reference a SESSION-table column (`lon.character`,
# `nyam_kz.character`, ...). Those columns only exist in COLUMN_DOCS once nylab.sessions has
# registered them -- days.py itself can't do this merge (nylab.sessions imports days.window()/
# first_cross(), so days importing sessions back would be a cycle), and cmd_run's own merge in
# nylab/__main__.py only runs once `nylab run` actually executes, which is too late for a
# hypothesis loaded/validated in isolation (a test, `nylab hypothesis add`, a future `nylab
# hypothesis check`). So this module -- which every one of those paths already imports before
# touching a hypothesis file -- does the merge itself, once, at import time.
COLUMN_DOCS.update(_sessions_mod.column_docs(_cfg.sessions()))


class HypothesisLoadError(ValueError):
    pass


@dataclasses.dataclass
class Hypothesis:
    id: str
    version: str
    title: str
    decision_time_h: float
    condition: str
    outcome: str
    baseline: str | None = None
    baseline_p0: float | None = None  # a literal null-rate override, see H015's notes
    min_n: int = 0
    family: str | None = None
    codex_ref: str = ""
    notes: str = ""
    matrix_shape: tuple[int, int] | None = None  # ROADMAP 5.4: [rows, cols] if this hypothesis
    # was promoted from a nylab.cross_session transition matrix -- see nylab/ledger.py's
    # docstring. None (the default) means an ordinary, non-matrix hypothesis (weight 1 in m).


def _check_lookahead(hyp_id: str, condition: str, decision_time_h: float) -> None:
    tree = hyp_dsl.parse(condition)
    hyp_dsl.validate(tree)
    for col in hyp_dsl.referenced_columns(tree):
        avail = COLUMN_DOCS.get(col)
        if avail is not None and avail > decision_time_h:
            raise HypothesisLoadError(
                f"{hyp_id}: condition {condition!r} uses column '{col}' (available_at_h={avail}) "
                f"but decision_time_h={decision_time_h} -- this would leak the future. Either fix "
                f"the condition or move decision_time_h to >= {avail}."
            )


def load_one(path: str) -> Hypothesis:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    for key in ("id", "decision_time_h", "condition", "outcome"):
        if key not in raw:
            raise HypothesisLoadError(f"{path}: missing required field '{key}'")
    if "baseline" not in raw and "baseline_p0" not in raw:
        raise HypothesisLoadError(f"{path}: needs either 'baseline' (an expression) or 'baseline_p0' (a literal)")

    matrix_shape = raw.get("matrix_shape")
    if matrix_shape is not None:
        if (not isinstance(matrix_shape, (list, tuple)) or len(matrix_shape) != 2
                or any(int(x) <= 0 for x in matrix_shape)):
            raise HypothesisLoadError(
                f"{path}: matrix_shape must be [rows, cols] of positive integers, got {matrix_shape!r}"
            )
        matrix_shape = (int(matrix_shape[0]), int(matrix_shape[1]))

    hyp = Hypothesis(
        id=str(raw["id"]), version=str(raw.get("version", "1.0")), title=raw.get("title", raw["id"]),
        decision_time_h=float(raw["decision_time_h"]), condition=str(raw["condition"]),
        outcome=str(raw["outcome"]), baseline=raw.get("baseline"),
        baseline_p0=(float(raw["baseline_p0"]) if raw.get("baseline_p0") is not None else None),
        min_n=int(raw.get("min_n", 0)), family=raw.get("family"),
        codex_ref=raw.get("codex_ref", ""), notes=raw.get("notes", ""),
        matrix_shape=matrix_shape,
    )

    # Parse + whitelist-validate every expression up front (never look-ahead-checked for
    # outcome/baseline -- see module docstring).
    hyp_dsl.validate(hyp_dsl.parse(hyp.condition))
    hyp_dsl.validate(hyp_dsl.parse(hyp.outcome))
    if hyp.baseline is not None:
        hyp_dsl.validate(hyp_dsl.parse(hyp.baseline))
    _check_lookahead(hyp.id, hyp.condition, hyp.decision_time_h)
    return hyp


def load_all(directory: str = "config/hypotheses") -> list[Hypothesis]:
    paths = sorted(glob.glob(os.path.join(directory, "*.yaml")))
    if not paths:
        raise HypothesisLoadError(f"no hypothesis YAML files found in {directory}/")
    return [load_one(p) for p in paths]
