"""
ny_session_lab.py — study the EURUSD New York session on your own MT5 data.

    pip install pandas numpy matplotlib
    python ny_session_lab.py EURUSD_M5_2021-09-24_2026-09-24.csv
    python ny_session_lab.py data.csv --tz ny+7 --oos 0.3 --out my_report

What it does
  1. Converts broker server time -> New York time (handles DST).
  2. Builds one row per trading day with ICT reference levels:
       CBDR (14:00-20:00), Asian range (20:00-00:00), London killzone (02:00-05:00),
       midnight open, 08:30 & 09:30 opens, previous-day high/low, NY session (07:00-16:00).
  3. DESCRIBES the NY session: when the high/low of the day forms, range by hour,
     how often London/Asia/PDH/PDL levels get raided, ADR consumption, SD projections.
  4. TESTS a battery of hypotheses with honest statistics:
       hit rate vs the sample's own baseline, z-score, in-sample vs out-of-sample,
       Bonferroni correction for the number of hypotheses tested.
  5. BACKTESTS one example rule-based model (London-high/low sweep reversal in the NY AM window)
     in R-multiples, with costs, confidence intervals and IS/OOS split. Edit its rules in CONFIG.
  6. Writes report.html + days.csv + trades.csv to the output folder.

Nothing here predicts the future. It tells you what DID happen, how reliably, and whether
it survived data it wasn't fitted on. See the Strategy Development Guide (PDF) for how to use it.
"""
import argparse
import base64
import io
import math
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

# ------------------------------------------------------------------ CONFIG (edit freely)
CONFIG = dict(
    pip=0.0001,
    # windows in NY hours; a trading day starts 17:00 NY the previous calendar day
    cbdr=(14, 20), asia=(20, 24), london_kz=(2, 5), pre_ny=(7, 9.5), ny=(7, 16), ny_am_kz=(7, 10),
    # example model: sweep of London KZ high/low, then M5 close back inside -> fade
    model_window=(8.5, 11.0),      # entries allowed 08:30-11:00 NY
    model_max_bars_after_sweep=6,  # close back inside within N bars of the first poke
    model_stop_buffer_pips=1.0,
    model_rr=2.0,                  # fixed target in R (set None to target the opposite London extreme)
    model_time_exit=12.0,          # flat by 12:00 NY
    default_cost_pips=1.0,         # round-trip spread+commission+slippage if data has no spread column
)


# ------------------------------------------------------------------ time handling
def to_new_york(ts: pd.Series, mode: str) -> pd.Series:
    """Convert naive broker-server timestamps to naive New York timestamps."""
    if mode == "ny+7":           # 'NY-close' brokers: server = NY + 7h all year (UTC+2 / UTC+3)
        return ts - pd.Timedelta(hours=7)
    if mode == "ny":
        return ts
    if mode.startswith("utc"):   # fixed offset servers: utc, utc+2, utc-5 ...
        off = float(mode[3:] or 0)
        utc = (ts - pd.Timedelta(hours=off)).dt.tz_localize("UTC")
        return utc.dt.tz_convert("America/New_York").dt.tz_localize(None)
    raise ValueError("--tz must be auto, ny+7, ny, utc or utc+N")


def detect_tz(ts: pd.Series) -> str:
    """Guess server convention from the hour the market re-opens after the weekend."""
    gaps = ts.diff() > pd.Timedelta(hours=30)
    hours = ts[gaps].dt.hour
    if len(hours) < 4:
        return "ny+7"
    h = int(hours.mode().iloc[0])
    if h in (0, 1):
        return "ny+7"                 # Sunday 17:00 NY == 00:00 server
    if h in (21, 22):
        return "utc"
    if h in (23,):
        return "utc+1"
    return "ny+7"


# ------------------------------------------------------------------ loading
def load(path, tz):
    df = pd.read_csv(path)
    cols = {c.lower().strip("<>"): c for c in df.columns}
    if "time" not in cols and "date" in cols:                       # MT5 'Export bars' format
        tcol = pd.to_datetime(df[cols["date"]].astype(str) + " " + df[cols.get("time", cols["date"])].astype(str))
    else:
        tcol = df[cols["time"]]
        tcol = pd.to_datetime(tcol, unit="s") if np.issubdtype(tcol.dtype, np.number) else pd.to_datetime(tcol)
    out = pd.DataFrame({"server": tcol})
    for k in ("open", "high", "low", "close"):
        out[k] = df[cols[k]].astype(float)
    if "spread" in cols:
        out["spread_pts"] = df[cols["spread"]].astype(float)
    out = out.dropna().sort_values("server").drop_duplicates("server").reset_index(drop=True)
    mode = detect_tz(out["server"]) if tz == "auto" else tz
    out["ny"] = to_new_york(out["server"], mode)
    bar = out["server"].diff().dt.total_seconds().div(60).mode().iloc[0]
    # trading day: starts 17:00 NY of the previous calendar day
    out["td"] = (out["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    out["h"] = (out["ny"] - (out["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7  # hours on NY clock, can be negative (prev evening)
    out = out[out["td"].dt.dayofweek < 5]                          # Mon-Fri trading days
    return out, mode, bar


# ------------------------------------------------------------------ per-day table
def window(df, lo, hi, name):
    sub = df[(df.h >= lo) & (df.h < hi)]
    g = sub.groupby("td")
    r = pd.DataFrame({
        f"{name}_open": g["open"].first(), f"{name}_high": g["high"].max(),
        f"{name}_low": g["low"].min(), f"{name}_close": g["close"].last(),
        f"{name}_hi_t": sub.loc[g["high"].idxmax(), ["td", "h"]].set_index("td")["h"],
        f"{name}_lo_t": sub.loc[g["low"].idxmin(), ["td", "h"]].set_index("td")["h"],
    })
    return r


def open_at(df, hour, name):
    sub = df[(df.h >= hour) & (df.h < hour + 0.5)]
    return sub.groupby("td")["open"].first().rename(name)


def first_cross(df, lo, hi, level_series, above=True):
    """First NY-clock hour inside [lo,hi) when price trades beyond a per-day level."""
    sub = df[(df.h >= lo) & (df.h < hi)].join(level_series.rename("lvl"), on="td")
    hit = sub[sub.high > sub.lvl] if above else sub[sub.low < sub.lvl]
    return hit.groupby("td")["h"].first()


def build_days(df, C):
    pip = C["pip"]
    day = window(df, -7, 17, "day")
    # CBDR spans the day boundary: 14:00-17:00 previous td + 17:00-20:00 current td (h -3..-4 hmm) -> use absolute NY time
    ny = df.set_index("ny")
    parts = [day,
             window(df, C["asia"][0] - 24, C["asia"][1] - 24, "asia"),
             window(df, *C["london_kz"], "lon"),
             window(df, *C["pre_ny"], "preny"),
             window(df, *C["ny"], "ny"),
             window(df, *C["ny_am_kz"], "nyam"),
             open_at(df, 0, "mid_open"), open_at(df, 8.5, "o0830"), open_at(df, 9.5, "o0930")]
    d = pd.concat(parts, axis=1).sort_index()
    # CBDR (14:00-20:00 NY ending inside this td's evening)
    cb = []
    for td in d.index:
        t0 = td - pd.Timedelta(hours=7)                    # 17:00 NY previous day
        s = ny.loc[t0 - pd.Timedelta(hours=3): t0 + pd.Timedelta(hours=3) - pd.Timedelta(seconds=1)]
        cb.append((s.high.max(), s.low.min()) if len(s) else (np.nan, np.nan))
    d["cbdr_high"], d["cbdr_low"] = zip(*cb)
    d["pdh"], d["pdl"] = d["day_high"].shift(1), d["day_low"].shift(1)
    d["day_range"] = (d.day_high - d.day_low) / pip
    d["adr5"] = d["day_range"].shift(1).rolling(5).mean()
    d["adr20"] = d["day_range"].shift(1).rolling(20).mean()
    d["asia_range"] = (d.asia_high - d.asia_low) / pip
    d["lon_range"] = (d.lon_high - d.lon_low) / pip
    d["ny_range"] = (d.ny_high - d.ny_low) / pip
    d["cbdr_range"] = (d.cbdr_high - d.cbdr_low) / pip
    # range consumed before NY open
    pre = window(df, -7, 9.5, "tilopen")
    d = d.join(pre[["tilopen_high", "tilopen_low"]])
    d["adr_used_0930"] = (d.tilopen_high - d.tilopen_low) / pip / d.adr5
    # raids during NY session (07-16)
    for lvl, col, above in [("lon_high", "ny_takes_lon_high", True), ("lon_low", "ny_takes_lon_low", False),
                            ("pdh", "ny_takes_pdh", True), ("pdl", "ny_takes_pdl", False),
                            ("asia_high", "ny_takes_asia_high", True), ("asia_low", "ny_takes_asia_low", False)]:
        t = first_cross(df, *C["ny"], d[lvl], above)
        d[col] = d.index.isin(t.index)
        d[col + "_t"] = t
    # pre-NY raids (07:00-09:30)
    for lvl, col, above in [("lon_high", "pre_takes_lon_high", True), ("lon_low", "pre_takes_lon_low", False),
                            ("pdh", "pre_takes_pdh", True), ("pdl", "pre_takes_pdl", False)]:
        t = first_cross(df, *C["pre_ny"], d[lvl], above)
        d[col] = d.index.isin(t.index)
    # directions
    d["lon_dir"] = np.sign(d.lon_close - d.lon_open)
    d["preny_dir"] = np.sign(d.preny_close - d.preny_open)
    d["ny_drive"] = np.sign(d.ny_close - d.o0930)              # 09:30 -> 16:00
    d["newshr_dir"] = np.sign(d.o0930 - d.o0830)               # 08:30 -> 09:30
    d["day_dir"] = np.sign(d.day_close - d.day_open)
    d["prev_day_dir"] = d["day_dir"].shift(1)
    # NY close vs London extremes after a raid
    d["ny_close_back_below_lon_high"] = d.ny_takes_lon_high & (d.ny_close < d.lon_high)
    d["ny_close_back_above_lon_low"] = d.ny_takes_lon_low & (d.ny_close > d.lon_low)
    # Asian range SD projections reached in NY
    ar = d.asia_high - d.asia_low
    for k in (1, 2, 2.5):
        d[f"ny_hits_asia_+{k}sd"] = d.ny_high >= d.asia_high + k * ar
        d[f"ny_hits_asia_-{k}sd"] = d.ny_low <= d.asia_low - k * ar
    d["dow"] = d.index.dayofweek
    d["ny_forms_day_high"] = d.ny_high >= d.day_high
    d["ny_forms_day_low"] = d.ny_low <= d.day_low
    return d.dropna(subset=["ny_open", "lon_open", "o0930", "ny_close"])


# ------------------------------------------------------------------ statistics
def ztest(k, n, p0):
    if n == 0 or p0 in (0, 1):
        return np.nan, np.nan
    p = k / n
    z = (p - p0) / math.sqrt(p0 * (1 - p0) / n)
    pval = math.erfc(abs(z) / math.sqrt(2))
    return z, pval


def ci(k, n):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    h = 1.96 * math.sqrt(p * (1 - p) / n)
    return (max(0, p - h), min(1, p + h))


def hypotheses(d, split_date):
    """Each: (name, condition mask, outcome mask, baseline outcome mask over ALL days)."""
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
        ("NY raids London high -> NY closes back below it", d.ny_takes_lon_high, d.ny_close < d.lon_high, pd.Series(True, index=d.index) & (d.ny_close < d.lon_high) | True),
    ]
    # last row: baseline for a 'failed breakout' is ill-defined; use 50% as the neutral reference
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
        rows.append(dict(hypothesis=name, n=n, hit=k / n if n else np.nan, baseline=p0,
                         ci_lo=ci(k, n)[0], ci_hi=ci(k, n)[1], z=z, p=pv,
                         bonferroni_sig=(pv < 0.05 / m) if n else False,
                         is_hit=ki / ni if ni else np.nan, oos_hit=ko / no if no else np.nan, oos_n=no,
                         oos_holds=(no >= 20 and ni > 0 and (ki / ni - p0) * (ko / no - p0) > 0 and abs(ko / no - p0) >= 0.03)))
    return pd.DataFrame(rows), m


# ------------------------------------------------------------------ example model backtest
def backtest(df, d, C):
    pip = C["pip"]
    lo_w, hi_w = C["model_window"]
    cost_default = C["default_cost_pips"] * pip
    trades = []
    bars = df[(df.h >= lo_w) & (df.h < C["model_time_exit"])]
    for td, g in bars.groupby("td"):
        if td not in d.index:
            continue
        L_hi, L_lo = d.at[td, "lon_high"], d.at[td, "lon_low"]
        if not np.isfinite(L_hi):
            continue
        g = g.reset_index(drop=True)
        trade = None
        for side in ("short", "long"):
            poke = g[(g.h < hi_w) & ((g.high > L_hi) if side == "short" else (g.low < L_lo))]
            if poke.empty:
                continue
            i0 = poke.index[0]
            for j in range(i0, min(i0 + C["model_max_bars_after_sweep"] + 1, len(g))):
                if g.at[j, "h"] >= hi_w:
                    break
                back_inside = g.at[j, "close"] < L_hi if side == "short" else g.at[j, "close"] > L_lo
                if back_inside:
                    ext = g.loc[i0:j, "high"].max() if side == "short" else g.loc[i0:j, "low"].min()
                    cand = dict(td=td, side=side, i=j, entry=g.at[j, "close"], ext=ext)
                    if trade is None or j < trade["i"]:
                        trade = cand
                    break
        if trade is None:
            continue
        side, e, j = trade["side"], trade["entry"], trade["i"]
        spread = (g.at[j, "spread_pts"] * pip / 10) if "spread_pts" in g and np.isfinite(g.at[j, "spread_pts"]) else None
        cost = max(cost_default, (spread or 0) + 0.2 * pip)
        buf = C["model_stop_buffer_pips"] * pip
        stop = trade["ext"] + buf if side == "short" else trade["ext"] - buf
        risk = abs(e - stop)
        if risk < 2 * pip:           # skip micro-stops: noise, unrealistic fills
            continue
        if C["model_rr"]:
            tgt = e - C["model_rr"] * risk if side == "short" else e + C["model_rr"] * risk
        else:
            tgt = L_lo if side == "short" else L_hi
        exit_px, reason = None, "time"
        for k in range(j + 1, len(g)):
            hi, lo = g.at[k, "high"], g.at[k, "low"]
            hit_stop = hi >= stop if side == "short" else lo <= stop
            hit_tgt = lo <= tgt if side == "short" else hi >= tgt
            if hit_stop:                   # conservative: stop wins ties inside one bar
                exit_px, reason = stop, "stop"; break
            if hit_tgt:
                exit_px, reason = tgt, "target"; break
        if exit_px is None:
            exit_px = g["close"].iloc[-1]
        pnl = (e - exit_px) if side == "short" else (exit_px - e)
        trades.append(dict(td=td, side=side, entry_time_ny=f"{int(g.at[j,'h']):02d}:{int(round((g.at[j,'h']%1)*60)):02d}",
                           entry=e, stop=stop, target=tgt, exit=exit_px, reason=reason,
                           risk_pips=risk / pip, R_gross=pnl / risk, R_net=(pnl - cost) / risk, cost_R=cost / risk))
    return pd.DataFrame(trades)


def r_stats(r):
    r = pd.Series(r).dropna()
    n = len(r)
    if n == 0:
        return dict(n=0)
    wins, losses = r[r > 0], r[r <= 0]
    sd = r.std(ddof=1) if n > 1 else np.nan
    eq = r.cumsum()
    dd = (eq.cummax() - eq).max()
    streak = best = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        best = max(best, streak)
    se = sd / math.sqrt(n) if n > 1 else np.nan
    return dict(n=n, win_rate=len(wins) / n, expectancy=r.mean(), ci_lo=r.mean() - 1.96 * se, ci_hi=r.mean() + 1.96 * se,
                t=r.mean() / se if se else np.nan,
                profit_factor=wins.sum() / abs(losses.sum()) if losses.sum() != 0 else np.inf,
                sqn=math.sqrt(min(n, 100)) * r.mean() / sd if sd else np.nan,
                total_R=r.sum(), max_dd_R=dd, longest_losing_streak=best)


# ------------------------------------------------------------------ report
def fig_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def charts(df, d, trades, split_date):
    if plt is None:
        return {}
    out = {}
    hrs = np.arange(7, 16)
    fig, ax = plt.subplots(figsize=(8, 3.2))
    hh = d.ny_hi_t.dropna().astype(int).clip(7, 15).value_counts().reindex(hrs, fill_value=0) / len(d)
    ll = d.ny_lo_t.dropna().astype(int).clip(7, 15).value_counts().reindex(hrs, fill_value=0) / len(d)
    ax.bar(hrs - 0.2, hh * 100, 0.4, label="NY session HIGH formed", color="#d23950")
    ax.bar(hrs + 0.2, ll * 100, 0.4, label="NY session LOW formed", color="#119469")
    ax.set_xticks(hrs); ax.set_xticklabels([f"{h}:00" for h in hrs]); ax.set_ylabel("% of days"); ax.legend(fontsize=8)
    ax.set_title("When does the NY session (07:00-16:00) make its high and low?", fontsize=10)
    out["extremes"] = fig_b64(fig)

    sub = df[(df.h >= 0) & (df.h < 17)].copy()
    sub["hour"] = sub.h.astype(int)
    rng = sub.groupby(["td", "hour"]).agg(hi=("high", "max"), lo=("low", "min"))
    prof = ((rng.hi - rng.lo) / CONFIG["pip"]).groupby("hour").median()
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(prof.index, prof.values, color=["#b87a00" if 7 <= h < 11 else "#9aa6bd" for h in prof.index])
    ax.set_xticks(prof.index); ax.set_xticklabels([f"{h}" for h in prof.index]); ax.set_xlabel("NY hour")
    ax.set_ylabel("median range (pips)"); ax.set_title("Volatility profile: median range of each hour (NY time)", fontsize=10)
    out["profile"] = fig_b64(fig)

    if len(trades):
        fig, ax = plt.subplots(figsize=(8, 3.2))
        eq = trades.R_net.cumsum().values
        ax.plot(range(1, len(eq) + 1), eq, color="#2f73d6")
        ax.plot(range(1, len(eq) + 1), trades.R_gross.cumsum().values, color="#9aa6bd", lw=1, ls="--", label="before costs")
        cut = (trades.td < split_date).sum()
        ax.axvline(cut + 0.5, color="#b87a00", ls=":", label="in-sample | out-of-sample")
        ax.axhline(0, color="#ccc", lw=0.8)
        ax.set_xlabel("trade #"); ax.set_ylabel("cumulative R"); ax.legend(fontsize=8)
        ax.set_title("Example model equity curve (net of costs)", fontsize=10)
        out["equity"] = fig_b64(fig)
    return out


def pct(x):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x*100:.1f}%"


def num(x, f="{:.2f}"):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f.format(x)


def html_report(meta, d, H, m, trades, st_all, st_is, st_oos, figs):
    css = """body{font-family:Segoe UI,Inter,Arial,sans-serif;max-width:980px;margin:30px auto;padding:0 18px;color:#1d2433;line-height:1.55}
h1{color:#0f1a2e;margin-bottom:4px}h2{color:#0f1a2e;border-bottom:2px solid #e8c77a;padding-bottom:4px;margin-top:34px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}th{background:#0f1a2e;color:#fff;text-align:left;padding:6px}
td{border-bottom:1px solid #e3e6ee;padding:5px 6px}tr:nth-child(even) td{background:#f6f7fa}.box{padding:12px 14px;border-left:4px solid;border-radius:6px;margin:14px 0}
.warn{background:#fcecee;border-color:#c8354b}.info{background:#eef4fd;border-color:#2f73d6}.good{background:#eaf7f1;border-color:#119469}
.y{color:#119469;font-weight:700}.n{color:#9aa6bd}.muted{color:#5e6678;font-size:13px}img{max-width:100%;border:1px solid #e3e6ee;border-radius:8px;margin:8px 0}"""
    D = d
    n = len(D)
    desc = [
        ("NY session makes the high of the trading day", D.ny_forms_day_high.mean()),
        ("NY session makes the low of the trading day", D.ny_forms_day_low.mean()),
        ("NY raids London KZ high", D.ny_takes_lon_high.mean()),
        ("NY raids London KZ low", D.ny_takes_lon_low.mean()),
        ("NY raids BOTH London extremes", (D.ny_takes_lon_high & D.ny_takes_lon_low).mean()),
        ("NY raids previous-day high (PDH)", D.ny_takes_pdh.mean()),
        ("NY raids previous-day low (PDL)", D.ny_takes_pdl.mean()),
        ("NY raids Asian high", D.ny_takes_asia_high.mean()),
        ("NY raids Asian low", D.ny_takes_asia_low.mean()),
        ("...of days NY raids London high, it CLOSES back below it", D.ny_close_back_below_lon_high.sum() / max(1, D.ny_takes_lon_high.sum())),
        ("...of days NY raids London low, it CLOSES back above it", D.ny_close_back_above_lon_low.sum() / max(1, D.ny_takes_lon_low.sum())),
        ("NY reaches Asian range +1 SD", D["ny_hits_asia_+1sd"].mean()),
        ("NY reaches Asian range −1 SD", D["ny_hits_asia_-1sd"].mean()),
        ("NY reaches Asian range ±2 SD (either side)", (D["ny_hits_asia_+2sd"] | D["ny_hits_asia_-2sd"]).mean()),
    ]
    rng = [("Day (17:00–17:00)", D.day_range), ("Asia 20:00–00:00", D.asia_range), ("London KZ 02:00–05:00", D.lon_range),
           ("NY 07:00–16:00", D.ny_range), ("CBDR 14:00–20:00", D.cbdr_range)]
    dow = D.groupby("dow").agg(days=("ny_range", "size"), ny_range=("ny_range", "median"),
                               up=("ny_drive", lambda s: (s > 0).mean()))
    names = ["Mon", "Tue", "Wed", "Thu", "Fri"]

    h = [f"<html><head><meta charset='utf-8'><title>NY Session Lab — {meta['file']}</title><style>{css}</style></head><body>"]
    h.append(f"<h1>EURUSD New York Session Lab</h1><div class='muted'>{meta['file']} · {meta['first']} → {meta['last']} · "
             f"{n} trading days · {meta['bar']:.0f}-min bars · server time mode <b>{meta['tz']}</b> · "
             f"in-sample before {meta['split']}, out-of-sample after</div>")
    h.append("<div class='box info'><b>How to read this report.</b> Section 1–2 describe what happened (facts, not signals). "
             "Section 3 tests specific ideas against the market's own baseline; only rows that are <b>Bonferroni-significant AND hold out-of-sample</b> "
             "deserve further work. Section 4 is an example of turning an idea into rules and R-multiples — edit CONFIG to test your own. "
             "Before trusting ANY timing statistic, check Section 0: if the volatility profile doesn't spike at 08:30 and 09:30–11:00 NY, your --tz setting is wrong.</div>")
    h.append("<h2>0 · Sanity check — volatility by NY hour</h2>")
    if "profile" in figs:
        h.append(f"<img src='data:image/png;base64,{figs['profile']}'>")
    h.append("<p class='muted'>Expected shape for EURUSD: a bump at London open (02:00–04:00), the biggest bars 08:00–11:00, a fade into lunch. "
             "If the peak sits somewhere else (e.g. 15:00–18:00), rerun with --tz utc or --tz utc+2.</p>")

    h.append("<h2>1 · Session ranges (pips)</h2><table><tr><th>Window (NY)</th><th>Median</th><th>Mean</th><th>20th pct</th><th>80th pct</th></tr>")
    for nm, s in rng:
        h.append(f"<tr><td>{nm}</td><td>{s.median():.1f}</td><td>{s.mean():.1f}</td><td>{s.quantile(.2):.1f}</td><td>{s.quantile(.8):.1f}</td></tr>")
    h.append(f"</table><p class='muted'>Median ADR(5) share already used by 09:30 NY: {pct(D.adr_used_0930.median())}.</p>")

    h.append("<h2>2 · What the NY session does</h2>")
    if "extremes" in figs:
        h.append(f"<img src='data:image/png;base64,{figs['extremes']}'>")
    h.append("<table><tr><th>Observation</th><th>Frequency</th></tr>")
    for nm, v in desc:
        h.append(f"<tr><td>{nm}</td><td>{pct(v)}</td></tr>")
    h.append("</table><table><tr><th>Day</th><th>Days</th><th>Median NY range</th><th>NY drive up %</th></tr>")
    for i, r in dow.iterrows():
        h.append(f"<tr><td>{names[i]}</td><td>{int(r.days)}</td><td>{r.ny_range:.1f}</td><td>{pct(r.up)}</td></tr>")
    h.append("</table>")

    h.append(f"<h2>3 · Hypothesis tests ({m} ideas tested)</h2>"
             f"<p class='muted'>Hit = how often the outcome happened when the condition was true. Baseline = how often the same outcome happens on ALL days. "
             f"An idea matters only if hit is meaningfully above baseline. Bonferroni threshold: p &lt; {0.05/m:.4f}. "
             f"'Holds OOS' = still ≥3 points better than baseline on the unseen out-of-sample period (≥20 cases).</p>")
    h.append("<table><tr><th>Hypothesis</th><th>N</th><th>Hit</th><th>Baseline</th><th>95% CI</th><th>z</th><th>Bonf.</th><th>IS hit</th><th>OOS hit (n)</th><th>Holds OOS</th></tr>")
    for _, r in H.iterrows():
        h.append(f"<tr><td>{r.hypothesis}</td><td>{r.n}</td><td>{pct(r.hit)}</td><td>{pct(r.baseline)}</td>"
                 f"<td>{pct(r.ci_lo)}–{pct(r.ci_hi)}</td><td>{num(r.z)}</td>"
                 f"<td class='{'y' if r.bonferroni_sig else 'n'}'>{'YES' if r.bonferroni_sig else 'no'}</td>"
                 f"<td>{pct(r.is_hit)}</td><td>{pct(r.oos_hit)} ({r.oos_n})</td>"
                 f"<td class='{'y' if r.oos_holds else 'n'}'>{'YES' if r.oos_holds else 'no'}</td></tr>")
    h.append("</table>")
    strong = H[H.bonferroni_sig & H.oos_holds]
    if len(strong):
        h.append("<div class='box good'><b>Candidates worth deeper research:</b><ul>" +
                 "".join(f"<li>{x}</li>" for x in strong.hypothesis) +
                 "</ul>A candidate is a <i>starting point</i>, not a strategy: it still needs an entry, a stop, a target and a cost-inclusive backtest (Strategy Guide Steps 4–7).</div>")
    else:
        h.append("<div class='box warn'><b>No idea passed both filters.</b> That is a normal, useful result: it means none of these simple "
                 "conditions is a reliable directional edge on its own. Edges usually come from combining a context filter with a precise "
                 "entry model (Section 4) — and some of these may still work as <i>filters</i>.</div>")

    h.append("<h2>4 · Example model — London KZ sweep reversal (NY AM)</h2>")
    C = CONFIG
    h.append(f"<p class='muted'>Rules: between {C['model_window'][0]:g}h and {C['model_window'][1]:g}h NY, price trades beyond the London killzone "
             f"high (low); within {C['model_max_bars_after_sweep']} bars an M5 candle closes back inside → enter at that close, opposite direction. "
             f"Stop {C['model_stop_buffer_pips']:g} pip beyond the sweep extreme. Target {('%gR' % C['model_rr']) if C['model_rr'] else 'the opposite London extreme'}. "
             f"Flat by {C['model_time_exit']:g}:00. One trade per day. Costs ≥ {C['default_cost_pips']:g} pip round trip (or the recorded spread + 0.2). "
             "If stop and target are touched in the same bar, the stop is assumed (conservative).</p>")
    if st_all.get("n", 0):
        h.append("<table><tr><th></th><th>Trades</th><th>Win rate</th><th>Expectancy (R, net)</th><th>95% CI</th><th>t</th><th>Profit factor</th><th>SQN</th><th>Max DD (R)</th><th>Worst streak</th></tr>")
        for nm, s in [("All", st_all), ("In-sample", st_is), ("Out-of-sample", st_oos)]:
            if s.get("n", 0):
                h.append(f"<tr><td>{nm}</td><td>{s['n']}</td><td>{pct(s['win_rate'])}</td><td>{num(s['expectancy'],'{:+.3f}')}</td>"
                         f"<td>{num(s['ci_lo'],'{:+.2f}')} to {num(s['ci_hi'],'{:+.2f}')}</td><td>{num(s['t'])}</td>"
                         f"<td>{num(s['profit_factor'])}</td><td>{num(s['sqn'])}</td><td>{num(s['max_dd_R'],'{:.1f}')}</td><td>{s['longest_losing_streak']}</td></tr>")
        h.append("</table>")
        if "equity" in figs:
            h.append(f"<img src='data:image/png;base64,{figs['equity']}'>")
        verdict = ("<div class='box good'><b>The OOS confidence interval is above zero.</b> Promising — next: vary one parameter at a time, "
                   "check each year separately, then forward-test on demo (Guide Steps 7–9).</div>") if st_oos.get("n", 0) and st_oos["ci_lo"] > 0 else \
                  ("<div class='box warn'><b>Not proven.</b> The out-of-sample confidence interval includes zero (or is negative). "
                   "Do NOT trade this as-is. Use it as a template: change one rule, re-run, and keep a log of every variant you tried "
                   "(that count is your 'm' for the multiple-testing correction).</div>")
        h.append(verdict)
        yearly = trades.assign(y=pd.to_datetime(trades.td).dt.year).groupby("y").R_net.agg(["size", "mean", "sum"])
        h.append("<table><tr><th>Year</th><th>Trades</th><th>Expectancy (R)</th><th>Total R</th></tr>" +
                 "".join(f"<tr><td>{y}</td><td>{int(r['size'])}</td><td>{r['mean']:+.3f}</td><td>{r['sum']:+.1f}</td></tr>" for y, r in yearly.iterrows()) + "</table>")
    else:
        h.append("<p>No trades were generated with the current rules.</p>")
    h.append("<h2>Files</h2><p class='muted'><b>days.csv</b> — one row per day with every level and flag above (open it in Excel and filter). "
             "<b>trades.csv</b> — every example-model trade with entry, stop, target, exit and R. "
             "Always open 10–20 of those trades on your MT5 chart and check the rules did what you think they did.</p></body></html>")
    return "\n".join(h)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="EURUSD NY session research lab")
    ap.add_argument("csv")
    ap.add_argument("--tz", default="auto", help="auto | ny+7 | utc | utc+2 | ny")
    ap.add_argument("--oos", type=float, default=0.3, help="fraction of most recent days held out (default 0.3)")
    ap.add_argument("--out", default="ny_lab_report")
    a = ap.parse_args()

    print("Loading", a.csv)
    df, mode, bar = load(a.csv, a.tz)
    if bar > 15:
        sys.exit(f"Bars look like {bar:.0f}-minute. Use M1 or M5 data for session analysis.")
    print(f"  {len(df):,} bars, {bar:.0f}-min, server-time mode: {mode}")
    d = build_days(df, CONFIG)
    if len(d) < 60:
        sys.exit(f"Only {len(d)} complete trading days — need at least ~60 (ideally 250+).")
    split_date = d.index[int(len(d) * (1 - a.oos))]
    print(f"  {len(d)} trading days  |  out-of-sample from {split_date:%Y-%m-%d}")

    H, m = hypotheses(d, split_date)
    trades = backtest(df, d, CONFIG)
    st_all = r_stats(trades.R_net) if len(trades) else {"n": 0}
    st_is = r_stats(trades[trades.td < split_date].R_net) if len(trades) else {"n": 0}
    st_oos = r_stats(trades[trades.td >= split_date].R_net) if len(trades) else {"n": 0}

    os.makedirs(a.out, exist_ok=True)
    figs = charts(df, d, trades, split_date)
    meta = dict(file=os.path.basename(a.csv), first=f"{d.index[0]:%Y-%m-%d}", last=f"{d.index[-1]:%Y-%m-%d}",
                tz=mode, bar=bar, split=f"{split_date:%Y-%m-%d}")
    open(os.path.join(a.out, "report.html"), "w", encoding="utf-8").write(
        html_report(meta, d, H, m, trades, st_all, st_is, st_oos, figs))
    d.to_csv(os.path.join(a.out, "days.csv"))
    trades.to_csv(os.path.join(a.out, "trades.csv"), index=False)
    H.to_csv(os.path.join(a.out, "hypotheses.csv"), index=False)

    print("\nHypotheses passing Bonferroni AND out-of-sample:",
          ", ".join(H[H.bonferroni_sig & H.oos_holds].hypothesis) or "none")
    if st_all.get("n"):
        print(f"Example model: {st_all['n']} trades, E = {st_all['expectancy']:+.3f}R net, "
              f"OOS E = {st_oos.get('expectancy', float('nan')):+.3f}R (CI {st_oos.get('ci_lo', float('nan')):+.2f} to {st_oos.get('ci_hi', float('nan')):+.2f})")
    print(f"\nReport: {os.path.abspath(os.path.join(a.out, 'report.html'))}")


if __name__ == "__main__":
    main()
