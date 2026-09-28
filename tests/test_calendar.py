"""ROADMAP Phase 4 acceptance + unit tests: calendar import (4.2/4.4), surprise z-scores,
event families, and the day/session news features (4.3), incl. the look-ahead registration.

Accept (docs/ROADMAP.md Phase 4): "On the user's real data, NFP events land at 08:30 NY in both
summer and winter; FOMC at 14:00." test_at04_nfp_and_fomc_land_at_expected_ny_hour is that check,
run against a synthetic export built the same way ExportCalendar.mq5 writes real ones. The "ny+7"
broker convention is a CONSTANT offset from server clock to NY clock (both track US DST together
-- that's what makes it the "NY close" convention), so a correct implementation places these
events at the same NY hour regardless of calendar month; that invariance IS the assertion, not a
loophole in it -- nylab.data.timezones.sanity_check (Phase 0/1) is what independently proves the
mode itself is right for a given broker, using the price bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import calendar_features, calendar_io
from nylab.days import COLUMN_DOCS


def _mt5_csv(tmp_path, rows):
    """rows: list of (time_server_str, currency, event_id, event_name, importance, actual, forecast, previous)."""
    df = pd.DataFrame(rows, columns=["time_server", "currency", "event_id", "event_name",
                                      "importance", "actual", "forecast", "previous"])
    df["revised_previous"] = ""
    df["unit"] = 0
    df["multiplier"] = 0
    path = tmp_path / "calendar_export.csv"
    df.to_csv(path, index=False)
    return str(path)


def test_at04_nfp_and_fomc_land_at_expected_ny_hour(tmp_path):
    # "ny+7": NY time = server time - 7h, always (broker DST tracks NY DST). NFP releases at
    # 08:30 NY -> server 15:30, any month. FOMC at 14:00 NY -> server 21:00.
    rows = [
        ("2024.01.05 15:30:00", "USD", 1, "Nonfarm Payrolls", 3, 200.0, 190.0, 180.0),   # winter
        ("2024.07.05 15:30:00", "USD", 2, "Nonfarm Payrolls", 3, 210.0, 200.0, 195.0),   # summer
        ("2024.01.31 21:00:00", "USD", 3, "FOMC Statement", 3, None, None, None),         # winter
        ("2024.07.31 21:00:00", "USD", 4, "FOMC Statement", 3, None, None, None),         # summer
    ]
    path = _mt5_csv(tmp_path, rows)
    df = calendar_io.load(path, tz_mode="ny+7")

    nfp = df[df["event_name"] == "Nonfarm Payrolls"]
    fomc = df[df["event_name"] == "FOMC Statement"]
    assert len(nfp) == 2 and (nfp["time_ny"].dt.hour == 8).all() and (nfp["time_ny"].dt.minute == 30).all()
    assert len(fomc) == 2 and (fomc["time_ny"].dt.hour == 14).all() and (fomc["time_ny"].dt.minute == 0).all()


def test_load_mt5_export_schema(tmp_path):
    path = _mt5_csv(tmp_path, [("2024.03.01 13:30:00", "usd", 1, " CPI m/m ", 2, 0.4, 0.3, 0.2)])
    df = calendar_io.load(path, tz_mode="ny+7")
    assert list(df.columns) == ["time_ny", "currency", "event_name", "importance", "actual", "forecast", "previous"]
    assert df.iloc[0]["currency"] == "USD"          # uppercased
    assert df.iloc[0]["event_name"] == "CPI m/m"    # stripped
    assert df.iloc[0]["importance"] == 2


def test_load_fallback_csv_schema(tmp_path):
    path = tmp_path / "fallback.csv"
    pd.DataFrame([
        {"datetime_ny": "2024-06-07 08:30:00", "currency": "usd", "event": "Nonfarm Payrolls",
         "impact": "high", "actual": 272, "forecast": 185, "previous": 165},
    ]).to_csv(path, index=False)
    df = calendar_io.load(str(path))
    assert df.iloc[0]["importance"] == 3  # "high" -> 3
    assert df.iloc[0]["time_ny"] == pd.Timestamp("2024-06-07 08:30:00")


def test_load_rejects_unrecognized_schema(tmp_path):
    path = tmp_path / "junk.csv"
    pd.DataFrame([{"a": 1, "b": 2}]).to_csv(path, index=False)
    with pytest.raises(ValueError):
        calendar_io.load(str(path))


@pytest.mark.parametrize("name,expect", [
    ("Nonfarm Payrolls", "NFP"), ("US NFP", "NFP"),
    ("CPI m/m", "CPI"), ("Consumer Price Index y/y", "CPI"),
    ("FOMC Statement", "FOMC"), ("Federal Funds Rate", "FOMC"),
    ("ECB Main Refinancing Rate", "ECB"), ("ECB Press Conference", "ECB"),  # ECB checked before speech
    ("Manufacturing PMI", "PMI"), ("GDP q/q", "GDP"),
    ("Retail Sales m/m", "retail_sales"), ("Initial Jobless Claims", "claims"),
    ("Fed Chair Powell Speaks", "speech"),
    ("Housing Starts", None),
])
def test_classify_family(name, expect):
    assert calendar_features.classify_family(name) == expect


def test_compute_surprise_z_requires_min_prior_and_never_leaks_future():
    # 12 releases of the same event; z-score for release i must only ever use releases < i.
    n = 12
    times = pd.date_range("2020-01-01", periods=n, freq="30D")
    # Small alternating surprises around zero on the first n-1 releases (so prior stdev is
    # small but > 0 -- realistic "boring" releases), then a huge outlier on the LAST release.
    actual = pd.Series([0.1 * (-1) ** i for i in range(n - 1)] + [100.0])
    forecast = pd.Series([0.0] * n)
    cal = pd.DataFrame({"time_ny": times, "currency": "USD", "event_name": "Widget Index",
                        "importance": 3, "actual": actual, "forecast": forecast})
    out = calendar_features.compute_surprise(cal)

    # First 8 releases: fewer than MIN_PRIOR_FOR_Z=8 prior points -> NaN.
    assert out["surprise_z"].iloc[:8].isna().all()
    # The 9th+ releases have enough prior history to get a real z; none of those early, boring
    # releases should show a huge z just because a future outlier exists in the same series.
    assert out["surprise_z"].iloc[8:11].abs().max() < 5
    # The outlier release itself gets a large z (it's a genuine 99-unit surprise vs a near-zero
    # prior stdev) -- that's it seeing its OWN value, not a leak.
    assert abs(out["surprise_z"].iloc[-1]) > 5


def test_build_day_flags_scheduling_and_session_windows():
    trading_days = pd.DatetimeIndex([pd.Timestamp("2024-06-07"), pd.Timestamp("2024-06-10")])
    # 2024-06-07 (a Friday td): NFP at 08:30 NY ((h=8.5, inside 'ny' and 'preny' windows, high
    # importance) and a high-importance EUR event inside the London KZ window (h=3).
    # 2024-06-10: nothing.
    rows = [
        {"time_ny": pd.Timestamp("2024-06-07 08:30:00"), "currency": "USD", "event_name": "Nonfarm Payrolls",
         "importance": 3, "actual": 272.0, "forecast": 185.0, "previous": 165.0},
        {"time_ny": pd.Timestamp("2024-06-07 03:00:00"), "currency": "EUR", "event_name": "ECB Rate Decision",
         "importance": 3, "actual": 4.25, "forecast": 4.25, "previous": 4.50},
    ]
    cal = pd.DataFrame(rows)
    sessions_cfg = {"asia": (-4, 0), "lon": (2, 5), "preny": (7, 9.5), "nyam_kz": (7, 10), "ny": (7, 16)}

    out = calendar_features.build_day_flags(cal, trading_days, sessions_cfg)

    d0, d1 = trading_days
    assert bool(out.loc[d0, "has_nfp"]) is True
    assert bool(out.loc[d1, "has_nfp"]) is False
    assert bool(out.loc[d0, "has_ecb"]) is True
    assert bool(out.loc[d0, "red_usd_0830"]) is True     # h=8.5 -> inside [8,9)
    assert bool(out.loc[d0, "red_eur_london"]) is True   # h=3.0 -> inside lon [2,5)
    assert out.loc[d0, "ny_usd_cnt"] == 1                # NFP (h=8.5) is inside ny [7,16)
    assert out.loc[d0, "preny_usd_cnt"] == 1              # and inside preny [7,9.5)
    assert out.loc[d0, "lon_eur_cnt"] == 1                # ECB at h=3.0 IS inside lon [2,5)
    assert out.loc[d1, "ny_usd_cnt"] == 0


def test_calendar_columns_registered_in_column_docs_for_lookahead_check():
    docs = calendar_features.column_docs()
    assert docs["has_nfp"] == -7.0
    assert docs["ny_usd_cnt"] == 16.0
    assert docs["lon_eur_maxz"] == 5.0
    # And the merge into nylab.days.COLUMN_DOCS actually happened at import time.
    for col in docs:
        assert col in COLUMN_DOCS, f"{col} missing from nylab.days.COLUMN_DOCS -- Phase 3 look-ahead check would miss it"


# --------------------------------------------------------------------- ROADMAP 9.4 (2026-09-28)
def test_freshness_message_missing_file_says_so(tmp_path):
    from nylab import calendar_io
    path = str(tmp_path / "calendar.parquet")  # never created
    msg = calendar_io.freshness_message(path)
    assert msg is not None
    assert "no" in msg and path in msg


def test_freshness_message_fresh_file_returns_none(tmp_path):
    from nylab import calendar_io
    path = tmp_path / "calendar.parquet"
    path.write_bytes(b"x")  # just needs to exist with a fresh mtime
    msg = calendar_io.freshness_message(str(path))
    assert msg is None


def test_freshness_message_stale_file_flags_it(tmp_path):
    import os
    import time

    from nylab import calendar_io
    path = tmp_path / "calendar.parquet"
    path.write_bytes(b"x")
    old = time.time() - 10 * 86400  # 10 days old
    os.utime(path, (old, old))
    msg = calendar_io.freshness_message(str(path), max_age_days=7)
    assert msg is not None
    assert "10" in msg
    assert "calendar-import" in msg or "calendar_export.csv" in msg


def test_freshness_message_respects_max_age_days(tmp_path):
    import os
    import time

    from nylab import calendar_io
    path = tmp_path / "calendar.parquet"
    path.write_bytes(b"x")
    age = time.time() - 3 * 86400  # 3 days old
    os.utime(path, (age, age))
    assert calendar_io.freshness_message(str(path), max_age_days=7) is None
    assert calendar_io.freshness_message(str(path), max_age_days=1) is not None
