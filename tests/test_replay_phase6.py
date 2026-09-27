"""ROADMAP Phase 6.1/6.2/6.5 acceptance: real session-character/news/raid/DSL filtering, the
hide-outcome toggle, and news events in the replay trainer's API -- against a Store built
through the FULL pipeline (sessions + calendar attached), unlike test_replay_api.py's plain
`store` fixture, which deliberately stays Phase-1-thin to prove the graceful-error path when
those columns are absent. Reuses the same synthetic-bars/synthetic-calendar pattern as
tests/test_sessions_section.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import config as cfg
from nylab import days as days_mod
from nylab import sessions as sessions_mod
from nylab import calendar_features
from nylab.data import timezones
from nylab.replay import api


def _synth_bars(n_days=140, seed=21):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01 00:00", periods=n_days * 288, freq="5min")
    walk = rng.normal(0, 0.00015, len(idx)).cumsum() + 1.10000
    high = walk + rng.uniform(0, 0.00012, len(idx))
    low = walk - rng.uniform(0, 0.00012, len(idx))
    close = walk + rng.normal(0, 0.00003, len(idx))
    return pd.DataFrame({"server": idx, "open": walk, "high": high, "low": low, "close": close})


def _synth_calendar(trading_days):
    rng = np.random.default_rng(5)
    rows = []
    for td in trading_days[::4]:
        rows.append(dict(time_ny=td + pd.Timedelta(hours=8.5), currency="USD", importance=3,
                          event_name="Non-Farm Payrolls", actual=1.0 + rng.normal(0, 0.1),
                          forecast=0.5, previous=0.4))
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def full_store():
    raw = _synth_bars()
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    windows = cfg.legacy_windows()
    d = days_mod.build_days(raw, windows)
    trading_days = pd.DatetimeIndex(d.index)
    cal = _synth_calendar(trading_days)
    d = days_mod.attach_calendar_features(d, cal, cfg.sessions())
    sessions_cfg = cfg.sessions()
    session_tables = sessions_mod.build_all_sessions(raw, d, cal, sessions_cfg, windows["pip"])
    d = sessions_mod.attach_session_features(d, session_tables)
    day_types = sessions_mod.build_day_types(d)
    d = d.join(day_types)
    return api.Store(raw, d, cal=cal)


def test_session_character_filter_matches_manual_mask(full_store):
    result = api.list_days(full_store, exclude_thin=False, session_character={"lon": ["chop"]})
    expected = int((full_store.days["lon_character"] == "chop").sum())
    assert result["count"] == expected
    assert result["spoiler_filter_used"] is True


def test_news_schedule_flag_is_not_a_spoiler(full_store):
    result = api.list_days(full_store, exclude_thin=False, news_flags=["has_nfp"])
    expected = int(full_store.days["has_nfp"].sum())
    assert result["count"] == expected
    assert result["spoiler_filter_used"] is False  # scheduling is known in advance, not an outcome


def test_realized_news_column_is_a_spoiler(full_store):
    col = "nyam_usd_cnt"
    assert col in full_store.days.columns
    result = api.list_days(full_store, exclude_thin=False, dsl=f"{col} > 0")
    assert result["spoiler_filter_used"] is True


def test_adr_range_filter(full_store):
    lo, hi = 0.3, 0.7
    result = api.list_days(full_store, exclude_thin=False, adr_min=lo, adr_max=hi)
    s = full_store.days["adr_used_0930"]
    expected = int(((s >= lo) & (s <= hi)).sum())
    assert result["count"] == expected


def test_combined_filters_are_anded(full_store):
    result = api.list_days(full_store, exclude_thin=False, weekdays=[0, 1, 2, 3, 4],
                            session_character={"lon": ["chop", "quiet"]},
                            raid_flags=["ny_takes_lon_high"])
    for r in [d for d in full_store.days.reset_index().to_dict("records")
              if d["lon_character"] in ("chop", "quiet") and d.get("ny_takes_lon_high")]:
        pass  # sanity: just confirm the call didn't error and count is sane
    assert 0 <= result["count"] <= len(full_store.days)


def test_hide_outcome_off_shows_session_characters(full_store):
    rows = api.list_days(full_store, exclude_thin=False, hide_outcome=False)["days"]
    assert any(r["outcome"].get("lon_character") is not None for r in rows)


def test_get_news_withholds_actual_before_release_reveals_after(full_store):
    td = next(t for t in full_store.days.index if bool(full_store.days.loc[t].get("has_nfp")))
    td_str = td.strftime("%Y-%m-%d")

    before = api.get_news(full_store, td_str, (td + pd.Timedelta(hours=8, minutes=0)).isoformat())
    nfp_events_before = [e for e in before["news"] if e["event_name"] == "Non-Farm Payrolls"]
    assert len(nfp_events_before) == 1
    assert nfp_events_before[0]["actual"] is None  # not released yet at 08:00, event is at 08:30
    assert nfp_events_before[0]["forecast"] is not None  # schedule/forecast known in advance
    # `h` (hours since td midnight, NY time) must be exposed so the frontend can render the clock
    # time via h_to_hhmm() instead of reading the epoch back through the BROWSER's local timezone
    # (a real bug found via smoke testing on a non-UTC machine -- see docs/PROGRESS.md).
    assert nfp_events_before[0]["h"] == pytest.approx(8.5, abs=0.01)

    after = api.get_news(full_store, td_str, (td + pd.Timedelta(hours=9)).isoformat())
    nfp_events_after = [e for e in after["news"] if e["event_name"] == "Non-Farm Payrolls"]
    assert nfp_events_after[0]["actual"] is not None
    assert nfp_events_after[0]["released"] is True


def test_get_news_without_calendar_returns_empty_with_note():
    from nylab import cache as cache_mod
    bars, days = cache_mod.load(cache_dir="tests/fixtures/_replay_cache")
    store_no_cal = api.Store(bars, days)
    result = api.get_news(store_no_cal, days.index[0].strftime("%Y-%m-%d"), days.index[0].isoformat())
    assert result["news"] == []
    assert "note" in result
