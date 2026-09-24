"""nylab.report.charts -- matplotlib figures for report.html. Ported from ny_session_lab.py."""
from __future__ import annotations

import base64
import io

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None


def fig_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def build(df, d, trades, split_date, pip) -> dict:
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
    prof = ((rng.hi - rng.lo) / pip).groupby("hour").median()
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
