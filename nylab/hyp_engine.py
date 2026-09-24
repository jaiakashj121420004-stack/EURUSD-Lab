"""nylab.hyp_engine -- evaluate loaded Hypothesis objects against the day table
(RESEARCH_PROTOCOL.md S2/S4/S9, ROADMAP 3.4/3.5). Successor to nylab.hypotheses' hardcoded
v0 port: same statistics (Wilson CI, z-test), now driven by YAML + the safe DSL, plus the
append-only ledger, Bonferroni AND Benjamini-Hochberg, and RESEARCH_PROTOCOL's verdict rules.
"""
from __future__ import annotations

import pandas as pd

from nylab import hyp_dsl
from nylab import ledger as ledger_mod
from nylab.stats import wilson_ci, ztest

# RESEARCH_PROTOCOL S9's exact verdict vocabulary.
VERDICTS = ("noise", "weak", "candidate", "promising", "not proven", "survives-oos", "killed")


def _mask(expr: str, ns: dict) -> pd.Series:
    val = hyp_dsl.evaluate(expr, ns)
    if not isinstance(val, pd.Series):
        idx = next(v.index for v in ns.values() if isinstance(v, pd.Series))
        val = pd.Series(val, index=idx)
    return val.reindex(next(iter(ns.values())).index).fillna(False).astype(bool)


def evaluate(d: pd.DataFrame, hyps: list, split_date, run_id: str,
             ledger_path: str = "research/ledger.csv", bh_q: float = 0.10):
    """Returns (rows: pd.DataFrame, ledger_rows: list[dict], m: int, bonferroni_alpha: float).

    `m` is computed from the EXISTING ledger plus this run's own (id, version) pairs, so a
    fresh run of an unchanged hypothesis set doesn't inflate its own correction just by
    running again (RESEARCH_PROTOCOL S4: "re-running an unchanged hypothesis does not
    increase m")."""
    ns = {col: d[col] for col in d.columns}
    is_mask = d.index < split_date

    m = ledger_mod.distinct_m(ledger_path, extra_ids=[(h.id, h.version) for h in hyps])
    alpha_bonf = ledger_mod.bonferroni_alpha(m)

    raw = []
    for h in hyps:
        cond = _mask(h.condition, ns)
        out = _mask(h.outcome, ns)
        p0 = h.baseline_p0 if h.baseline_p0 is not None else float(_mask(h.baseline, ns).mean())

        n, k = int(cond.sum()), int((cond & out).sum())
        z, pv = ztest(k, n, p0)
        ni, ki = int((cond & is_mask).sum()), int((cond & out & is_mask).sum())
        no, ko = int((cond & ~is_mask).sum()), int((cond & out & ~is_mask).sum())
        lo, hi = wilson_ci(k, n)
        is_hit = ki / ni if ni else float("nan")
        oos_hit = ko / no if no else float("nan")
        lift_pp = (oos_hit - p0) * 100 if no else float("nan")
        raw.append(dict(
            id=h.id, version=h.version, hypothesis=h.title, family=h.family, min_n=h.min_n,
            n=n, hit=(k / n if n else float("nan")), baseline=p0, ci_lo=lo, ci_hi=hi,
            z=z, p=pv, is_hit=is_hit, oos_hit=oos_hit, oos_n=no, lift_pp=lift_pp,
        ))

    pvals = [r["p"] for r in raw]
    bh_sig_all = ledger_mod.bh_significant(pvals, q=bh_q)

    # Per-family BH too (RESEARCH_PROTOCOL S10: "BH within the family + global Bonferroni").
    families = {r["family"] for r in raw if r["family"]}
    bh_sig_family = {}
    for fam in families:
        idx = [i for i, r in enumerate(raw) if r["family"] == fam]
        fam_sig = ledger_mod.bh_significant([raw[i]["p"] for i in idx], q=bh_q)
        for i, sig in zip(idx, fam_sig):
            bh_sig_family[i] = bool(sig)

    for i, r in enumerate(raw):
        below_min_n = r["n"] < r["min_n"]
        r["bonferroni_sig"] = bool(r["n"] and not below_min_n and r["p"] < alpha_bonf)
        r["bh_sig"] = bool(bh_sig_all[i] and not below_min_n)
        r["bh_sig_family"] = bool(bh_sig_family.get(i, False)) and not below_min_n
        oos_same_direction = (
            not pd.isna(r["is_hit"]) and not pd.isna(r["oos_hit"])
            and (r["is_hit"] - r["baseline"]) * (r["oos_hit"] - r["baseline"]) > 0
        )
        r["oos_holds"] = bool(r["oos_n"] >= 20 and oos_same_direction and abs(r["lift_pp"]) >= 3.0)

        if r["n"] == 0 or below_min_n:
            r["verdict"] = "not proven"
        elif r["bonferroni_sig"] and r["oos_holds"]:
            # Akash's call (2026-09, after AT-01 caught this): "survives-oos" is reserved for
            # the STRICT Bonferroni-on-IS route only. BH is deliberately lenient (RESEARCH_
            # PROTOCOL S4: "for triage") -- it is EXPECTED to pass ~1 in 10 null hypotheses by
            # design (10% FDR), so letting a BH pass alone promote all the way to "survives-oos"
            # would occasionally rubber-stamp a pure-noise result as a confirmed finding, which
            # is exactly what AT-01 exists to catch. It caught one (H013) on the clean fixture
            # before this rule was tightened.
            r["verdict"] = "survives-oos"
        elif (r["bh_sig"] or r["bh_sig_family"]) and r["oos_holds"]:
            r["verdict"] = "candidate"
        elif r["bh_sig"] or r["bh_sig_family"]:
            r["verdict"] = "candidate"
        elif r["p"] < 0.10:
            r["verdict"] = "weak"
        else:
            r["verdict"] = "noise"
        del r["family"], r["min_n"]  # not part of the reported row shape

    rows = pd.DataFrame(raw)
    ts = pd.Timestamp.now(tz="UTC").isoformat()
    ledger_rows = [dict(
        run_id=run_id, timestamp=ts, kind="hypothesis", id=r["id"], version=r["version"],
        n=r["n"], stat=r["z"], p=r["p"], is_metric=r["is_hit"], oos_metric=r["oos_hit"],
        verdict=r["verdict"], notes="",
    ) for r in raw]
    return rows, ledger_rows, m, alpha_bonf
