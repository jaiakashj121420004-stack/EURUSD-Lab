"""
make_synth.py -- synthetic EURUSD M5 bars for testing the pipeline without real MT5 data.

Server time = NY+7 ("NY close" broker convention: server midnight == 17:00 NY, DST handled
automatically because the convention is a fixed +7h offset from NY wall-clock time).

Three variants, same base random-walk engine and intraday volatility profile
(quiet Asia, bump London, peak 08:00-11:00 NY), built deterministically from --seed:

  clean   -- no edge by construction. The pipeline must find NOTHING here (AT-01).
  planted -- identical to clean, EXCEPT: on --frac (default 60%) of the trading days where
             the pre-NY window (07:00-09:30 NY) trades through the London killzone high
             (02:00-05:00 NY) -- i.e. `pre_takes_lon_high` in ny_session_lab.py / nylab --
             the 09:30 -> 16:00 NY drive (`ny_drive`) is forced negative by adding a downward
             ramp to those bars. The pipeline MUST find this edge (AT-02, hit >= 0.58).
  twoera  -- identical random-walk engine to `clean` (still NO real day-to-day edge -- no
             condition genuinely predicts any outcome), EXCEPT the whole day's volatility is
             multiplied by 0.6 for the first half of the series and 1.6 for the second half --
             a single step-change "regime shift" partway through, same shape as the real
             calm-2024-vs-busy-2022 artifact RESEARCH_PROTOCOL.md S3 found in H014 (ROADMAP
             5.7.1/5.7.6). The pipeline must find NOTHING here either -- with a PRIOR-ONLY
             threshold (`quantile_prior`). A FULL-SAMPLE `quantile()`/`median()` threshold,
             by contrast, would flag "calm era" days rather than "calm day" days, manufacturing
             a spurious correlation with whatever ELSE differs between the two eras (their own
             volatility level, in particular) -- exactly why the loader rejects it outright
             regardless of what data it's ever run on (AT-05, ROADMAP 5.7.6).

Usage:
    python make_synth.py --variant clean   --years 5 --seed 7
    python make_synth.py --variant planted --years 5 --seed 7
    python make_synth.py --variant planted --years 2 --seed 7 --frac 0.6
    python make_synth.py --variant twoera  --years 5 --seed 7

Output file name (unless --out given): EURUSD_M5_synth_<variant>_<years>y.csv
Columns match what mt5_export.py produces and ny_session_lab.py / nylab expect:
    time, open, high, low, close, tick_volume, spread, real_volume
"""
import argparse

import numpy as np
import pandas as pd

PIP = 0.0001
ANCHOR_END = pd.Timestamp("2025-12-31 23:55")  # fixed anchor -> runs are reproducible


def make_clean_bars(years: float, seed: int, era_multiplier=None) -> pd.DataFrame:
    """Base random-walk M5 bars, server time = NY+7, intraday vol profile, NO edge.

    `era_multiplier` (ROADMAP 5.7.6, AT-05): optional array-like the same length as the bar
    index, multiplied into `vol` before drawing returns -- a step function on it (e.g. 0.6 for
    the first half, 1.6 for the second) reproduces a volatility-regime shift with NO real
    day-to-day predictive edge added anywhere; None (the default) keeps `clean`'s behavior
    byte-identical to before this parameter existed."""
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
    if era_multiplier is not None:
        vol = vol * np.asarray(era_multiplier)

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


def make_twoera_bars(years: float, seed: int) -> pd.DataFrame:
    """ROADMAP 5.7.6 (AT-05): same engine as make_clean_bars -- still NO real day-to-day edge --
    but volatility steps from x0.6 to x1.6 exactly halfway through the series by BAR COUNT (a
    hard regime shift, not a gradual drift, to make the artifact as clear-cut as possible)."""
    rng = np.random.default_rng(seed)
    start = (ANCHOR_END - pd.Timedelta(days=round(years * 365.25))).floor("D")
    idx = pd.date_range(start, ANCHOR_END, freq="5min")  # server time
    ny = idx - pd.Timedelta(hours=7)
    dow, hour = ny.dayofweek, ny.hour
    closed = ((dow == 4) & (hour >= 17)) | (dow == 5) | ((dow == 6) & (hour < 17))
    idx = idx[~closed]
    era_multiplier = np.where(np.arange(len(idx)) < len(idx) // 2, 0.6, 1.6)
    return make_clean_bars(years, seed, era_multiplier=era_multiplier)


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
    ap.add_argument("--variant", choices=["clean", "planted", "twoera"], required=True)
    ap.add_argument("--years", type=float, default=5)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--frac", type=float, default=0.6, help="planted only: fraction of condition days affected")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.variant == "twoera":
        bars = make_twoera_bars(a.years, a.seed)
    else:
        bars = make_clean_bars(a.years, a.seed)
        if a.variant == "planted":
            bars = plant_edge(bars, a.seed, a.frac)

    out = a.out or f"EURUSD_M5_synth_{a.variant}_{a.years:g}y.csv"
    cols = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    bars[cols].to_csv(out, index=False)
    print(f"wrote {out}: {len(bars)} bars, {bars['time'].min()} .. {bars['time'].max()} (server time)")


if __name__ == "__main__":
    main()
