"""Phase 2 acceptance (REPLAY_TRAINER.md S9 / S7): the no-leak rule, filters, resampling,
the fill engine, and account math. All against the module functions directly -- no HTTP
round trip needed to prove the no-leak property, since api.py has no code path that can
return unrevealed data (it's a filter, not a permission check).
"""
import random
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from nylab import cache as cache_mod  # noqa: E402
from nylab.replay import api, sim  # noqa: E402

CACHE_DIR = ROOT / "tests" / "fixtures" / "_replay_cache"


@pytest.fixture(scope="module")
def store():
    if not (CACHE_DIR / "bars_M5.parquet").exists():
        from nylab import config as cfg
        from nylab import days as days_mod
        from nylab.data import loader, timezones

        csv_path = ROOT / "tests" / "fixtures" / "EURUSD_M5_synth_clean_2y.csv"
        raw = loader.load_bars(str(csv_path))
        raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
        raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
        raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
        raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
        d = days_mod.build_days(raw, cfg.legacy_windows())
        cache_mod.save(raw, d, cache_dir=str(CACHE_DIR))

    bars, days = cache_mod.load(cache_dir=str(CACHE_DIR))
    return api.Store(bars, days)


def test_no_leak_bars_random_sample(store):
    """AT: for 100 random (td, until) pairs, no returned bar is after `until`."""
    tds = list(store.bars_by_td.keys())
    rng = random.Random(7)
    checked = 0
    for _ in range(100):
        td = rng.choice(tds)
        day_bars = store.bars_by_td[td]
        if len(day_bars) < 2:
            continue
        cut = day_bars.iloc[rng.randrange(1, len(day_bars))]
        until = cut["ny"].isoformat()
        result = api.get_bars(store, td.strftime("%Y-%m-%d"), "M5", until, context_days=0)
        for b in result["bars"]:
            assert b["time"] <= int(cut["ny"].timestamp()), "leaked a bar after `until`"
        checked += 1
    assert checked > 50


def test_no_leak_levels_available_at_h(store):
    """AT: a level only appears once the NY hour reaches its documented available_at_h."""
    tds = list(store.days.index)
    rng = random.Random(11)
    for _ in range(100):
        td = rng.choice(tds)
        until = (td + pd.Timedelta(hours=rng.uniform(-6, 16))).isoformat()
        result = api.get_levels(store, td.strftime("%Y-%m-%d"), until)
        if "error" in result:
            continue
        h = result["h"]
        for col in result["levels"]:
            from nylab.days import COLUMN_DOCS
            assert COLUMN_DOCS.get(col, 999) <= h + 1e-9, f"{col} leaked before its available_at_h"


def test_higher_tf_matches_resample_of_revealed_bars(store):
    """AT: the forming H1 candle must equal resampling the M5 bars actually revealed so far."""
    td = list(store.bars_by_td.keys())[10]
    day_bars = store.bars_by_td[td]
    until = day_bars.iloc[len(day_bars) // 2]["ny"]

    m5 = api.get_bars(store, td.strftime("%Y-%m-%d"), "M5", until.isoformat(), context_days=0)["bars"]
    h1 = api.get_bars(store, td.strftime("%Y-%m-%d"), "H1", until.isoformat(), context_days=0)["bars"]

    m5_df = pd.DataFrame(m5)
    m5_df["hour"] = pd.to_datetime(m5_df["time"], unit="s").dt.floor("h")
    manual = m5_df.groupby("hour").agg(open=("open", "first"), high=("high", "max"),
                                        low=("low", "min"), close=("close", "last"))
    last_h1 = h1[-1]
    last_manual = manual.iloc[-1]
    assert abs(last_h1["open"] - last_manual["open"]) < 1e-9
    assert abs(last_h1["high"] - last_manual["high"]) < 1e-9
    assert abs(last_h1["low"] - last_manual["low"]) < 1e-9
    assert abs(last_h1["close"] - last_manual["close"]) < 1e-9


def test_day_filters_are_correct(store):
    rows = api.list_days(store, weekdays=[0], exclude_thin=False)
    assert all(r["weekday"] == 0 for r in rows)
    lon_high_rows = api.list_days(store, exclude_thin=False)
    lon_high_rows = [r for r in lon_high_rows if r["ny_takes_lon_high"]]
    expected = int(store.days["ny_takes_lon_high"].sum())
    assert len(lon_high_rows) == expected


def test_date_jump_is_fast(store):
    """REPLAY_TRAINER.md S9 item 1: date picker jump to any date in < 1s."""
    import time
    tds = list(store.bars_by_td.keys())
    rng = random.Random(3)
    sample = rng.sample(tds, min(20, len(tds)))
    t0 = time.perf_counter()
    for td in sample:
        api.get_bars(store, td.strftime("%Y-%m-%d"), "M5", (td + pd.Timedelta(hours=9.5)).isoformat(), context_days=10)
        api.get_levels(store, td.strftime("%Y-%m-%d"), (td + pd.Timedelta(hours=9.5)).isoformat())
    elapsed = time.perf_counter() - t0
    assert elapsed / len(sample) < 1.0, f"avg jump took {elapsed/len(sample):.3f}s, want < 1s"


def test_fill_engine_conservative_stop_wins_same_bar():
    pos = {"side": "long", "sl": 1.1000, "tp": 1.1050}
    bar = {"high": 1.1060, "low": 1.0990, "close": 1.1010}  # both stop and target touched
    result = sim.check_bar(pos, bar)
    assert result == {"filled": True, "reason": "stop", "exit": 1.1000}


def test_fill_engine_target_only():
    pos = {"side": "short", "sl": 1.1050, "tp": 1.0950}
    bar = {"high": 1.1010, "low": 1.0940, "close": 1.0960}
    result = sim.check_bar(pos, bar)
    assert result == {"filled": True, "reason": "target", "exit": 1.0950}


def test_full_mock_trade_matches_engine_r_math():
    """AT: a scripted mock trade (limit entry via market_fill_price, SL, TP) produces the same
    R as nylab.models.london_sweep_reversal's engine would for the same numbers."""
    entry = sim.market_fill_price({"open": 1.10500})
    sl, tp = 1.10400, 1.10700  # 1:2 RR, 10-pip risk
    fill = sim.check_bar({"side": "long", "sl": sl, "tp": tp}, {"high": 1.10750, "low": 1.10450, "close": 1.10700})
    assert fill["reason"] == "target"
    r = sim.compute_r("long", entry, fill["exit"], sl, cost_pips=1.0, pip=0.0001)
    assert abs(r["risk_pips"] - 10.0) < 1e-6
    assert abs(r["R_gross"] - 2.0) < 1e-6
    assert abs(r["R_net"] - 1.9) < 1e-6  # 2R gross minus 1 pip cost on a 10-pip risk = 2 - 0.1


def test_lots_from_risk_rounds_down():
    lots = sim.lots_from_risk(balance=5000, risk_pct=0.5, sl_distance_pips=25, pip_value_per_lot=10.0)
    assert lots == 0.10  # $25 risk / (25 pips * $10/pip/lot) = 0.1 lots exactly


def test_maven_daily_breach_triggers():
    program = {"daily_dd_pct": 4, "max_dd_pct": 8}
    s = sim.maven_state(starting_balance=5000, current_balance=4790, day_start_balance=5000,
                         peak_balance=5000, program=program)
    assert s["day_dd_breached"] is True
    assert s["day_dd_status"] == "red"


def test_maven_not_breached_when_within_limits():
    program = {"daily_dd_pct": 4, "max_dd_pct": 8}
    s = sim.maven_state(starting_balance=5000, current_balance=4980, day_start_balance=5000,
                         peak_balance=5000, program=program)
    assert s["day_dd_breached"] is False
    assert s["day_dd_status"] == "green"


def test_pending_limit_order_fills_on_dip():
    """A long LIMIT rests below market and fills when price dips down to it."""
    order = {"side": "long", "entry": 1.10000, "order_type": "limit"}
    bar = {"high": 1.10100, "low": 1.09950}
    result = sim.check_pending_fill(order, bar)
    assert result == {"filled": True, "entry": 1.10000}


def test_pending_limit_order_does_not_fill_if_untouched():
    order = {"side": "long", "entry": 1.09000, "order_type": "limit"}
    bar = {"high": 1.10100, "low": 1.09950}
    result = sim.check_pending_fill(order, bar)
    assert result == {"filled": False, "entry": None}


def test_pending_stop_order_fills_on_breakout():
    """A long STOP rests above market and fills when price rises up to it."""
    order = {"side": "long", "entry": 1.10200, "order_type": "stop"}
    bar = {"high": 1.10250, "low": 1.09980}
    result = sim.check_pending_fill(order, bar)
    assert result == {"filled": True, "entry": 1.10200}


def test_pending_short_limit_fills_on_rally():
    """A short LIMIT rests above market and fills when price rallies up to it."""
    order = {"side": "short", "entry": 1.10300, "order_type": "limit"}
    bar = {"high": 1.10310, "low": 1.10100}
    result = sim.check_pending_fill(order, bar)
    assert result == {"filled": True, "entry": 1.10300}


def test_pwh_pwl_available_from_day_open(store):
    """Phase 2 gap-close: PWH/PWL exist in the day table and, like PDH/PDL, are already fully
    known at the start of the trading day (available_at_h -7) since they only summarize the
    prior, fully-completed calendar week."""
    from nylab.days import COLUMN_DOCS
    assert COLUMN_DOCS["pwh"] == -7 and COLUMN_DOCS["pwl"] == -7
    assert "pwh" in store.days.columns and "pwl" in store.days.columns
    have_both = store.days.dropna(subset=["pwh", "pwl"])
    assert len(have_both) > 0, "pwh/pwl never populated on this fixture -- check the week-grouping logic"
    assert (have_both["pwh"] >= have_both["pwl"]).all()
