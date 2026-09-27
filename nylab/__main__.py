"""nylab -- CLI. `python -m nylab run <csv>` reproduces v0's full pipeline (day table, the 15
hypotheses, the example model, report.html) through the nylab/ package, plus a parquet cache
and summary.json (ROADMAP Phase 1). export/calendar-import/hypothesis/snapshot/replay are
stubs for now -- wired up in the phases named in docs/ROADMAP.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd

from nylab import cache as cache_mod
from nylab import calendar_io
from nylab import config as cfg
from nylab import days as days_mod
from nylab import sessions as sessions_mod
from nylab import hyp_engine, hyp_loader
from nylab import label_validate
from nylab import ledger as ledger_mod
from nylab import stats as stats_mod
from nylab.data import loader, quality, timezones
from nylab.models import london_sweep_reversal as lsr
from nylab.report import charts as charts_mod
from nylab.report import html as html_mod
from nylab.report import sessions_section as sessions_section_mod
from nylab.report import summary as summary_mod
from nylab.replay import server as replay_server


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

    cal = None
    if os.path.exists(args.calendar):
        cal = calendar_io.load_cache(args.calendar)
        d = days_mod.attach_calendar_features(d, cal, cfg.sessions())
        print(f"  attached news features from {args.calendar} "
              f"({cal['currency'].eq('USD').sum()} USD / {cal['currency'].eq('EUR').sum()} EUR rows)")
    else:
        print(f"  no calendar cache at {args.calendar} -- skipping news features "
              f"(run `nylab calendar-import` first if you want them; see ROADMAP Phase 4).")

    # ROADMAP Phase 5.1/5.2: the SESSION table (all sessions except cbdr) + character labels +
    # day types, wide-joined onto `d` so hypothesis YAMLs can use dotted cross-session syntax
    # (`lon.character`, `nyam_full.took_prev_high`, `day.has_fomc`). COLUMN_DOCS's own
    # registration for these columns already happened at nylab.hyp_loader's import time (see
    # that module) -- imported above via `from nylab import hyp_engine, hyp_loader`, so it's
    # already done by the time we get here, before hyp_loader.load_all() runs its look-ahead
    # check further down.
    sessions_cfg = cfg.sessions()
    session_tables = sessions_mod.build_all_sessions(df, d, cal, sessions_cfg, windows["pip"])
    d = sessions_mod.attach_session_features(d, session_tables)
    skipped = d.attrs.get("sessions_skipped_columns")
    if skipped:
        print(f"  session-table columns kept as their pre-existing legacy meaning "
              f"(name collision, see nylab/sessions.py): {skipped}")
    day_types = sessions_mod.build_day_types(d)
    d = d.join(day_types)
    print(f"  built the SESSION table for {len(sessions_mod.SESSION_IDS)} sessions "
          f"({d.shape[1]} day-table columns total)")

    split_date = d.index[int(len(d) * (1 - args.oos))]
    print(f"  {len(d)} trading days  |  out-of-sample from {split_date:%Y-%m-%d}")

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M")
    hyps = hyp_loader.load_all()
    ledger_path = args.ledger_path  # ARCHITECTURE.md S1: the repo-level ledger, append-only across runs
    H, ledger_rows, m, bonf_alpha = hyp_engine.evaluate(d, hyps, split_date, run_id=run_id,
                                                         ledger_path=ledger_path)

    model_params = dict(model_cfg.params)
    model_params["default_cost_pips"] = costs.default_cost_pips
    trades = lsr.backtest(df, d, windows["pip"], model_params)
    st_all = stats_mod.r_stats(trades.R_net) if len(trades) else {"n": 0}
    st_is = stats_mod.r_stats(trades[trades.td < split_date].R_net) if len(trades) else {"n": 0}
    st_oos = stats_mod.r_stats(trades[trades.td >= split_date].R_net) if len(trades) else {"n": 0}

    out_dir = args.out or os.path.join("reports", run_id)
    os.makedirs(out_dir, exist_ok=True)

    figs = charts_mod.build(df, d, trades, split_date, windows["pip"])
    figs.update(sessions_section_mod.build_figs(df, windows["pip"]))
    meta = dict(file=os.path.basename(args.csv), first=f"{d.index[0]:%Y-%m-%d}", last=f"{d.index[-1]:%Y-%m-%d}",
                tz=mode, bar=bar, split=f"{split_date:%Y-%m-%d}", n_days=len(d))

    extra_section = sessions_section_mod.build(df, d, session_tables, sessions_cfg, cal, H, windows["pip"], figs)
    report_html = html_mod.build(meta, d, H, m, trades, st_all, st_is, st_oos, figs, windows["pip"], model_params,
                                  extra_section=extra_section)
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
            verdict=stats_mod.model_verdict(st_oos),  # ROADMAP 5.7.5: promising/negative/not proven
        )

    summ = summary_mod.build(run_id, meta, tz_check, H, m, model_stats, bonferroni_alpha=bonf_alpha)
    summ["data_quality"] = dq
    summary_mod.write(summ, os.path.join(out_dir, "summary.json"))

    ledger_mod.append(ledger_rows, path=ledger_path)

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


def cmd_calendar_import(args):
    """ROADMAP 4.2/4.4: convert mql5/ExportCalendar.mq5's calendar_export.csv (or a 4.4 fallback
    CSV) into data/calendar.parquet. tz_mode MUST be the same mode `nylab run` used for the price
    bars (SESSIONS_AND_CONTEXT.md S4) -- pass the exact same --tz value, or leave both on auto's
    default "ny+7" if that's what your `nylab run` printed as "server-time mode"."""
    df = calendar_io.load(args.csv, tz_mode=args.tz)
    if len(df) == 0:
        sys.exit(f"{args.csv}: parsed 0 rows -- check the file isn't empty and matches one of the "
                  f"two expected schemas (see docs/SESSIONS_AND_CONTEXT.md S4).")
    calendar_io.save(df, args.out)
    by_ccy = df["currency"].value_counts()
    print(f"Imported {len(df)} events ({df['time_ny'].min():%Y-%m-%d} -> {df['time_ny'].max():%Y-%m-%d}), "
          f"by currency: {dict(by_ccy)}")
    print(f"Saved {os.path.abspath(args.out)} -- `nylab run` will pick it up automatically next time "
          f"(via --calendar, default data/calendar.parquet).")


def cmd_hypothesis_add(args):
    """ROADMAP 3.6: scaffold a new hypothesis YAML from a template, so adding an idea is
    'fill in a form', not 'write Python and risk a look-ahead bug'. Deliberately writes
    condition/outcome/baseline as TODO placeholders rather than guessing -- nylab.hyp_loader
    will refuse to load them until they're real expressions."""
    path = os.path.join(args.directory, f"{args.id}.yaml")
    if os.path.exists(path):
        sys.exit(f"{path} already exists -- bump the version inside it instead of overwriting "
                  f"(RESEARCH_PROTOCOL.md S4: changing a hypothesis's definition is a new version, "
                  f"counted in m; re-running an unchanged one is not).")
    os.makedirs(args.directory, exist_ok=True)
    template = f"""id: {args.id}
version: "1.0"
title: "{args.title}"
codex_ref: ""
decision_time_h: {args.decision_time_h}
condition: "TODO -- a column/expression known by decision_time_h (see docs/FEATURES_SPEC.md, nylab.days.COLUMN_DOCS)"
outcome: "TODO -- the future result being tested"
baseline: "TODO -- same outcome expression, evaluated over ALL eligible days"
min_n: 60
notes: ""
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(template)
    print(f"Wrote {path}. Fill in condition/outcome/baseline, then it'll load and run alongside "
          f"the others next time you run `python -m nylab run`. It will be REJECTED at load time "
          f"if its condition uses a column not yet known by decision_time_h={args.decision_time_h} "
          f"(RESEARCH_PROTOCOL.md S3).")


def cmd_label_validate_build(args):
    """ROADMAP 5.6: sample days, package their bars + computed character/day_type labels into
    a single self-contained HTML page (no server needed) for Akash to click through offline."""
    html, payload = label_validate.build(args.cache_dir, cfg.sessions(), n=args.n, seed=args.seed,
                                          strategy=args.strategy)
    os.makedirs(args.out_dir, exist_ok=True)
    html_path = os.path.join(args.out_dir, f"sample_{args.seed}.html")
    meta_path = os.path.join(args.out_dir, f"sample_{args.seed}_meta.json")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"Wrote {len(payload['days'])} sampled days to {os.path.abspath(html_path)}")
    print(f"Open it in a browser, click Agree/Disagree for every row, then \"Download my answers\".")
    print(f"Once you have the exported label_validation_answers.json, run:")
    print(f"  python -m nylab label-validate score <path-to-answers.json> --meta {meta_path}")


def cmd_label_validate_score(args):
    """ROADMAP 5.6: score Akash's exported answers.json against the sampled meta payload --
    per-label agreement rate, flagged red if below the 80% accept bar."""
    with open(args.meta, encoding="utf-8") as f:
        payload = json.load(f)
    with open(args.answers, encoding="utf-8") as f:
        answers_doc = json.load(f)
    result = label_validate.score(answers_doc.get("answers", {}), payload)
    if len(result) == 0:
        sys.exit("No answered rows found -- did you click Agree/Disagree before downloading?")
    pd.set_option("display.width", 120)
    print(result.to_string(index=False))
    failing = result[~result["passes_80pct"]]
    if len(failing):
        print(f"\n{len(failing)} label(s) below the 80% accept bar -- adjust thresholds "
              f"with Akash and re-validate (RESEARCH_PROTOCOL.md S-thresholds-frozen-once-validated):")
        print(failing.to_string(index=False))
    else:
        print("\nEvery label cleared the 80% agreement bar.")


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
    p_run.add_argument("--ledger-path", dest="ledger_path", default="research/ledger.csv",
                        help="append-only multiple-testing ledger (RESEARCH_PROTOCOL.md S4)")
    p_run.add_argument("--calendar", default="data/calendar.parquet",
                        help="calendar cache from `nylab calendar-import` (ROADMAP Phase 4); "
                             "silently skipped if the file doesn't exist")
    p_run.set_defaults(func=cmd_run)

    p_replay = sub.add_parser("replay", help="launch the offline replay trainer (opens your browser)")
    p_replay.add_argument("--cache-dir", dest="cache_dir", default="data/cache")
    p_replay.add_argument("--host", default="127.0.0.1")
    p_replay.add_argument("--port", type=int, default=8765)
    p_replay.add_argument("--no-browser", dest="open_browser", action="store_false")
    p_replay.add_argument("--calendar", default="data/calendar.parquet",
                           help="ROADMAP 6.5: calendar cache for news markers; missing file is fine, news just stays empty")
    p_replay.set_defaults(func=lambda a: replay_server.serve(a.cache_dir, a.host, a.port, a.open_browser, a.calendar))

    p_hyp = sub.add_parser("hypothesis", help="scaffold a new hypothesis YAML file (ROADMAP 3.6)")
    hyp_sub = p_hyp.add_subparsers(dest="hyp_command", required=True)
    p_hyp_add = hyp_sub.add_parser("add", help="write config/hypotheses/<id>.yaml from a template")
    p_hyp_add.add_argument("id", help="e.g. H016")
    p_hyp_add.add_argument("title", help="plain-English one-line description")
    p_hyp_add.add_argument("--decision-time-h", dest="decision_time_h", type=float, required=True,
                            help="NY hour (relative to td midnight) by which the condition must be decidable")
    p_hyp_add.add_argument("--dir", dest="directory", default="config/hypotheses")
    p_hyp_add.set_defaults(func=cmd_hypothesis_add)

    p_lv = sub.add_parser("label-validate", help="ROADMAP 5.6: sample days and validate computed "
                                                   "character/day_type labels with Akash")
    lv_sub = p_lv.add_subparsers(dest="lv_command", required=True)
    p_lv_build = lv_sub.add_parser("build", help="sample days, write a self-contained HTML review page")
    p_lv_build.add_argument("--n", type=int, default=14)
    p_lv_build.add_argument("--seed", type=int, default=44,
                             help="44+ for the curated strategy round-4 revision (<15 days, \"normal\" "
                                  "excluded); round 3 used seed 43/n=20 with the old (pre-greedy) floor, "
                                  "rounds 1-2 used seed 42 with --strategy random")
    p_lv_build.add_argument("--strategy", choices=["curated", "random"], default="curated",
                             help="'curated' (default, ROADMAP 5.6 round 3+): near-rule-boundary fill "
                                  "beyond the stratified floor. 'random': the original round 1/2 "
                                  "uniform-random fill, kept for reproducing old rounds.")
    p_lv_build.add_argument("--cache-dir", dest="cache_dir", default="data/cache")
    p_lv_build.add_argument("--out-dir", dest="out_dir", default="research/label_validation")
    p_lv_build.set_defaults(func=cmd_label_validate_build)
    p_lv_score = lv_sub.add_parser("score", help="score an exported answers.json against the sampled meta")
    p_lv_score.add_argument("answers")
    p_lv_score.add_argument("--meta", required=True)
    p_lv_score.set_defaults(func=cmd_label_validate_score)

    p_cal = sub.add_parser("calendar-import", help="convert calendar_export.csv (or a fallback "
                                                     "CSV) into data/calendar.parquet (ROADMAP 4.2/4.4)")
    p_cal.add_argument("csv")
    p_cal.add_argument("--tz", default="ny+7", help="MUST match the --tz your `nylab run` used for bars")
    p_cal.add_argument("--out", default="data/calendar.parquet")
    p_cal.set_defaults(func=cmd_calendar_import)

    for name, phase in [
        ("export", "Phase 9 (mt5_export.py at the repo root still works standalone today)"),
        ("snapshot", "Phase 8"),
    ]:
        p = sub.add_parser(name)
        p.set_defaults(func=_not_yet(name, phase))

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
