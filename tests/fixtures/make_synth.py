"""
make_synth.py -- synthetic EURUSD M5 bars for testing the pipeline without real MT5 data.

Server time = NY+7 ("NY close" broker convention: server midnight == 17:00 NY, DST handled
automatically because the convention is a fixed +7h offset from NY wall-clock time).

Two variants, same base random-walk engine and intraday volatility profile
(quiet Asia, bump London, peak 08:00-11:00 NY), built deterministically from --seed:

  clean   -- no edge by construction. The pipeline must find NOTHING here (AT-01).
  planted -- identical to clean, EXCEPT: on --frac (default 60%) of the trading days where
             the pre-NY window (07:00-09:30 NY) trades through the London killzone high
             (02:00-05:00 NY) -- i.e. `pre_takes_lon_high` in ny_session_lab.py / nylab --
             the 09:30 -> 16:00 NY drive (`ny_drive`) is forced negative by adding a downward
             ramp to those bars. The pipeline MUST find this edge (AT-02, hit >= 0.58).

Usage:
    python make_synth.py --variant clean   --years 5 --seed 7
    python make_synth.py --variant planted --years 5 --seed 7
    python make_synth.py --variant planted --years 2 --seed 7 --frac 0.6

Output file name (unless --out given): EURUSD_M5_synth_<variant>_<years>y.csv
Columns match what mt5_export.py produces and ny_session_lab.py / nylab expect:
    time, open, high, low, close, tick_volume, spread, real_volume
"""
import argparse

import numpy as np
import pandas as pd

PIP = 0.0001
ANCHOR_END = pd.Timestamp("2025-12-31 23:55")  # fixed anchor -> runs are reproducible


def make_clean_bars(years: float, seed: int) -> pd.DataFrame:
    """Base random-walk M5 bars, server time = NY+7, intraday vol profile, NO edge."""
    rng = np.random.default_rng(seed)
    start = (ANCHOR_END - pd.Timedelta(days=round(years * 365.25))).floor("D")
    idx = pd.date_range(start, ANCHOR_END, freq="5min")  # server time
    ny = idx - pd.Timedelta(hours=7)

    dow, hour = ny.dayofweek, ny.hour
    # market closed Fri 17:00 NY -> Sun 17:00 NY
    closed = ((dow == 4) & (hour >= 17)) | (dow == 5) | ((dow == 6) & (hour < 17))
    idx, ny = idx[~closed], ny[~closed]

    h = ny.hour + ny.minute / 60.0
    vol = np.where(
        (h >= 8) & (h < 11), 1.8,
        np.where((h >= 2) & (h < 5), 1.3, np.where((h >= 17) | (h < 2), 0.5, 0.9)),
    ) * 0.00012

    ret = rng.normal(0, vol)
    close = 1.08 + np.cumsum(ret)
    open_ = np.r_[1.08, close[:-1]]
    high = np.maximum(open_, close) + np.abs(rng.normal(0, vol * 0.6))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, vol * 0.6))

    return pd.DataFrame(
        dict(
            time=idx, ny=ny, open=open_, high=high, low=low, close=close,
            tick_volume=100, spread=rng.integers(1, 8, len(idx)), real_volume=0,
        )
    )


def trading_day(ny: pd.Series) -> pd.Series:
    """td label = calendar date the 17:00 NY -> 17:00 NY window ENDS on (DATA_AND_TIME S3)."""
    return (ny + pd.Timedelta(hours=7)).dt.floor("D")


def plant_edge(bars: pd.DataFrame, seed: int, frac: float) -> pd.DataFrame:
    """Force a down-drive 09:30->16:00 NY on `frac` of days where pre-NY raids the London high."""
    bars = bars.copy()
    bars["td"] = trading_day(bars["ny"])
    h = bars["ny"].dt.hour + bars["ny"].dt.minute / 60.0
    bars["h"] = h

    lon_mask = (h >= 2) & (h < 5)
    pre_mask = (h >= 7) & (h < 9.5)
    pm_mask = (h >= 9.5) & (h < 16)

    lon_high = bars.loc[lon_mask].groupby("td")["high"].max()
    pre_high = bars.loc[pre_mask].groupby("td")["high"].max()

    common = pre_high.index.intersection(lon_high.index)
    cond_days = common[pre_high.loc[common].values > lon_high.loc[common].values]

    rng = np.random.default_rng(seed + 1)  # separate stream from the base walk
    affected = cond_days[rng.random(len(cond_days)) < frac]

    n_planted = 0
    for td in affected:
        day_mask = (bars["td"] == td) & pm_mask
        idx = bars.index[day_mask]
        n = len(idx)
        if n == 0:
            continue
        drift = -np.linspace(0, 9 * PIP, n)  # ~9 pip forced drive down by 16:00 NY
        for col in ("open", "high", "low", "close"):
            bars.loc[idx, col] = bars.loc[idx, col] + drift
        n_planted += 1

    bars = bars.drop(columns=["td", "h"])
    print(
        f"  planted: {len(cond_days)} days met the pre-NY-raids-London-high condition; "
        f"forced the down-drive on {n_planted} of them ({frac:.0%} target)."
    )
    return bars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["clean", "planted"], required=True)
    ap.add_argument("--years", type=float, default=5)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--frac", type=float, default=0.6, help="planted only: fraction of condition days affected")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    bars = make_clean_bars(a.years, a.seed)
    if a.variant == "planted":
        bars = plant_edge(bars, a.seed, a.frac)

    out = a.out or f"EURUSD_M5_synth_{a.variant}_{a.years:g}y.csv"
    cols = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    bars[cols].to_csv(out, index=False)
    print(f"wrote {out}: {len(bars)} bars, {bars['time'].min()} .. {bars['time'].max()} (server time)")


if __name__ == "__main__":
    main()
