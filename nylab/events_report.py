"""nylab.events_report -- ROADMAP 7.3: builds the full events table (events.parquet) and
descriptive stats over it (FVG fill rates, sweep -> MSS conversion) per session.

Deliberately a DESCRIPTIVE report, not a new source of hypothesis-testable day-table columns:
adding raw per-event counts into `d` would multiply the number of things RESEARCH_PROTOCOL.md's
ledger has to count as tests, and none of Akash's hypotheses reference per-event detail anyway
(they read day-level summaries). If a specific aggregate here (a fill rate, a conversion rate)
turns out to matter enough to test formally, it becomes its OWN hypothesis YAML / ledger entry
the normal way -- this module's job stops at "what happened, descriptively".

Reuses nylab.sessions's own per-session raid-level convention (the immediately preceding
session's high/low in SESSION_IDS's chain, plus pdh/pdl/pwh/pwl) so the levels scanned per
session here are exactly the ones nylab.sessions already validated as meaningful, not a second,
possibly-inconsistent choice.
"""
from __future__ import annotations

import pandas as pd

from nylab import events as events_mod
from nylab import ict_features
from nylab import structure
from nylab.days import window
from nylab.sessions import SESSION_IDS, _PREV_IN_CHAIN


def build_events_table(df: pd.DataFrame, d: pd.DataFrame, sessions_cfg: dict, pip: float,
                        swing_n: int = 2, mss_max_bars: int = 24, fvg_horizon_bars: int = 576
                        ) -> dict[str, pd.DataFrame]:
    """Computes every Phase 7.2 event type ONCE over the full continuous bar series, then scans
    raids/sweeps/MSS/order-blocks per session window (SESSION_IDS) the same way nylab.sessions
    already does for its own first-raid columns. Returns a dict of DataFrames:
    {'fvg': ..., 'raids': ..., 'mss': ..., 'order_blocks': ...} -- ROADMAP 7.3's "events.parquet"
    is these four written out as separate parquet files (a single table would need an
    unenlightening union-of-columns schema across four quite different event shapes)."""
    atr = ict_features.atr(df)
    swings = structure.label_swings(df, n=swing_n)
    displacement = ict_features.displacement_candles(df, atr)
    bull_fvg, bear_fvg = ict_features.fair_value_gaps(df, atr, pip=pip)

    fvg = events_mod.fvg_lifecycle(df, atr, pip, horizon_bars=fvg_horizon_bars)

    all_raids = []
    for sid in SESSION_IDS:
        lo, hi = sessions_cfg[sid]
        levels = {}
        pred = _PREV_IN_CHAIN.get(sid)
        if pred is not None:
            plo, phi = sessions_cfg[pred]
            pred_raw = window(df, plo, phi, pred)
            levels["prev_high"] = ("above", pred_raw[f"{pred}_high"])
            levels["prev_low"] = ("below", pred_raw[f"{pred}_low"])
        if "pdh" in d.columns:
            levels["pdh"] = ("above", d["pdh"])
            levels["pdl"] = ("below", d["pdl"])
        if "pwh" in d.columns:
            levels["pwh"] = ("above", d["pwh"])
            levels["pwl"] = ("below", d["pwl"])
        if not levels:
            continue
        r = events_mod.detect_raids(df, levels, lo, hi, pip)
        if len(r):
            r = r.assign(session=sid)
            all_raids.append(r)
    raids = pd.concat(all_raids, ignore_index=True) if all_raids else pd.DataFrame()

    mss = events_mod.detect_mss(df, raids, swings, displacement, bull_fvg, bear_fvg,
                                 max_bars=mss_max_bars) if len(raids) else pd.DataFrame()
    obs = events_mod.detect_order_blocks(df, mss, displacement) if len(mss) else pd.DataFrame()

    return {"fvg": fvg, "raids": raids, "mss": mss, "order_blocks": obs}


def save(tables: dict[str, pd.DataFrame], out_dir: str) -> None:
    """Writes each table as <out_dir>/events_<name>.parquet (ROADMAP 7.3's events.parquet,
    split by event kind -- see build_events_table's docstring)."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    for name, tbl in tables.items():
        path = os.path.join(out_dir, f"events_{name}.parquet")
        tbl.to_parquet(path, index=False)


def descriptive_stats(tables: dict[str, pd.DataFrame]) -> dict:
    """FEATURES_SPEC-adjacent, ROADMAP 7.3: FVG fill rates and sweep -> MSS conversion, the two
    aggregate numbers the roadmap names explicitly. Returns a plain dict (JSON-safe: no NaN/inf
    left in -- see nylab.replay.server._json_safe for why that matters once this reaches a UI)."""
    fvg, raids, mss = tables.get("fvg", pd.DataFrame()), tables.get("raids", pd.DataFrame()), tables.get("mss", pd.DataFrame())
    out: dict = {}

    if len(fvg):
        n = len(fvg)
        out["fvg"] = dict(
            n=n,
            first_touch_rate=float((fvg["first_touch_idx"] >= 0).mean()),
            ce_touch_rate=float((fvg["ce_touch_idx"] >= 0).mean()),
            full_fill_rate=float((fvg["full_fill_idx"] >= 0).mean()),
            invalidated_rate=float((fvg["invalidated_idx"] >= 0).mean()),
            by_direction={
                direction: dict(
                    n=int(len(g)),
                    full_fill_rate=float((g["full_fill_idx"] >= 0).mean()) if len(g) else float("nan"),
                )
                for direction, g in fvg.groupby("direction")
            },
        )
    else:
        out["fvg"] = dict(n=0)

    if len(raids):
        sweeps = raids[raids["raid_type"] == "sweep"]
        n_sweeps = len(sweeps)
        n_converted = len(mss) if len(mss) else 0
        out["raids"] = dict(
            n=len(raids), n_sweeps=n_sweeps, n_breaks=int((raids["raid_type"] == "break").sum()),
            by_session={sid: int(n) for sid, n in raids["session"].value_counts().items()},
        )
        out["sweep_to_mss_conversion"] = dict(
            n_sweeps=n_sweeps, n_mss=n_converted,
            rate=float(n_converted / n_sweeps) if n_sweeps else float("nan"),
        )
    else:
        out["raids"] = dict(n=0)
        out["sweep_to_mss_conversion"] = dict(n_sweeps=0, n_mss=0, rate=float("nan"))

    return out
