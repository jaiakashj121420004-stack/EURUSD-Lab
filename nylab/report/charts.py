"""nylab.report.charts -- matplotlib figures for report.html. Ported from ny_session_lab.py.

design-restyle (2026-09-27, surface B): every chart is now rendered TWICE, once in each of
DESIGN_SYSTEM.md's Porcelain (light) / Espresso (dark) palettes, so report.html's theme toggle
can swap the <img> shown via CSS instead of leaving baked-light charts on a dark page. Palette
hex values are copied from nylab/replay/static/style.css's :root / [data-theme="dark"] blocks --
kept as plain literals here (not shared code) since this module has no CSS to read them from at
report-build time; if the app's tokens change, update THEMES below to match."""
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

# Mirrors nylab/replay/static/style.css's :root (light) and [data-theme="dark"] (dark) tokens.
THEMES = {
    "light": dict(bg="#F0EDE8", text="#2B2822", muted="#6B6459", faint="#968F82", grid="#DDD5C7",
                  bear="#E5484D", bull="#0F9D76", amber="#E39B2F", accent="#0EA5A0"),
    "dark": dict(bg="#1E1B18", text="#EFE9E1", muted="#A79E92", faint="#746B60", grid="#3A342C",
                 bear="#FF6369", bull="#22C39A", amber="#F5B04C", accent="#2DD4BF"),
}


def _style(fig, ax, t):
    """Applies one THEMES[...] palette to a figure/axes' background, spines, ticks and labels."""
    fig.patch.set_facecolor(t["bg"])
    ax.set_facecolor(t["bg"])
    for spine in ax.spines.values():
        spine.set_color(t["grid"])
    ax.tick_params(colors=t["muted"], labelsize=8)
    ax.xaxis.label.set_color(t["muted"])
    ax.yaxis.label.set_color(t["muted"])
    ax.title.set_color(t["text"])
    if ax.get_legend() is not None:
        leg = ax.get_legend()
        leg.get_frame().set_facecolor(t["bg"])
        leg.get_frame().set_edgecolor(t["grid"])
        for txt in leg.get_texts():
            txt.set_color(t["text"])


def fig_b64(fig, bg=None) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=bg or fig.get_facecolor())
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _extremes_fig(d, t):
    hrs = np.arange(7, 16)
    fig, ax = plt.subplots(figsize=(8, 3.2))
    hh = d.ny_hi_t.dropna().astype(int).clip(7, 15).value_counts().reindex(hrs, fill_value=0) / len(d)
    ll = d.ny_lo_t.dropna().astype(int).clip(7, 15).value_counts().reindex(hrs, fill_value=0) / len(d)
    ax.bar(hrs - 0.2, hh * 100, 0.4, label="NY session HIGH formed", color=t["bear"])
    ax.bar(hrs + 0.2, ll * 100, 0.4, label="NY session LOW formed", color=t["bull"])
    ax.set_xticks(hrs); ax.set_xticklabels([f"{h}:00" for h in hrs]); ax.set_ylabel("% of days"); ax.legend(fontsize=8)
    ax.set_title("When does the NY session (07:00-16:00) make its high and low?", fontsize=10)
    _style(fig, ax, t)
    return fig


def _profile_fig(df, pip, t):
    sub = df[(df.h >= 0) & (df.h < 17)].copy()
    sub["hour"] = sub.h.astype(int)
    rng = sub.groupby(["td", "hour"]).agg(hi=("high", "max"), lo=("low", "min"))
    prof = ((rng.hi - rng.lo) / pip).groupby("hour").median()
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(prof.index, prof.values, color=[t["amber"] if 7 <= h < 11 else t["faint"] for h in prof.index])
    ax.set_xticks(prof.index); ax.set_xticklabels([f"{h}" for h in prof.index]); ax.set_xlabel("NY hour")
    ax.set_ylabel("median range (pips)"); ax.set_title("Volatility profile: median range of each hour (NY time)", fontsize=10)
    _style(fig, ax, t)
    return fig


def _equity_fig(trades, split_date, t):
    fig, ax = plt.subplots(figsize=(8, 3.2))
    eq = trades.R_net.cumsum().values
    ax.plot(range(1, len(eq) + 1), eq, color=t["accent"])
    ax.plot(range(1, len(eq) + 1), trades.R_gross.cumsum().values, color=t["faint"], lw=1, ls="--", label="before costs")
    cut = (trades.td < split_date).sum()
    ax.axvline(cut + 0.5, color=t["amber"], ls=":", label="in-sample | out-of-sample")
    ax.axhline(0, color=t["grid"], lw=0.8)
    ax.set_xlabel("trade #"); ax.set_ylabel("cumulative R"); ax.legend(fontsize=8)
    ax.set_title("Example model equity curve (net of costs)", fontsize=10)
    _style(fig, ax, t)
    return fig


def build(df, d, trades, split_date, pip) -> dict:
    if plt is None:
        return {}
    out = {}
    for theme, t in THEMES.items():
        out[f"extremes_{theme}"] = fig_b64(_extremes_fig(d, t), bg=t["bg"])
        out[f"profile_{theme}"] = fig_b64(_profile_fig(df, pip, t), bg=t["bg"])
        if len(trades):
            out[f"equity_{theme}"] = fig_b64(_equity_fig(trades, split_date, t), bg=t["bg"])
    return out
