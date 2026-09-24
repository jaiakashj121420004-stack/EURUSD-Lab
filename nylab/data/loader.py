"""nylab.data.loader -- CSV (python export or MT5 'Export Bars') -> canonical bars DataFrame.

DATA_AND_TIME.md S1 pitfall 5: the loader must accept both the python-export format
(comma-separated: time,open,high,low,close,tick_volume,spread,real_volume) AND MT5's own
"Export Bars" format (tab-separated, <DATE> <TIME> <OPEN> ... headers). sep=None with the
python engine lets pandas sniff the delimiter so both work without extra flags.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def load_bars(path: str) -> pd.DataFrame:
    """Returns columns: server (datetime64, naive, sorted, de-duplicated), open, high, low,
    close (float), spread_pts (float, NaN if the source has no spread column), tick_volume
    (float, NaN if absent)."""
    df = pd.read_csv(path, sep=None, engine="python")
    cols = {c.lower().strip("<>"): c for c in df.columns}

    if "time" not in cols and "date" in cols:
        time_col = cols.get("time", cols["date"])
        tcol = pd.to_datetime(df[cols["date"]].astype(str) + " " + df[time_col].astype(str))
    else:
        raw = df[cols["time"]]
        tcol = pd.to_datetime(raw, unit="s") if np.issubdtype(raw.dtype, np.number) else pd.to_datetime(raw)

    out = pd.DataFrame({"server": tcol})
    for k in ("open", "high", "low", "close"):
        out[k] = df[cols[k]].astype(float)
    out["spread_pts"] = df[cols["spread"]].astype(float) if "spread" in cols else np.nan
    out["tick_volume"] = df[cols["tick_volume"]].astype(float) if "tick_volume" in cols else np.nan

    out = out.dropna(subset=["server", "open", "high", "low", "close"])
    out = out.sort_values("server").drop_duplicates("server").reset_index(drop=True)
    return out
