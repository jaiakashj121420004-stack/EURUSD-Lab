"""Regression tests for the bugs found in the 2026-09-28 audit (docs/PROGRESS.md)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import backtest, robustness
from nylab.report import gallery_section, snapshot


def _v0_style_trades(n=12):
    """Shape of london_sweep_reversal.backtest() output -- what `nylab run` really reports:
    `entry_time_ny` ("HH:MM"), NO `entry_time_h` column."""
    tds = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.default_rng(3)
    return pd.DataFrame({
        "td": tds, "side": ["short"] * n, "entry_time_ny": ["09:40"] * n,
        "entry": [1.1] * n, "stop": [1.101] * n, "target": [1.098] * n, "exit": [1.098] * n,
        "reason": ["target"] * n, "risk_pips": [10.0] * n,
        "R_gross": rng.normal(0, 1, n), "R_net": rng.normal(0, 1, n), "cost_R": [0.1] * n,
    })


def _bars_for(tds):
    rows = []
    for td in tds:
        for i in range(24):
            h = 8.0 + i * 5 / 60
            rows.append(dict(td=td, h=h, open=1.1, high=1.1005, low=1.0995, close=1.1))
    return pd.DataFrame(rows)


def test_entry_hour_reads_either_trade_shape():
    t = _v0_style_trades(1).iloc[0]
    assert snapshot.entry_hour(t) == 9 + 40 / 60
    t2 = t.copy(); t2["entry_time_h"] = 3.25
    assert snapshot.entry_hour(t2) == 3.25


def test_gallery_works_on_v0_style_trades_that_nylab_run_actually_passes():
    """This exact call crashed `python -m nylab run` with KeyError: 'entry_time_h'."""
    trades = _v0_style_trades()
    split = trades["td"].iloc[4]
    df = _bars_for(trades["td"])
    figs = gallery_section.build_figs(df, trades, split, seed=1)
    html = gallery_section.build(trades, split, figs, seed=1)
    assert "until=09:40" in html
    assert any(k.startswith("trade_") for k in figs)


class _LongSignal:
    name, version = "t", "t"
    params = {"window": (8.0, 8.1), "time_exit": 11.0}

    def signals(self, day_bars, day, events):
        e = float(day_bars["close"].iloc[-1])
        return [backtest.Signal(bar_index=len(day_bars) - 1, side="long", entry_price=e,
                                stop_price=e - 0.0010, target_price=e + 0.0030, time_exit_h=11.0)]


def test_delayed_entry_past_the_stop_is_skipped_not_booked_as_a_win():
    """Before the fix: the delay bar closed BELOW the long stop, the delayed 'entry' was taken
    there, the next bar 'hit' the stop (which is ABOVE that entry) and booked a winning trade."""
    td = pd.Timestamp("2024-03-05")
    closes = [1.1000, 1.0980, 1.0980, 1.0980, 1.0980]  # bar 1 closes 20 pips below entry (stop = -10)
    rows = [dict(td=td, h=8.0 + i * 5 / 60, open=c, high=c + 0.0002, low=c - 0.0002, close=c)
            for i, c in enumerate(closes)]
    df = pd.DataFrame(rows)
    d = pd.DataFrame(index=pd.DatetimeIndex([td], name="td"))
    m = robustness.DelayedEntryModel(_LongSignal(), delay_bars=1)
    m.inner.params = {"window": (8.0, 8.3), "time_exit": 11.0}
    m.params = m.inner.params
    trades = backtest.run_backtest(m, df, d, 0.0001, 1.0)
    assert len(trades) == 0
    assert m.skipped_invalid == 1


def test_matrix_family_bh_uses_the_whole_matrix_size_not_just_promoted_cells(tmp_path):
    """H016 (one promoted cell of a 6x6 matrix) came out `candidate` at p=0.098 on real data
    because the within-family BH ran over a family of size 1. With the whole 36-cell family
    counted, a p around 0.05-0.1 must not be BH-significant within the family."""
    from nylab import hyp_engine
    from nylab.hyp_loader import Hypothesis
    # Deterministic: IS = first 300 days. flag on 90 IS days with 38 hits (42%), off on 210 IS
    # days with 66 hits (31%) -> two-proportion p ~= 0.06: "significant" in a family of 1, not
    # in a family of 36.
    idx = pd.bdate_range("2023-01-02", periods=400)
    flag = np.zeros(400, bool); hit = np.zeros(400, bool)
    flag[:90] = True; hit[:38] = True; hit[90:156] = True
    flag[300:330] = True; hit[300:313] = True; hit[330:352] = True  # OOS, same direction
    flag = pd.Series(flag, index=idx); hit = pd.Series(hit, index=idx)
    d = pd.DataFrame({"flag": flag, "hit": hit})
    h = Hypothesis(id="HFAM", version="1.0", title="t", decision_time_h=0.0, condition="flag",
                   outcome="hit", baseline="hit", family="fam", matrix_shape=(6, 6))
    rows, _, _, _ = hyp_engine.evaluate(d, [h], idx[300], run_id="t",
                                        ledger_path=str(tmp_path / "l.csv"))
    r = rows.iloc[0]
    assert 0.01 < r["p"] < 0.10, r["p"]
    assert not r["bh_sig_family"]
    assert r["verdict"] == "weak"
