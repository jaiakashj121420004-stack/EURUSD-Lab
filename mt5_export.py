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

Read-only: this script never places, modifies or closes orders.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
    import pandas as pd
except ImportError:
    sys.exit("Missing packages. Run:  pip install MetaTrader5 pandas")

TF = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1"}


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
    a = ap.parse_args()

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
    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=int(365.25 * a.years) + 1)
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
        sys.exit("No data returned. Open an EURUSD chart on this timeframe, scroll back (or press Home) "
                 "to force MT5 to download history, then run again.")
    df = pd.concat(frames).drop_duplicates("time").sort_values("time")
    df["time"] = pd.to_datetime(df["time"], unit="s")  # NOTE: this is broker SERVER time, not UTC
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


if __name__ == "__main__":
    main()
