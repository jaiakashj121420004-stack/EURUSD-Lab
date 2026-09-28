"""nylab.hyp_engine -- evaluate loaded Hypothesis objects against the day table
(RESEARCH_PROTOCOL.md S2/S4/S9, ROADMAP 3.4/3.5). Successor to nylab.hypotheses' hardcoded
v0 port: same statistics (Wilson CI, z-test), now driven by YAML + the safe DSL, plus the
append-only ledger, Bonferroni AND Benjamini-Hochberg, and RESEARCH_PROTOCOL's verdict rules.

ROADMAP 5.7.3 (2026-09-27): the significance test (`z`/`p`/`ci_lo`/`ci_hi`) was rewritten per
RESEARCH_PROTOCOL.md S2's 2026-09-26 clarification -- see `evaluate()`'s own docstring for the
exact before/after. `n`/`hit`/`is_hit`/`oos_hit`/`oos_n` keep their EXISTING full-sample /
split-specific meanings (still purely descriptive, still comparable to earlier runs); only the
significance-test trio and the new `direction`/`effect_*` fields are new.
"""
from __future__ import annotations

import pandas as pd

from nylab import hyp_dsl
from nylab import ledger as ledger_mod
from nylab.stats import ztest, two_proportion_ztest, wilson_ci

# RESEARCH_PROTOCOL S9's exact verdict vocabulary.
VERDICTS = ("noise", "weak", "candidate", "promising", "not proven", "survives-oos", "killed")

EMBARGO_TD = 5  # ROADMAP 5.7.3: trading days excluded from BOTH is_mask and oos_mask, right at
# the IS/OOS boundary -- guards against any rolling/prior-window feature (quantile_prior,
# median_prior, adr5/adr20, range_rel, ...) whose window straddles the split from leaking a
# little bit of OOS information into an IS-side row, or vice versa.

# ROADMAP 5.7.3 "effect in pips": columns whose value is genuinely pip-denominated (a distance,
# not a sign/ratio/raw price) -- the only ones where reporting "median pips, condition vs
# complement" is meaningful (RESEARCH_PROTOCOL.md S2's own H013 example: "median 43 vs 41 pips").
# Deliberately an explicit allow-list rather than "any numeric column": ny_drive is numeric but a
# sign (-1/0/1), and ny_close/lon_high are numeric but raw PRICES (need /pip to mean anything) --
# reporting either as "pips" would be actively misleading. A hypothesis whose outcome doesn't
# reference one of these (e.g. H001-H012's `ny_drive`, H015's `ny_close`, H016's `character`) has
# no effect_col at all -- lift_pp is still reported for those, just not a pip figure.
PIP_UNIT_COLUMNS = {
    "day_range", "asia_range", "lon_range", "ny_range", "cbdr_range",
    "r0930_1600", "adr5", "adr20",
}


def _mask(expr: str, ns: dict) -> pd.Series:
    val = hyp_dsl.evaluate(expr, ns)
    if not isinstance(val, pd.Series):
        idx = next(v.index for v in ns.values() if isinstance(v, pd.Series))
        val = pd.Series(val, index=idx)
    return val.reindex(next(iter(ns.values())).index).fillna(False).astype(bool)


def _split_masks(index: pd.Index, split_date) -> tuple[pd.Series, pd.Series]:
    """ROADMAP 5.7.3's 5-td embargo: IS keeps its existing boundary (`< split_date`, unchanged
    from before this ticket -- no earlier test's IS row count moves); OOS starts EMBARGO_TD
    trading days later. Rows in between belong to neither mask."""
    at_or_after = index[index >= split_date]
    oos_start = at_or_after[EMBARGO_TD] if len(at_or_after) > EMBARGO_TD else split_date
    is_mask = pd.Series(index < split_date, index=index)
    oos_mask = pd.Series(index >= oos_start, index=index)
    return is_mask, oos_mask


def _effect_col(outcome_expr: str) -> str | None:
    """The first pip-denominated column (PIP_UNIT_COLUMNS) the outcome expression references, if
    any -- e.g. H013 v1.1's `r0930_1600 < median(r0930_1600)` -> 'r0930_1600'."""
    tree = hyp_dsl.parse(outcome_expr)
    for col in hyp_dsl.referenced_columns(tree):
        if col in PIP_UNIT_COLUMNS:
            return col
    return None


def evaluate(d: pd.DataFrame, hyps: list, split_date, run_id: str,
             ledger_path: str = "research/ledger.csv", bh_q: float = 0.10):
    """Returns (rows: pd.DataFrame, ledger_rows: list[dict], m: int, bonferroni_alpha: float).

    `m` is computed from the EXISTING ledger plus this run's own (id, version) pairs, so a
    fresh run of an unchanged hypothesis set doesn't inflate its own correction just by
    running again (RESEARCH_PROTOCOL S4: "re-running an unchanged hypothesis does not
    increase m").

    ROADMAP 5.7.3's significance-test rewrite (RESEARCH_PROTOCOL.md S2, 2026-09-26 clarification):
    BEFORE, `z`/`p` came from a one-proportion test of the FULL SAMPLE (IS+OOS combined) against
    a `baseline` expression evaluated over ALL days -- including the condition's own days, which
    dilutes the very contrast being tested, AND lets OOS data leak into the number that decides
    "is this real" (look-ahead into the test itself, not just the hypothesis). AFTER: `z`/`p`/
    `ci_lo`/`ci_hi` describe ONE estimate, computed on IS ONLY -- the condition-true hit rate --
    tested against its own COMPLEMENT (days where the condition is false, also IS-only) with a
    two-proportion z-test, unless the hypothesis sets an explicit `baseline_p0` (a deliberately
    literal theoretical null, e.g. H015's 50% coin-flip -- there ztest() against that literal p0
    is still the right test, just now on IS-only n/k instead of full-sample). `n`/`hit`/`is_hit`/
    `oos_hit`/`oos_n` are UNCHANGED descriptive full-sample/split stats, still comparable across
    runs made before this ticket."""
    ns = {col: d[col] for col in d.columns}
    is_mask, oos_mask = _split_masks(d.index, split_date)

    def _cells(h):
        return h.matrix_shape[0] * h.matrix_shape[1] if h.matrix_shape else 1

    m = ledger_mod.distinct_m(ledger_path, extra_ids=[(h.id, h.version, _cells(h)) for h in hyps])
    alpha_bonf = ledger_mod.bonferroni_alpha(m)
    cells_by_id = {(h.id, h.version): _cells(h) for h in hyps}

    raw = []
    for h in hyps:
        cond = _mask(h.condition, ns)
        out = _mask(h.outcome, ns)

        n, k = int(cond.sum()), int((cond & out).sum())
        n1, k1 = int((cond & is_mask).sum()), int((cond & out & is_mask).sum())       # IS, condition-true
        n2, k2 = int((~cond & is_mask).sum()), int((~cond & out & is_mask).sum())      # IS, complement
        no, ko = int((cond & oos_mask).sum()), int((cond & out & oos_mask).sum())      # OOS (post-embargo)

        if h.baseline_p0 is not None:
            baseline_value = h.baseline_p0
            z, pv = ztest(k1, n1, h.baseline_p0)
        else:
            baseline_value = (k2 / n2) if n2 else float("nan")
            z, pv = two_proportion_ztest(k1, n1, k2, n2)
        lo, hi = wilson_ci(k1, n1)  # the SAME IS-only estimate z/p just tested, not the old full-sample one

        is_hit = k1 / n1 if n1 else float("nan")
        oos_hit = ko / no if no else float("nan")
        lift_pp = (oos_hit - baseline_value) * 100 if no and not pd.isna(baseline_value) else float("nan")
        direction = (
            None if n1 == 0 or pd.isna(baseline_value)
            else ("as_claimed" if (is_hit - baseline_value) >= 0 else "opposite")
        )

        effect_col = _effect_col(h.outcome)
        if effect_col:
            col = d[effect_col]
            effect_is_cond = col[cond & is_mask].median()
            effect_is_complement = col[~cond & is_mask].median()
            effect_oos_cond = col[cond & oos_mask].median()
            effect_oos_complement = col[~cond & oos_mask].median()
        else:
            effect_is_cond = effect_is_complement = effect_oos_cond = effect_oos_complement = float("nan")

        raw.append(dict(
            id=h.id, version=h.version, hypothesis=h.title, family=h.family, min_n=h.min_n,
            n=n, hit=(k / n if n else float("nan")), baseline=baseline_value, ci_lo=lo, ci_hi=hi,
            z=z, p=pv, is_hit=is_hit, oos_hit=oos_hit, oos_n=no, lift_pp=lift_pp,
            direction=direction, effect_col=effect_col,
            effect_is_cond_pips=effect_is_cond, effect_is_complement_pips=effect_is_complement,
            effect_oos_cond_pips=effect_oos_cond, effect_oos_complement_pips=effect_oos_complement,
            is_n=n1,  # ROADMAP 5.7.3: min_n now gates on the IS-only n actually used by the test
        ))

    pvals = [r["p"] for r in raw]
    # Audit fix 2026-09-28: global BH also counts a matrix promotion as its whole matrix
    # (RESEARCH_PROTOCOL S10), same padding-with-p=1.0 idea as the per-family BH below.
    # Decided 2026-09-28 (Akash's call, docs/PROGRESS.md): BH stays scoped to THIS run's own
    # hypotheses, not padded to the full ledger `m` the way Bonferroni is -- padding it out
    # would make BH converge toward Bonferroni's own strictness as the ledger grows, defeating
    # the reason it exists here (a lighter, per-run triage tier separate from the strict
    # lifetime bar that backs `survives-oos`).
    n_tests_this_run = sum(int(cells_by_id[(r["id"], r["version"])] or 1) for r in raw)
    padded = pvals + [1.0] * max(0, n_tests_this_run - len(pvals))
    bh_sig_all = ledger_mod.bh_significant(padded, q=bh_q)[: len(pvals)]

    # Per-family BH too (RESEARCH_PROTOCOL S10: "BH within the family + global Bonferroni").
    families = {r["family"] for r in raw if r["family"]}
    bh_sig_family = {}
    for fam in families:
        idx = [i for i, r in enumerate(raw) if r["family"] == fam]
        fam_p = [raw[i]["p"] for i in idx]
        # Audit fix 2026-09-28: a matrix family's size is its WHOLE matrix (RESEARCH_PROTOCOL
        # S10: "promoting a cell counts the whole matrix as tested"), not just the cells that
        # happen to be promoted into YAML files. Before this, a family with ONE promoted cell
        # (H016, from a 6x6 = 36-cell matrix) ran BH over a list of length 1 -- i.e. no
        # correction at all -- and H016 (p=0.098) was labelled `candidate` on real data. The
        # un-promoted cells are padded in as p=1.0 (never significant themselves), which makes
        # the BH thresholds use the true family size.
        fam_size = max([len(idx)] + [int(cells_by_id[(raw[i]["id"], raw[i]["version"])] or 1) for i in idx])
        fam_p = fam_p + [1.0] * (fam_size - len(idx))
        fam_sig = ledger_mod.bh_significant(fam_p, q=bh_q)[: len(idx)]
        for i, sig in zip(idx, fam_sig):
            bh_sig_family[i] = bool(sig)

    for i, r in enumerate(raw):
        below_min_n = r["is_n"] < r["min_n"]  # ROADMAP 5.7.3: gates on the IS-only n the test uses
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
        r["matrix_cells"] = cells_by_id[(r["id"], r["version"])]  # ROADMAP 5.5: surfaced in
        # the report's relational-hypotheses table so a matrix-family promotion is visibly
        # distinguished from an ordinary 1-cell hypothesis, not just counted invisibly into m.
        del r["min_n"]  # not part of the reported row shape (family/matrix_cells now ARE)
        del r["is_n"]  # internal to the min_n gate above, not part of the reported row shape

    rows = pd.DataFrame(raw)
    ts = pd.Timestamp.now(tz="UTC").isoformat()
    ledger_rows = [dict(
        run_id=run_id, timestamp=ts, kind="hypothesis", id=r["id"], version=r["version"],
        n=r["n"], stat=r["z"], p=r["p"], is_metric=r["is_hit"], oos_metric=r["oos_hit"],
        verdict=r["verdict"], notes="", matrix_cells=cells_by_id[(r["id"], r["version"])],
    ) for r in raw]
    return rows, ledger_rows, m, alpha_bonf
