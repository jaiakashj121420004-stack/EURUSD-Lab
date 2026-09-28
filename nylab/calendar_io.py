"""nylab.calendar_io -- load the economic calendar from mql5/ExportCalendar.mq5's CSV (or a
user-supplied fallback CSV), convert to New York time with the SAME tz mode used for the price
bars, and cache it as parquet (ROADMAP 4.2/4.4, SESSIONS_AND_CONTEXT.md S4).

Canonical output columns (what everything downstream consumes): time_ny (datetime64, naive,
NY-local), currency (str, upper), event_name (str), importance (int 0-3, 3=high), actual,
forecast, previous (float, NaN if not yet released / not applicable).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from nylab.data import timezones

# MQL5's FileOpen(..., FILE_ANSI, ...) writes calendar_export.csv in Windows' ANSI codepage,
# not UTF-8 -- event names with a dash/accented character ("U.S. \u2013 Fed Speech", say) then
# fail a plain utf-8 read. Try utf-8 first (handles a plain-ASCII export, and any fallback CSV a
# user wrote themselves in a normal editor), then fall back to cp1252 (Windows' default Western
# European ANSI codepage), then latin-1 (never raises -- last resort so import never hard-crashes
# on an encoding it doesn't recognize).
_CSV_ENCODINGS = ("utf-8", "cp1252", "latin-1")


def _read_csv_any_encoding(path, **kwargs) -> pd.DataFrame:
    last_err = None
    for enc in _CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc, **kwargs)
        except UnicodeDecodeError as e:
            last_err = e
    raise last_err

MT5_COLUMNS = {"time_server", "currency", "event_name", "importance"}
FALLBACK_COLUMNS = {"datetime_ny", "currency", "event", "impact"}

_IMPACT_MAP = {"none": 0, "low": 1, "moderate": 2, "medium": 2, "high": 3}


def _coerce_importance(raw) -> int:
    if pd.isna(raw):
        return 0
    s = str(raw).strip().lower()
    if s in _IMPACT_MAP:
        return _IMPACT_MAP[s]
    try:
        return int(float(s))
    except ValueError:
        return 0


def load_mt5_export(path: str, tz_mode: str = "ny+7") -> pd.DataFrame:
    """mql5/ExportCalendar.mq5's calendar_export.csv: time_server, currency, event_id,
    event_name, importance, actual, forecast, previous, revised_previous, unit, multiplier.
    tz_mode MUST match whatever mode nylab.data.timezones used for the price bars (DATA_AND_TIME.md
    S2, SESSIONS_AND_CONTEXT.md S4) -- the calendar and the bars have to agree on what "NY time"
    means or every availability/look-ahead check downstream is silently wrong."""
    raw = _read_csv_any_encoding(path)
    missing = MT5_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)} -- not an ExportCalendar.mq5 export?")

    server = pd.to_datetime(raw["time_server"])
    time_ny = timezones.to_new_york(server, tz_mode)

    out = pd.DataFrame({
        "time_ny": time_ny,
        "currency": raw["currency"].astype(str).str.upper().str.strip(),
        "event_name": raw["event_name"].astype(str).str.strip(),
        "importance": raw["importance"].apply(_coerce_importance),
        "actual": pd.to_numeric(raw.get("actual"), errors="coerce"),
        "forecast": pd.to_numeric(raw.get("forecast"), errors="coerce"),
        "previous": pd.to_numeric(raw.get("previous"), errors="coerce"),
    })
    return out


def load_fallback_csv(path: str) -> pd.DataFrame:
    """4.4 fallback: a user-supplied CSV with columns datetime_ny, currency, event, impact,
    actual, forecast, previous -- already in NY time, no tz conversion needed. Use this when
    ExportCalendar.mq5 can't be run (e.g. broker disables MQL5 calendar access)."""
    raw = _read_csv_any_encoding(path)
    missing = FALLBACK_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)} -- expected the fallback schema "
                          f"datetime_ny,currency,event,impact,actual,forecast,previous")

    out = pd.DataFrame({
        "time_ny": pd.to_datetime(raw["datetime_ny"]),
        "currency": raw["currency"].astype(str).str.upper().str.strip(),
        "event_name": raw["event"].astype(str).str.strip(),
        "importance": raw["impact"].apply(_coerce_importance),
        "actual": pd.to_numeric(raw.get("actual"), errors="coerce"),
        "forecast": pd.to_numeric(raw.get("forecast"), errors="coerce"),
        "previous": pd.to_numeric(raw.get("previous"), errors="coerce"),
    })
    return out


def load(path: str, tz_mode: str = "ny+7") -> pd.DataFrame:
    """Auto-detects ExportCalendar.mq5's schema vs the 4.4 fallback schema by column names,
    then dispatches. This is what `nylab calendar-import` calls."""
    header = _read_csv_any_encoding(path, nrows=0).columns
    cols = set(header)
    if MT5_COLUMNS <= cols:
        df = load_mt5_export(path, tz_mode)
    elif FALLBACK_COLUMNS <= cols:
        df = load_fallback_csv(path)
    else:
        raise ValueError(
            f"{path}: columns {sorted(cols)} don't match either the ExportCalendar.mq5 schema "
            f"({sorted(MT5_COLUMNS)}...) or the fallback schema ({sorted(FALLBACK_COLUMNS)}...)."
        )
    df = df.dropna(subset=["time_ny", "currency", "event_name"])
    df = df.sort_values("time_ny").drop_duplicates(["time_ny", "currency", "event_name"]).reset_index(drop=True)
    return df


def save(df: pd.DataFrame, path: str = "data/calendar.parquet") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)


def load_cache(path: str = "data/calendar.parquet") -> pd.DataFrame:
    return pd.read_parquet(path)


def freshness_message(path: str = "data/calendar.parquet", max_age_days: float = 7.0) -> str | None:
    """ROADMAP 9.4: run_daily.bat's weekly re-export reminder. Purely informational -- calendar
    features are optional (`nylab run` already runs fine without data/calendar.parquet, just
    skipping news columns), so this never raises or blocks anything, only returns a message to
    print (or None when there's nothing to say). Kept as a plain function, not inline batch-file
    logic, so it's unit-testable without a real Windows/MT5 setup."""
    import os
    import time

    if not os.path.exists(path):
        return (f"no {path} yet -- news features are being skipped (optional; see README / "
                f"ROADMAP Phase 4 to set it up).")
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    if age_days < max_age_days:
        return None
    return (f"{path} is {age_days:.0f} days old -- re-export calendar_export.csv (see README) "
            f"and run: python -m nylab calendar-import calendar_export.csv")
