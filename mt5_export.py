"""
mt5_export.py — export EURUSD price history from YOUR MetaTrader 5 to CSV.

Runs on Windows, on the same machine as your MT5 terminal.
    1) Open MT5 and log in (demo is fine). Leave it running.
    2) In MT5: Tools > Options > Charts > "Max bars in chart" = Unlimited  (then restart MT5)
    3) In a terminal (PowerShell / CMD):
           pip install MetaTrader5 pandas
           python mt5_export.py
    4) A file like  EURUSD_M5_2021-09-24_2026-09-24.csv  appears next to this script.

Options:
    python mt5_export.py --symbol EURUSD --timeframe M5 --years 5
    python mt5_export.py --timeframe M1 --years 1        (M1 = much bigger file; many brokers keep less M1 history)

Incremental mode (ROADMAP 9.1, added 2026-09-28 for run_daily.bat):
    python mt5_export.py --append-to EURUSD_M5_2021-09-27_2026-09-25.csv
Instead of a brand-new dated file, this pulls only the bars since that file's own last one (plus
a few days' overlap in case the broker revised a recent bar) and appends them IN PLACE to that
SAME file -- so it keeps growing under one name, and everything that already points at that
filename (`nylab run`, the replay cache, etc.) never has to change. Pass the exact same path every
time (run_daily.bat does). Safe to run more than once a day: it always de-duplicates by bar time,
so a repeat run adds nothing new.

Read-only: this script never places, modifies or closes orders.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
    import pandas as pd
except ImportError:
    sys.exit("Missing packages. Run:  pip install MetaTrader5 pandas")

TF = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1"}


def _merge_incremental(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Pure merge step for --append-to (ROADMAP 9.1), pulled out of main() so it's testable
    without a real MT5 connection: combine, de-duplicate by bar time (a re-requested overlap
    window, or a same-day re-run, must never create a double row), sort. `existing`/`new` must
    both already have a `time` column as real datetimes (main() converts before calling this)."""
    return (pd.concat([existing, new], ignore_index=True)
            .drop_duplicates("time").sort_values("time").reset_index(drop=True))


def _request_window(now_utc: datetime, last_existing=None, overlap_days: float = 3,
                     years: float = 5):
    """Pure helper (testable without MT5): decide the [start, end) window to request from the
    broker. Bug fixed here 2026-09-28: MT5 bar times (and anything read back from our own CSV
    files) are plain/naive datetimes with no timezone attached, but `end` used to be built from
    `datetime.now(timezone.utc)`, which IS timezone-aware -- comparing a naive `start` (from the
    CSV, in incremental mode) against that aware `end` crashed with
    "can't compare offset-naive and offset-aware datetimes" the first time run_daily.bat actually
    ran. Using `datetime.utcnow()` (naive) keeps both sides the same type; it's the same instant
    either way, just without the tzinfo attached."""
    end = now_utc + timedelta(days=1)
    if last_existing is not None:
        start = last_existing - timedelta(days=overlap_days)
    else:
        start = end - timedelta(days=int(365.25 * years) + 1)
    return start, end


def find_symbol(base):
    """Brokers often add suffixes (EURUSD.m, EURUSDm, EURUSD.raw). Find the right one."""
    info = mt5.symbol_info(base)
    if info is not None:
        return base
    cands = [s.name for s in (mt5.symbols_get() or []) if s.name.upper().startswith(base.upper())]
    if not cands:
        sys.exit(f"No symbol starting with {base} found in Market Watch.")
    cands.sort(key=len)
    print(f"  '{base}' not found; using broker symbol '{cands[0]}' (others: {cands[1:5]})")
    return cands[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--timeframe", default="M5", choices=list(TF))
    ap.add_argument("--years", type=float, default=5)
    ap.add_argument("--append-to", dest="append_to", default=None,
                     help="ROADMAP 9.1: incremental mode -- pull only bars newer than this "
                          "existing export file's own last one (see module docstring) and append "
                          "them in place, instead of writing a new dated file.")
    ap.add_argument("--overlap-days", dest="overlap_days", type=float, default=3,
                     help="Incremental mode only: re-request this many days before the existing "
                          "file's last bar too, in case the broker revised a recent one -- "
                          "de-duplicated by bar time either way, so this never creates doubles.")
    a = ap.parse_args()

    existing = None
    if a.append_to:
        if not os.path.exists(a.append_to):
            sys.exit(f"--append-to file not found: {a.append_to}\n"
                      "Run a normal full export first (drop --append-to), then use --append-to "
                      "for every run after that.")
        existing = pd.read_csv(a.append_to)
        existing["time"] = pd.to_datetime(existing["time"])
        if not len(existing):
            sys.exit(f"{a.append_to} exists but has no rows -- delete it and run a normal full "
                      "export instead of incremental.")

    if not mt5.initialize():
        sys.exit(f"MT5 initialize() failed: {mt5.last_error()}  — is the terminal open and logged in?")
    acc = mt5.account_info()
    term = mt5.terminal_info()
    print(f"Connected: {term.name if term else '?'} | server {acc.server if acc else '?'}")

    sym = find_symbol(a.symbol)
    mt5.symbol_select(sym, True)
    si = mt5.symbol_info(sym)

    # Estimate the broker server's current UTC offset (tick time is server time)
    tick = mt5.symbol_info_tick(sym)
    offset_h = None
    if tick is not None and tick.time:
        now_utc = datetime.now(timezone.utc).timestamp()
        offset_h = round((tick.time - now_utc) / 3600)
        print(f"  Broker server time is approx UTC{offset_h:+d} right now "
              f"(only reliable while the market is open).")

    tf = getattr(mt5, TF[a.timeframe])
    last_existing = existing["time"].max() if existing is not None else None
    start, end = _request_window(datetime.utcnow(), last_existing, a.overlap_days, a.years)
    if existing is not None:
        print(f"  Incremental: {a.append_to} already covers through {last_existing} (server time). "
              f"Requesting from {start:%Y-%m-%d} ({a.overlap_days:.0f}-day overlap) to now...")
    else:
        print(f"  Requesting {sym} {a.timeframe} from {start:%Y-%m-%d} ...")

    # Pull in yearly chunks — more reliable than one giant request
    frames, t0 = [], start
    while t0 < end:
        t1 = min(t0 + timedelta(days=365), end)
        r = mt5.copy_rates_range(sym, tf, t0, t1)
        if r is not None and len(r):
            frames.append(pd.DataFrame(r))
        t0 = t1
    mt5.shutdown()

    if not frames:
        if existing is not None:
            print(f"\nNo bars returned for that window (nothing new since the last export, or the "
                  f"market's closed right now). {a.append_to} is unchanged.")
            return
        sys.exit("No data returned. Open an EURUSD chart on this timeframe, scroll back (or press Home) "
                 "to force MT5 to download history, then run again.")
    df = pd.concat(frames).drop_duplicates("time").sort_values("time")
    df["time"] = pd.to_datetime(df["time"], unit="s")  # NOTE: this is broker SERVER time, not UTC

    if existing is not None:
        before = len(existing)
        combined = _merge_incremental(existing, df)
        added = len(combined) - before
        combined.to_csv(a.append_to, index=False)
        first, last = combined["time"].iloc[0], combined["time"].iloc[-1]
        print(f"\nAppended {added:,} new bar(s) -> {a.append_to}")
        print(f"  now covers {first:%Y-%m-%d} -> {last:%Y-%m-%d}, {len(combined):,} bars total")
        if offset_h is not None:
            print(f"  Server offset now UTC{offset_h:+d}.")
        print(f"\nNext:  python -m nylab run {a.append_to}")
        return

    first, last = df["time"].iloc[0], df["time"].iloc[-1]
    fn = f"{a.symbol}_{a.timeframe}_{first:%Y-%m-%d}_{last:%Y-%m-%d}.csv"
    df.to_csv(fn, index=False)

    got_years = (last - first).days / 365.25
    print(f"\nSaved {len(df):,} bars  ({first:%Y-%m-%d} -> {last:%Y-%m-%d}, {got_years:.1f} years)  ->  {fn}")
    print(f"  digits={si.digits}  point={si.point}  (spread column is in points; 10 points = 1 pip on 5-digit brokers)")
    if got_years < a.years * 0.9:
        print(f"  NOTE: you asked for {a.years} years but the broker supplied {got_years:.1f}. "
              "Scroll the chart back / raise 'Max bars in chart', or try M5 instead of M1.")
    if offset_h is not None:
        print(f"  Server offset now UTC{offset_h:+d}. Most brokers use 'New York close' time (UTC+2 winter / UTC+3 summer); "
              "if that matches, run the lab with --tz auto (default).")
    print("\nNext:  python ny_session_lab.py \"%s\"" % fn)
    print(f"  (or, from now on, keep it fresh with:  python mt5_export.py --append-to {fn})")


if __name__ == "__main__":
    main()
