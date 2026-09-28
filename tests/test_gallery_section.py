"""ROADMAP 8.2: nylab.report.gallery_section -- trade gallery selection + HTML rendering."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab.report import gallery_section


def _mk_trades(n, split_date):
    tds = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "td": tds, "side": ["long"] * n, "entry_time_h": [8.0] * n,
        "entry": [1.1] * n, "stop": [1.09] * n, "target": [1.12] * n, "exit": [1.12] * n,
        "reason": ["target"] * n, "risk_pips": [10.0] * n,
        "R_gross": rng.normal(0, 1, n), "R_net": rng.normal(0, 1, n) - 0.1, "cost_R": [0.1] * n,
    })


def test_select_gallery_trades_only_pulls_from_oos():
    n = 40
    trades = _mk_trades(n, None)
    split_date = trades["td"].iloc[20]
    sel = gallery_section.select_gallery_trades(trades, split_date, n_random=10, n_best=3, n_worst=3, seed=1)
    for group in sel.values():
        assert (group["td"] >= split_date).all()


def test_select_gallery_trades_best_and_worst_are_correct_extremes():
    n = 40
    trades = _mk_trades(n, None)
    split_date = trades["td"].iloc[0]  # everything is OOS
    sel = gallery_section.select_gallery_trades(trades, split_date, n_random=5, n_best=3, n_worst=3, seed=1)
    assert list(sel["best"]["R_net"]) == sorted(trades["R_net"], reverse=True)[:3]
    assert list(sel["worst"]["R_net"]) == sorted(trades["R_net"])[:3]


def test_select_gallery_trades_random_sample_size_capped_by_available_oos():
    n = 5
    trades = _mk_trades(n, None)
    split_date = trades["td"].iloc[0]
    sel = gallery_section.select_gallery_trades(trades, split_date, n_random=20, n_best=2, n_worst=2, seed=2)
    assert len(sel["random"]) == 5  # capped, not an error, even though n_random=20 > available


def test_select_gallery_trades_empty_when_no_oos_trades():
    n = 10
    trades = _mk_trades(n, None)
    split_date = trades["td"].iloc[-1] + pd.Timedelta(days=100)  # nothing is OOS
    sel = gallery_section.select_gallery_trades(trades, split_date)
    assert all(len(v) == 0 for v in sel.values())


def test_select_gallery_trades_handles_totally_empty_trades_df():
    trades = pd.DataFrame(columns=["td", "R_net"])
    sel = gallery_section.select_gallery_trades(trades, pd.Timestamp("2024-01-01"))
    assert all(len(v) == 0 for v in sel.values())


def test_select_gallery_trades_preserves_original_positional_index():
    n = 30
    trades = _mk_trades(n, None)
    split_date = trades["td"].iloc[10]
    sel = gallery_section.select_gallery_trades(trades, split_date, n_random=5, n_best=2, n_worst=2, seed=3)
    for group in sel.values():
        for idx in group.index:
            # the index label must still refer to the SAME row in the original `trades` df.
            pd.testing.assert_series_equal(trades.loc[idx], group.loc[idx], check_names=False)


def test_build_produces_html_with_replay_links_and_no_crash_on_empty_gallery():
    n = 10
    trades = _mk_trades(n, None)
    split_date = trades["td"].iloc[-1] + pd.Timedelta(days=100)  # no OOS -> empty gallery
    html = gallery_section.build(trades, split_date, figs={}, seed=1)
    assert "Trade gallery" in html
    assert "No out-of-sample trades available." in html


def test_build_embeds_replay_deep_links_for_selected_trades():
    n = 20
    trades = _mk_trades(n, None)
    split_date = trades["td"].iloc[0]
    figs = {}  # no chart images needed to check the link text itself
    html = gallery_section.build(trades, split_date, figs, n_random=5, n_best=2, n_worst=2, seed=7)
    assert "Open in replay" in html
    assert "?date=" in html and "until=" in html
