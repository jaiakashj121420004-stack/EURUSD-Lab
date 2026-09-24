"""nylab -- CLI. `python -m nylab run <csv>` reproduces v0's full pipeline (day table, the 15
hypotheses, the example model, report.html) through the nylab/ package, plus a parquet cache
and summary.json (ROADMAP Phase 1). export/calendar-import/hypothesis/snapshot/replay are
stubs for now -- wired up in the phases named in docs/ROADMAP.md.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

from nylab import cache as cache_mod
from nylab import config as cfg
from nylab import days as days_mod
from nylab import hypotheses as hyp_mod
from nylab import stats as stats_mod
from nylab.data import loader, quality, timezones
from nylab.models import london_sweep_reversal as lsr
from nylab.report import charts as charts_mod
from nylab.report import html as html_mod
from nylab.report import summary as summary_mod


def _prepare_bars(csv_path: str, tz: str):
    raw = loader.load_bars(csv_path)
    mode = timezones.detect_tz(raw["server"]) if tz == "auto" else tz
    raw["ny"] = timezones.to_new_york(raw["server"], mode)
    bar_minutes = raw["server"].diff().dt.total_seconds().div(60).mode().iloc[0]
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    return raw, mode, float(bar_minutes)


def cmd_run(args):
    windows = cfg.legacy_windows()
    costs = cfg.load_costs()
    model_cfg = cfg.load_model("london_sweep_reversal")

    print("Loading", args.csv)
    df, mode, bar = _prepare_bars(args.csv, args.tz)
    if bar > 15:
        sys.exit(f"Bars look like {bar:.0f}-minute. Use M1 or M5 data for session analysis.")
    print(f"  {len(df):,} bars, {bar:.0f}-min, server-time mode: {mode}")

    tz_check = timezones.sanity_check(df, windows["pip"])
    if not tz_check["ok"]:
        print(f"  WARNING: volatility peak is hour {tz_check['peak_hour']}, not inside 08:00-11:00 NY. "
              f"Your broker's server-time convention may not be 'ny+7' -- pass --tz to override.")

    dq = quality.check_bars(df)

    d = days_mod.build_days(df, windows)
    if len(d) < 60:
        sys.exit(f"Only {len(d)} complete trading days -- need at least ~60 (ideally 250+).")
    split_date = d.index[int(len(d) * (1 - args.oos))]
    print(f"  {len(d)} trading days  |  out-of-sample from {split_date:%Y-%m-%d}")

    H, m = hyp_mod.evaluate(d, split_date)

    model_params = dict(model_cfg.params)
    model_params["default_cost_pips"] = costs.default_cost_pips
    trades = lsr.backtest(df, d, windows["pip"], model_params)
    st_all = stats_mod.r_stats(trades.R_net) if len(trades) else {"n": 0}
    st_is = stats_mod.r_stats(trades[trades.td < split_date].R_net) if len(trades) else {"n": 0}
    st_oos = stats_mod.r_stats(trades[trades.td >= split_date].R_net) if len(trades) else {"n": 0}

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = args.out or os.path.join("reports", run_id)
    os.makedirs(out_dir, exist_ok=True)

    figs = charts_mod.build(df, d, trades, split_date, windows["pip"])
    meta = dict(file=os.path.basename(args.csv), first=f"{d.index[0]:%Y-%m-%d}", last=f"{d.index[-1]:%Y-%m-%d}",
                tz=mode, bar=bar, split=f"{split_date:%Y-%m-%d}", n_days=len(d))

    report_html = html_mod.build(meta, d, H, m, trades, st_all, st_is, st_oos, figs, windows["pip"], model_params)
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(report_html)
    d.to_csv(os.path.join(out_dir, "days.csv"))
    trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False)
    H.to_csv(os.path.join(out_dir, "hypotheses.csv"), index=False)

    model_stats = None
    if st_all.get("n"):
        model_stats = dict(
            name=model_cfg.name, version=model_cfg.version,
            oos=dict(n=st_oos.get("n", 0),
                      E=round(float(st_oos.get("expectancy", float("nan"))), 4),
                      ci=[round(float(st_oos.get("ci_lo", float("nan"))), 4),
                          round(float(st_oos.get("ci_hi", float("nan"))), 4)]),
            verdict="promising" if st_oos.get("n", 0) and st_oos.get("ci_lo", -1) > 0 else "not proven",
        )

    summ = summary_mod.build(run_id, meta, tz_check, H, m, model_stats)
    summ["data_quality"] = dq
    summary_mod.write(summ, os.path.join(out_dir, "summary.json"))

    if not args.no_cache:
        cache_mod.save(df, d, cache_dir=args.cache_dir)

    print("\nHypotheses passing Bonferroni AND out-of-sample:",
          ", ".join(H[H.bonferroni_sig & H.oos_holds].hypothesis) or "none")
    if st_all.get("n"):
        print(f"Example model: {st_all['n']} trades, E = {st_all['expectancy']:+.3f}R net, "
              f"OOS E = {st_oos.get('expectancy', float('nan')):+.3f}R "
              f"(CI {st_oos.get('ci_lo', float('nan')):+.2f} to {st_oos.get('ci_hi', float('nan')):+.2f})")
    print(f"\nReport:  {os.path.abspath(os.path.join(out_dir, 'report.html'))}")
    print(f"Summary: {os.path.abspath(os.path.join(out_dir, 'summary.json'))}")


def _not_yet(name, phase):
    def _f(args):
        print(f"'{name}' isn't built yet -- it's scheduled for {phase} (see docs/ROADMAP.md).")
    return _f


def main():
    ap = argparse.ArgumentParser(prog="nylab", description="EURUSD Session Research Lab")
    sub = ap.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="load bars, build the day table, test hypotheses, "
                                        "run the example model, write report.html + summary.json")
    p_run.add_argument("csv")
    p_run.add_argument("--tz", default="auto", help="auto | ny+7 | ny | utc | utc+N | eu")
    p_run.add_argument("--oos", type=float, default=0.3, help="fraction of most recent days held out")
    p_run.add_argument("--out", default=None, help="output dir; default reports/<run-id>/")
    p_run.add_argument("--run-id", dest="run_id", default=None)
    p_run.add_argument("--cache-dir", dest="cache_dir", default="data/cache")
    p_run.add_argument("--no-cache", dest="no_cache", action="store_true")
    p_run.set_defaults(func=cmd_run)

    for name, phase in [
        ("export", "Phase 9 (mt5_export.py at the repo root still works standalone today)"),
        ("calendar-import", "Phase 4"),
        ("hypothesis", "Phase 3"),
        ("snapshot", "Phase 8"),
        ("replay", "Phase 2"),
    ]:
        p = sub.add_parser(name)
        p.set_defaults(func=_not_yet(name, phase))

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
