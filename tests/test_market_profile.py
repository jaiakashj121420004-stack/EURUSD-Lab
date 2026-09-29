"""nylab.market_profile -- descriptive market-map tables for Akash's 'help me understand
EURUSD' request. Every table here is exploratory, not a tested hypothesis (see the module
docstring) -- these tests just verify the arithmetic/plumbing on small, hand-built inputs."""
import numpy as np
import pandas as pd
import pytest

from nylab import market_profile as mp


def _days(n, start="2026-01-05"):  # a Monday
    return pd.date_range(start, periods=n, freq="D")


def test_dir_label():
    assert mp._dir_label(1) == "up"
    assert mp._dir_label(-1) == "down"
    assert mp._dir_label(0) == "flat"
    assert mp._dir_label(np.nan) == "n/a"


def test_session_relationship_table_basic_counts_and_dominant():
    # asia=chop, lon=trend always leads to nyam up in this toy set; asia=trend, lon=chop -> down
    idx = _days(6)
    d = pd.DataFrame({
        "asia_character": ["chop", "chop", "chop", "trend", "trend", "trend"],
        "lon_character": ["trend", "trend", "trend", "chop", "chop", "chop"],
        "nyam_full_dir": [1, 1, 0, -1, -1, -1],
    }, index=idx)
    out = mp.session_relationship_table(d, ["asia_character", "lon_character"], "nyam_full_dir", "dir")
    assert len(out) == 2
    row_ct = out[(out.asia_character == "chop") & (out.lon_character == "trend")].iloc[0]
    assert row_ct["n"] == 3
    assert row_ct["dominant"] == "up"
    assert row_ct["pct_up"] == pytest.approx(2 / 3)
    row_tc = out[(out.asia_character == "trend") & (out.lon_character == "chop")].iloc[0]
    assert row_tc["dominant"] == "down"
    assert row_tc["dominant_pct"] == 1.0


def test_session_relationship_table_flags_low_n():
    idx = _days(3)
    d = pd.DataFrame({"a": ["x", "x", "x"], "out_dir": [1, 1, -1]}, index=idx)
    out = mp.session_relationship_table(d, ["a"], "out_dir", "dir")
    assert out.iloc[0]["low_n"] is True or bool(out.iloc[0]["low_n"]) is True
    assert out.iloc[0]["n"] == 3


def test_session_relationship_table_character_outcome_kind():
    idx = _days(4)
    d = pd.DataFrame({"a": ["x", "x", "y", "y"], "out_char": ["trend", "trend", "chop", "quiet"]}, index=idx)
    out = mp.session_relationship_table(d, ["a"], "out_char", "character")
    row_x = out[out.a == "x"].iloc[0]
    assert row_x["dominant"] == "trend"
    assert row_x["pct_trend"] == 1.0


def test_early_raid_outcome_table_buckets_by_elapsed_time():
    idx = _days(4)
    d = pd.DataFrame({
        "lon_first_raid_t": [5.1, 6.5, np.nan, 5.2],  # session starts at h=5.0 -> 5.1/5.2 within 60min, 6.5 is 90min later
        "lon_dir": [1, -1, 1, 1],
    }, index=idx)
    out = mp.early_raid_outcome_table(d, "lon", session_start_h=5.0, outcome_col="lon_dir", outcome_kind="dir")
    buckets = dict(zip(out["bucket"], out["n"]))
    assert buckets["early sweep"] == 2  # 5.1 and 5.2 are within 60 min of 5.0
    assert buckets["late sweep"] == 1   # 6.5 is 90 min after 5.0
    assert buckets["no sweep"] == 1


def test_quiet_start_outcome_table_uses_range_rel_thresholds():
    idx = _days(4)
    d = pd.DataFrame({
        "lon_range_rel": [0.3, 0.3, 1.6, 1.0],
        "lon_character": ["quiet", "chop", "trend", "normal"],
    }, index=idx)
    out = mp.quiet_start_outcome_table(d, "lon")
    quiet_row = out[out.bucket.str.startswith("quiet")].iloc[0]
    assert quiet_row["n"] == 2
    active_row = out[out.bucket.str.startswith("already active")].iloc[0]
    assert active_row["n"] == 1
    typical_row = out[out.bucket == "typical"].iloc[0]
    assert typical_row["n"] == 1


def test_hour_of_day_profile_computes_range_and_direction():
    ts = pd.date_range("2026-01-05 08:00", periods=4, freq="15min", tz=None)
    df = pd.DataFrame({
        "ny": ts,
        "open": [1.1000, 1.1010, 1.1005, 1.1015],
        "high": [1.1015, 1.1020, 1.1015, 1.1025],
        "low": [1.0995, 1.1000, 1.0995, 1.1005],
        "close": [1.1010, 1.1005, 1.1015, 1.1020],
    })
    out = mp.hour_of_day_profile(df, pip=0.0001)
    assert list(out["ny_hour"]) == [8]
    row = out.iloc[0]
    assert row["n_days"] == 1
    # hour-8 range = max(high) - min(low) across both 30-min bars = 1.1025-1.0995 = 0.0030 = 30 pips
    assert row["median_range_pips"] == pytest.approx(30.0)
    assert 0 <= row["pct_up"] <= 1


def test_news_reaction_table_splits_by_news_presence():
    idx = _days(4)
    d = pd.DataFrame({
        "lon_news_high_usd": [1, 0, 0, 2],
        "lon_range_rel": [1.5, 0.8, 0.9, 1.7],
        "lon_dir": [1, -1, 0, 1],
    }, index=idx)
    out = mp.news_reaction_table(d, "lon", currency="usd")
    with_news = out[out.group.str.contains("USD high-impact")].iloc[0]
    without_news = out[out.group == "no high-impact news in window"].iloc[0]
    assert with_news["n"] == 2
    assert without_news["n"] == 2
    assert with_news["median_range_rel"] == pytest.approx(1.6)


def test_news_reaction_table_missing_column_returns_empty():
    d = pd.DataFrame({"x": [1, 2, 3]})
    out = mp.news_reaction_table(d, "lon", currency="usd")
    assert out.empty


def test_weekday_profile_maps_dow_to_names_and_computes_median():
    idx = _days(5)  # Mon..Fri
    d = pd.DataFrame({"dow": [0, 1, 2, 3, 4], "day_range": [50, 60, 70, 80, 90],
                       "day_dir": [1, 1, -1, 0, 1]}, index=idx)
    out = mp.weekday_profile(d)
    assert list(out["weekday"]) == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    mon = out[out.weekday == "Monday"].iloc[0]
    assert mon["median_range_pips"] == 50
    assert mon["pct_up"] == 1.0


def test_weekday_extremes_table_finds_the_week_high_day():
    # one week, Mon-Fri: Thursday has the highest day_high and lowest day_low
    idx = _days(5)
    d = pd.DataFrame({
        "dow": [0, 1, 2, 3, 4],
        "day_high": [1.10, 1.11, 1.12, 1.15, 1.13],
        "day_low": [1.05, 1.04, 1.03, 1.01, 1.02],
    }, index=idx)
    out = mp.weekday_extremes_table(d)
    thu = out[out.weekday == "Thursday"].iloc[0]
    assert thu["pct_sets_week_high"] == 1.0
    assert thu["pct_sets_week_low"] == 1.0
    mon = out[out.weekday == "Monday"].iloc[0]
    assert mon["pct_sets_week_high"] == 0.0


def test_monthly_and_quarterly_profile_group_correctly():
    idx = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-04-05", "2026-04-06"])
    d = pd.DataFrame({"day_range": [40, 60, 100, 120],
                       "day_type": ["range_day", "normal_day", "trend_day", "trend_day"]}, index=idx)
    m = mp.monthly_profile(d)
    jan = m[m.month == "Jan"].iloc[0]
    assert jan["n"] == 2
    assert jan["median_range_pips"] == 50
    assert jan["pct_range_or_normal_day"] == 1.0
    q = mp.quarterly_profile(d)
    q1 = q[q.quarter_num == 1].iloc[0]
    q2 = q[q.quarter_num == 2].iloc[0]
    assert q1["n"] == 2 and q2["n"] == 2
    assert q2["pct_range_or_normal_day"] == 0.0
