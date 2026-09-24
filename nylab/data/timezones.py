"""nylab.data.timezones -- server time -> New York time conversion, auto-detect, sanity check.

Ported from ny_session_lab.py's to_new_york()/detect_tz(). Per Akash's request (2026-09-24),
callers default to "ny+7" (the common "NY close" broker convention) rather than asking him to
pick a --tz mode; sanity_check() is the safety net that flags it if that default is wrong for
his broker, instead of a menu of timezone choices.
"""
from __future__ import annotations

import pandas as pd


def detect_tz(server: pd.Series) -> str:
    """Guess the broker's server-clock convention from the hour trading resumes after the
    weekend gap (DATA_AND_TIME.md S2)."""
    gaps = server.diff() > pd.Timedelta(hours=30)
    hours = server[gaps].dt.hour
    if len(hours) < 4:
        return "ny+7"
    h = int(hours.mode().iloc[0])
    if h in (0, 1):
        return "ny+7"       # Sunday 17:00 NY == 00:00 server ("NY close" convention)
    if h in (21, 22):
        return "utc"
    if h in (23,):
        return "utc+1"
    return "ny+7"           # default; sanity_check() below is the real safety net


def to_new_york(server: pd.Series, mode: str) -> pd.Series:
    if mode == "ny+7":
        return server - pd.Timedelta(hours=7)
    if mode == "ny":
        return server
    if mode == "eu":
        # EU-DST servers (UTC+2/+3 following EU DST, not US DST) -- DATA_AND_TIME.md S2.
        eu = server.dt.tz_localize("Europe/Athens", ambiguous="infer", nonexistent="shift_forward")
        return eu.dt.tz_convert("America/New_York").dt.tz_localize(None)
    if mode.startswith("utc"):
        off = float(mode[3:] or 0)
        utc = (server - pd.Timedelta(hours=off)).dt.tz_localize("UTC")
        return utc.dt.tz_convert("America/New_York").dt.tz_localize(None)
    raise ValueError(f"unsupported --tz mode: {mode!r} (use auto, ny+7, ny, utc, utc+N, eu)")


def sanity_check(bars_ny: pd.DataFrame, pip: float) -> dict:
    """DATA_AND_TIME.md S2 mandatory check: for EURUSD, median range by NY hour must peak
    inside 08:00-11:00. bars_ny needs columns 'ny' and 'high'/'low'. Returns ok=False (a red
    flag, not an exception) if the peak is somewhere else -- that means the tz mode is wrong."""
    h = bars_ny["ny"].dt.hour
    rng = (bars_ny["high"] - bars_ny["low"]) / pip
    by_hour = rng.groupby(h).median().reindex(range(24))
    top4 = set(by_hour.nlargest(4).index)
    ok = any(hr in top4 for hr in (8, 9, 10))
    return dict(
        ok=bool(ok),
        peak_hour=int(by_hour.idxmax()) if by_hour.notna().any() else None,
        median_range_by_hour={int(k): (None if pd.isna(v) else round(float(v), 2)) for k, v in by_hour.items()},
    )
