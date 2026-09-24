"""nylab.report.summary -- summary.json, what Claude reads after each run (ARCHITECTURE.md S6)."""
from __future__ import annotations

import json
from pathlib import Path


def build(run_id, meta, tz_check, H, m, model_stats, bonferroni_alpha=None) -> dict:
    """H is nylab.hyp_engine.evaluate()'s row DataFrame (Phase 3) -- it already carries the
    real verdict (RESEARCH_PROTOCOL.md S9 vocabulary: noise/weak/candidate/promising/
    not proven/survives-oos/killed), Bonferroni AND Benjamini-Hochberg flags, so this just
    reshapes those columns into ARCHITECTURE.md S6's JSON schema rather than recomputing
    anything itself -- there should be exactly one place that decides a hypothesis's verdict."""
    hyps = []
    for _, r in H.iterrows():
        hyps.append(dict(
            id=r.get("id", r["hypothesis"]), title=r["hypothesis"], n=int(r["n"]),
            hit=None if r["hit"] != r["hit"] else round(float(r["hit"]), 4),
            baseline=round(float(r["baseline"]), 4),
            z=None if r["z"] != r["z"] else round(float(r["z"]), 3),
            p=None if r["p"] != r["p"] else round(float(r["p"]), 4),
            bonf_sig=bool(r.get("bonferroni_sig", False)),
            bh_sig=bool(r.get("bh_sig", False)),
            oos_hit=None if r["oos_hit"] != r["oos_hit"] else round(float(r["oos_hit"]), 4),
            oos_n=int(r["oos_n"]),
            oos_holds=bool(r.get("oos_holds", False)),
            verdict=r.get("verdict", "noise"),
        ))
    return dict(
        run_id=run_id,
        data=dict(first=meta["first"], last=meta["last"], days=meta["n_days"], tz_mode=meta["tz"],
                   tz_sanity=("ok" if tz_check["ok"] else
                              f"WARNING: peak hour is {tz_check['peak_hour']}, expected 08-10 -- check --tz")),
        ledger_total_tests=m,
        bonferroni_alpha=round(bonferroni_alpha if bonferroni_alpha is not None else 0.05 / m, 6),
        hypotheses=hyps,
        models=[model_stats] if model_stats else [],
    )


def write(out_dict: dict, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out_dict, f, indent=2, default=str)
