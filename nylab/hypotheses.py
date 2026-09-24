"""nylab.hypotheses -- the 15 fixed hypotheses from v0, ported verbatim.

Phase 3 replaces this module with YAML hypothesis files + the safe DSL + the append-only
ledger (ARCHITECTURE.md S5, RESEARCH_PROTOCOL.md). Kept as plain Python here so Phase 1's
output matches the v0 golden files exactly (ROADMAP Phase 1 acceptance).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab.stats import wilson_ci, ztest


def evaluate(d: pd.DataFrame, split_date) -> tuple[pd.DataFrame, int]:
    """Each row of H: (name, condition mask, outcome mask, baseline outcome mask over ALL days)."""
    up = d.ny_drive > 0
    dn = d.ny_drive < 0
    H = [
        ("London KZ bullish -> NY drive (09:30-16:00) up", d.lon_dir > 0, up, up),
        ("London KZ bearish -> NY drive down", d.lon_dir < 0, dn, dn),
        ("09:30 below midnight open (discount) -> NY drive up", d.o0930 < d.mid_open, up, up),
        ("09:30 above midnight open (premium) -> NY drive down", d.o0930 > d.mid_open, dn, dn),
        ("Pre-NY (07-09:30) raids London high only -> NY drive down", d.pre_takes_lon_high & ~d.pre_takes_lon_low, dn, dn),
        ("Pre-NY raids London low only -> NY drive up", d.pre_takes_lon_low & ~d.pre_takes_lon_high, up, up),
        ("Pre-NY raids PDH -> NY drive down", d.pre_takes_pdh & ~d.pre_takes_pdl, dn, dn),
        ("Pre-NY raids PDL -> NY drive up", d.pre_takes_pdl & ~d.pre_takes_pdh, up, up),
        ("08:30-09:30 up (news hour) -> NY drive down (Judas)", d.newshr_dir > 0, dn, dn),
        ("08:30-09:30 down -> NY drive up (Judas)", d.newshr_dir < 0, up, up),
        ("Previous day up -> NY drive up", d.prev_day_dir > 0, up, up),
        ("Previous day down -> NY drive down", d.prev_day_dir < 0, dn, dn),
        ("ADR used by 09:30 > 80% -> NY range below its median", d.adr_used_0930 > 0.8,
         d.ny_range < d.ny_range.median(), d.ny_range < d.ny_range.median()),
        ("Asia range in bottom 20% -> NY range above its median", d.asia_range < d.asia_range.quantile(0.2),
         d.ny_range > d.ny_range.median(), d.ny_range > d.ny_range.median()),
        ("NY raids London high -> NY closes back below it", d.ny_takes_lon_high, d.ny_close < d.lon_high,
         pd.Series(True, index=d.index) & (d.ny_close < d.lon_high) | True),
    ]
    rows = []
    is_mask = d.index < split_date
    m = len(H)
    for name, cond, out, base in H:
        cond = cond.fillna(False).astype(bool)
        out = out.fillna(False).astype(bool)
        n, k = int(cond.sum()), int((cond & out).sum())
        p0 = 0.5 if name.startswith("NY raids London high") else float(base.fillna(False).astype(bool).mean())
        z, pv = ztest(k, n, p0)
        ni, ki = int((cond & is_mask).sum()), int((cond & out & is_mask).sum())
        no, ko = int((cond & ~is_mask).sum()), int((cond & out & ~is_mask).sum())
        lo, hi = wilson_ci(k, n)
        rows.append(dict(
            hypothesis=name, n=n, hit=k / n if n else np.nan, baseline=p0,
            ci_lo=lo, ci_hi=hi, z=z, p=pv,
            bonferroni_sig=(pv < 0.05 / m) if n else False,
            is_hit=ki / ni if ni else np.nan, oos_hit=ko / no if no else np.nan, oos_n=no,
            oos_holds=(no >= 20 and ni > 0 and (ki / ni - p0) * (ko / no - p0) > 0 and abs(ko / no - p0) >= 0.03),
        ))
    return pd.DataFrame(rows), m
