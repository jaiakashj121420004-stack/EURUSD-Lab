"""nylab.ledger -- the append-only multiple-testing ledger (RESEARCH_PROTOCOL.md S4, ROADMAP 3.4/3.5).

`m` = the number of tests EVER evaluated, including ones later killed. For an ordinary
hypothesis that's 1 per distinct (id, version); re-running an unchanged hypothesis does NOT
increase m; changing its definition (which must bump `version`) does. `research/ledger.csv` is
append-only: this module never rewrites or drops an existing row, only adds new ones.

ROADMAP 5.4 / SESSIONS_AND_CONTEXT.md S5.2's matrix-family rule changes the WEIGHT, not this
principle: a hypothesis promoted from a cross-session transition matrix (nylab.cross_session)
carries `matrix_shape: [rows, cols]` in its YAML (see nylab.hyp_loader), and counts as
rows*cols distinct tests toward m, not 1 -- "once you pick a cell because it looked extreme,
you must count every cell of that matrix as tested". The `matrix_cells` ledger column records
that weight per (id, version) pair. A pre-5.4 ledger.csv has no such column; append() migrates
it in place ONCE (adding matrix_cells=1 to every existing row, matching what those rows always
implicitly meant) the first time a new row is appended -- still never changing any row's
existing recorded values, only widening the schema forward. distinct_m() also tolerates reading
a file that hasn't been migrated yet (defaults missing weights to 1).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

LEDGER_COLUMNS = ["run_id", "timestamp", "kind", "id", "version", "n", "stat", "p",
                   "is_metric", "oos_metric", "verdict", "notes", "matrix_cells"]

DEFAULT_PATH = "research/ledger.csv"


def load(path: str = DEFAULT_PATH) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    return pd.read_csv(path)


def _migrate_matrix_cells_column(path: str) -> None:
    """One-time, in-place schema widen for a ledger.csv written before ROADMAP 5.4: adds
    matrix_cells=1 to every existing row (their tests always implicitly counted as 1 cell each)
    so the file has a single consistent column count going forward. Never touches any other
    value in any existing row -- see module docstring."""
    if not os.path.exists(path):
        return
    existing = pd.read_csv(path)
    if "matrix_cells" in existing.columns:
        return
    existing["matrix_cells"] = 1
    existing.to_csv(path, index=False)


def append(rows: list[dict], path: str = DEFAULT_PATH) -> None:
    """Append-only: never rewrites or drops an existing row's VALUES, only adds new ones on the
    end (see _migrate_matrix_cells_column for the one allowed schema-widening exception)."""
    if not rows:
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _migrate_matrix_cells_column(path)
    df = pd.DataFrame(rows, columns=LEDGER_COLUMNS)
    df["matrix_cells"] = df["matrix_cells"].fillna(1).astype(int)
    header = not os.path.exists(path)
    df.to_csv(path, mode="a", header=header, index=False)


def distinct_m(path: str = DEFAULT_PATH, extra_ids=None) -> int:
    """m = the sum of matrix_cells weights over distinct (id, version) pairs already on the
    ledger, plus any pairs in `extra_ids` not yet on disk -- so a run can compute its OWN m
    (for Bonferroni) before it appends its own rows, counting itself exactly once.

    `extra_ids` accepts either 2-tuples `(id, version)` (weight defaults to 1, the pre-5.4
    shape) or 3-tuples `(id, version, matrix_cells)` for a matrix-family hypothesis."""
    existing = load(path)
    weights: dict[tuple[str, str], int] = {}
    if len(existing):
        mc = existing["matrix_cells"] if "matrix_cells" in existing.columns else pd.Series(1, index=existing.index)
        mc = mc.fillna(1).astype(int)
        for i, v, w in zip(existing.get("id", pd.Series(dtype=str)).astype(str),
                            existing.get("version", pd.Series(dtype=str)).astype(str), mc):
            weights[(i, v)] = int(w)
    if extra_ids:
        for item in extra_ids:
            if len(item) == 3:
                i, v, w = item
            else:
                i, v = item
                w = 1
            weights[(str(i), str(v))] = int(w)
    return sum(weights.values())


def bonferroni_alpha(m: int, alpha: float = 0.05) -> float:
    """RESEARCH_PROTOCOL S4: 'strict' correction, p < 0.05/m."""
    return alpha / m if m else alpha


def bh_significant(pvals, q: float = 0.10) -> np.ndarray:
    """Benjamini-Hochberg step-up FDR procedure at level `q` (RESEARCH_PROTOCOL S4: 'lenient,
    for triage', default 10%). Returns a boolean array in the SAME order as `pvals`. A NaN
    p-value (an n=0 hypothesis has nothing to test) is never significant."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    if n == 0:
        return np.zeros(0, dtype=bool)
    safe = np.where(np.isnan(p), np.inf, p)
    order = np.argsort(safe, kind="stable")
    ranked = safe[order]
    thresh = (np.arange(1, n + 1) / n) * q
    passed = ranked <= thresh
    sig_sorted = np.zeros(n, dtype=bool)
    if passed.any():
        k_max = int(np.max(np.where(passed)[0]))
        sig_sorted[: k_max + 1] = True
    sig = np.zeros(n, dtype=bool)
    sig[order] = sig_sorted
    return sig
