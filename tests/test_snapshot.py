"""ROADMAP 8.1: nylab.report.snapshot -- trade snapshot PNGs for the report.html gallery."""
from __future__ import annotations

import base64

import pandas as pd
import pytest

from nylab.report import snapshot
from nylab.report.charts import THEMES


def _mk_day_bars(td, n=60, start_h=-2.0):
    hs = [start_h + i * (5 / 60) for i in range(n)]
    base = 1.1000
    rows = []
    for i, h in enumerate(hs):
        o = base + i * 0.0001
        c = o + 0.00005
        rows.append((o, max(o, c) + 0.00005, min(o, c) - 0.00005, c))
    return pd.DataFrame({
        "td": [td] * n, "h": hs,
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
    })


def _mk_trade(td, entry_time_h=3.0, side="long"):
    return pd.Series(dict(td=td, side=side, entry_time_h=entry_time_h, entry=1.1010,
                           stop=1.1000, target=1.1030, exit=1.1030, reason="target",
                           risk_pips=10.0, R_gross=2.0, R_net=1.8, cost_R=0.2))


def test_trade_snapshot_fig_returns_a_figure_and_can_be_encoded():
    if snapshot.plt is None:
        pytest.skip("matplotlib not available")
    td = pd.Timestamp("2024-01-02")
    day_bars = _mk_day_bars(td)
    trade = _mk_trade(td)
    for theme, t in THEMES.items():
        fig = snapshot.trade_snapshot_fig(day_bars, trade, t)
        assert fig is not None
        png_b64 = snapshot.fig_b64(fig, bg=t["bg"])
        # a real, non-trivially-sized base64 PNG (fig_b64 already closes the figure).
        raw = base64.b64decode(png_b64)
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(raw) > 500


def test_trade_snapshot_fig_handles_missing_target_gracefully():
    if snapshot.plt is None:
        pytest.skip("matplotlib not available")
    td = pd.Timestamp("2024-01-02")
    day_bars = _mk_day_bars(td)
    trade = _mk_trade(td)
    trade["target"] = None
    fig = snapshot.trade_snapshot_fig(day_bars, trade, THEMES["light"])
    assert fig is not None
    snapshot.plt.close(fig)


def test_trade_snapshot_fig_falls_back_to_full_day_when_window_is_empty():
    if snapshot.plt is None:
        pytest.skip("matplotlib not available")
    td = pd.Timestamp("2024-01-02")
    day_bars = _mk_day_bars(td, n=5, start_h=10.0)
    # entry_time_h far outside the fixture's bar range -> context window is empty -> fallback.
    trade = _mk_trade(td, entry_time_h=-20.0)
    fig = snapshot.trade_snapshot_fig(day_bars, trade, THEMES["dark"])
    assert fig is not None
    snapshot.plt.close(fig)


def test_build_gallery_figs_keys_by_positional_index_and_theme():
    if snapshot.plt is None:
        pytest.skip("matplotlib not available")
    tds = [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    df = pd.concat([_mk_day_bars(td) for td in tds], ignore_index=True)
    trades = pd.DataFrame([_mk_trade(tds[0]).to_dict(), _mk_trade(tds[1]).to_dict()])
    figs = snapshot.build_gallery_figs(df, trades, [0, 1])
    assert set(figs.keys()) == {"trade_0_light", "trade_0_dark", "trade_1_light", "trade_1_dark"}
    for v in figs.values():
        assert isinstance(v, str) and len(v) > 100


def test_build_gallery_figs_skips_a_trade_with_no_matching_day_bars():
    if snapshot.plt is None:
        pytest.skip("matplotlib not available")
    td = pd.Timestamp("2024-01-02")
    df = _mk_day_bars(td)
    orphan_trade = _mk_trade(pd.Timestamp("2099-01-01"))
    trades = pd.DataFrame([orphan_trade.to_dict()])
    figs = snapshot.build_gallery_figs(df, trades, [0])
    assert figs == {}
