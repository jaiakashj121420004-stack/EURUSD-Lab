"""mt5_export.py's own merge logic -- ROADMAP 9.1's incremental --append-to mode. The MetaTrader5
package only exists on Windows with a running terminal, so nothing here touches mt5.* -- just the
pure pandas merge step (_merge_incremental), which is where the actual correctness risk is (a bad
merge could silently duplicate or drop bars)."""
import importlib.util
import os
import sys

import pandas as pd
import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_mt5_export():
    """mt5_export.py imports MetaTrader5 at module level, which isn't installed here (Windows-
    only) -- stub it out before import so _merge_incremental (which never touches mt5.*) is still
    reachable and testable."""
    if "MetaTrader5" not in sys.modules:
        sys.modules["MetaTrader5"] = type(sys)("MetaTrader5")
    spec = importlib.util.spec_from_file_location("mt5_export", os.path.join(_HERE, "mt5_export.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mt5_export = _load_mt5_export()


def _bars(times, price=1.1000):
    return pd.DataFrame({
        "time": pd.to_datetime(times), "open": price, "high": price, "low": price, "close": price,
        "tick_volume": 10, "spread": 10, "real_volume": 0,
    })


def test_merge_incremental_appends_genuinely_new_bars():
    existing = _bars(["2026-01-01 00:00:00", "2026-01-01 00:05:00"])
    new = _bars(["2026-01-01 00:10:00", "2026-01-01 00:15:00"])
    out = mt5_export._merge_incremental(existing, new)
    assert len(out) == 4
    assert list(out["time"]) == list(pd.to_datetime(
        ["2026-01-01 00:00:00", "2026-01-01 00:05:00", "2026-01-01 00:10:00", "2026-01-01 00:15:00"]))


def test_merge_incremental_dedupes_the_overlap_window():
    """--overlap-days re-requests a few days the file already has, on purpose (in case the
    broker revised a recent bar) -- the overlap must not create doubled rows."""
    existing = _bars(["2026-01-01 00:00:00", "2026-01-01 00:05:00", "2026-01-01 00:10:00"])
    new = _bars(["2026-01-01 00:05:00", "2026-01-01 00:10:00", "2026-01-01 00:15:00"])  # 2 overlap
    out = mt5_export._merge_incremental(existing, new)
    assert len(out) == 4  # not 6
    assert out["time"].is_unique


def test_merge_incremental_a_same_day_rerun_with_no_new_bars_adds_nothing():
    existing = _bars(["2026-01-01 00:00:00", "2026-01-01 00:05:00"])
    new = _bars(["2026-01-01 00:00:00", "2026-01-01 00:05:00"])  # identical re-pull
    out = mt5_export._merge_incremental(existing, new)
    assert len(out) == 2


def test_merge_incremental_result_is_sorted_even_if_inputs_are_not():
    existing = _bars(["2026-01-01 00:10:00", "2026-01-01 00:00:00"])
    new = _bars(["2026-01-01 00:05:00"])
    out = mt5_export._merge_incremental(existing, new)
    assert list(out["time"]) == sorted(out["time"])


def test_merge_incremental_keeps_all_original_columns():
    existing = _bars(["2026-01-01 00:00:00"])
    new = _bars(["2026-01-01 00:05:00"])
    out = mt5_export._merge_incremental(existing, new)
    assert set(out.columns) == {"time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"}


def test_request_window_never_mixes_naive_and_aware_datetimes():
    """Regression test for the real bug found 2026-09-28: run_daily.bat's first live run crashed
    with 'can't compare offset-naive and offset-aware datetimes' because `end` was built from
    datetime.now(timezone.utc) (aware) while `last_existing` (read back from our own CSV, via
    pd.to_datetime with no utc=True) is naive. _request_window must hand back a start/end pair
    that are BOTH naive, and start must be before end, so main()'s request-chunking loop
    (`while t0 < end`) never explodes on this comparison again."""
    import datetime as dt
    now_utc = dt.datetime(2026, 9, 28, 12, 0, 0)  # naive, like datetime.utcnow()
    last_existing = pd.Timestamp("2026-09-25 05:25:00")  # naive, like a CSV column parsed back

    start, end = mt5_export._request_window(now_utc, last_existing, overlap_days=3, years=5)

    assert start.tzinfo is None
    assert end.tzinfo is None
    assert start < end  # this exact comparison is what crashed on Akash's machine


def test_request_window_full_export_mode_has_no_last_existing():
    """Non-incremental (first-ever) export: no CSV to read yet, so the window is just
    'years back from now' -- same naive-datetime guarantee applies."""
    import datetime as dt
    now_utc = dt.datetime(2026, 9, 28, 12, 0, 0)

    start, end = mt5_export._request_window(now_utc, last_existing=None, overlap_days=3, years=5)

    assert start.tzinfo is None
    assert end.tzinfo is None
    assert start < end
    assert (end - start).days >= 365 * 5  # roughly 5 years, plus the +1 day padding
