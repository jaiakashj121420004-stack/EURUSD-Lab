"""nylab.ledger -- the append-only multiple-testing ledger (RESEARCH_PROTOCOL.md S4, ROADMAP 3.4/3.5).

`m` = number of distinct (id, version) rows EVER evaluated, including ones later killed.
Re-running an unchanged hypothesis does NOT increase m; changing its definition (which must
bump `version`) does. `research/ledger.csv` is append-only: this module never rewrites or
drops an existing row, only adds new ones.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

LEDGER_COLUMNS = ["run_id", "timestamp", "kind", "id", "version", "n", "stat", "p",
                   "is_metric", "oos_metric", "verdict", "notes"]

DEFAULT_PATH = "research/ledger.csv"


def load(path: str = DEFAULT_PATH) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    return pd.read_csv(path)


def append(rows: list[dict], path: str = DEFAULT_PATH) -> None:
    """Append-only: never rewrites or drops an existing row, only adds new ones on the end."""
    if not rows:
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    df = pd.DataFrame(rows, columns=LEDGER_COLUMNS)
    header = not os.path.exists(path)
    df.to_csv(path, mode="a", header=header, index=False)


def distinct_m(path: str = DEFAULT_PATH, extra_ids: list[tuple[str, str]] | None = None) -> int:
    """m = count of distinct (id, version) pairs already on the ledger, plus any pairs in
    `extra_ids` not yet on disk -- so a run can compute its OWN m (for Bonferroni) before it
    appends its own rows, counting itself exactly once."""
    existing = load(path)
    pairs = set(zip(existing.get("id", pd.Series(dtype=str)).astype(str),
                     existing.get("version", pd.Series(dtype=str)).astype(str)))
    if extra_ids:
        pairs |= {(str(i), str(v)) for i, v in extra_ids}
    return len(pairs)


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
