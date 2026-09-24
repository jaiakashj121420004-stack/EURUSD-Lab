# ARCHITECTURE.md — target design

v0 lives in two scripts. The target is a small, testable Python package. Refactor v0 into this
shape in Phase 1 **without changing results** (Phase 1 acceptance compares outputs with the v0 golden files).

## 1. Package layout

```
eurusd-lab/                     (repo root — the project is "EURUSD Session Research Lab"; older docs called it "NY Session Research Lab" before scope grew to all sessions)
├── nylab/
│   ├── __main__.py            # CLI: export | run | hypothesis | snapshot | ledger
│   ├── config.py              # load + validate YAML configs (dataclasses)
│   ├── data/
│   │   ├── mt5_source.py      # ONLY file importing MetaTrader5 (Windows). Export + incremental update
│   │   ├── loader.py          # CSV (python export or MT5 'Export Bars') → canonical bars DataFrame
│   │   ├── timezones.py       # server→NY conversion, auto-detect, sanity checks
│   │   └── quality.py         # data-quality checks (DATA_AND_TIME §5)
│   ├── features/
│   │   ├── sessions.py        # per-day windows: CBDR, Asia, London KZ, pre-NY, NY, NY AM, opens
│   │   ├── levels.py          # PDH/PDL, midnight open, weekly high/low, ADR/ATR, SD projections
│   │   ├── swings.py          # fractal swing highs/lows, HH/HL/LH/LL labels, structure score
│   │   ├── fvg.py             # fair value gaps (+ CE, fill tracking)
│   │   ├── displacement.py    # displacement candles
│   │   ├── mss.py             # market structure shift on LTF after a sweep
│   │   ├── sweeps.py          # raid/sweep events of any level with 'close back inside' flag
│   │   └── regime.py          # ADR ratio, efficiency ratio, ADX, choppiness (Formula Handbook Part 6)
│   ├── events.py              # builds the EVENT table (one row per sweep/FVG/MSS with timestamps)
│   ├── days.py                # builds the DAY table (one row per td) from features
│   ├── sessions.py            # builds the SESSION table (td × session) + character labels (SESSIONS_AND_CONTEXT §2–3)
│   ├── crosssession.py        # transition matrices, news-conditioned matrices, SB window stats
│   ├── calendar/
│   │   ├── importer.py        # MQL5-export CSV / fallback CSV → calendar.parquet (NY time)
│   │   └── features.py        # surprise z, event families, per-session/per-day news flags
│   ├── replay/                # REPLAY_TRAINER.md
│   │   ├── server.py          # local HTTP server + JSON API (no-leak enforced here)
│   │   ├── api.py             # /api/days, /api/bars, /api/levels, /api/news, /api/trades
│   │   ├── sim.py             # mock-trade fills (reuses backtest engine rules) + Maven account state
│   │   └── static/            # index.html, app.js, style.css, vendor/lightweight-charts.standalone.js
│   ├── hypotheses/
│   │   ├── registry.py        # load research/hypotheses/*.yaml, evaluate, return results
│   │   └── dsl.py             # tiny, safe expression language over DAY-table columns
│   ├── backtest/
│   │   ├── engine.py          # bar-by-bar, one position at a time, no look-ahead, cost model
│   │   ├── costs.py           # spread/commission/slippage model
│   │   └── models/            # one file per rule-based model (plugin interface below)
│   │       ├── base.py
│   │       ├── london_sweep_reversal.py   # = v0 example model
│   │       └── silver_bullet_fvg.py        # Phase 7 (runs in London, NY AM and NY PM SB windows)
│   ├── stats/
│   │   ├── proportions.py     # z-test, Wilson CI, binomial
│   │   ├── expectancy.py      # R stats, CI, t, SQN, PF, drawdown, streaks
│   │   ├── multiple.py        # Bonferroni, Benjamini-Hochberg, ledger-aware thresholds
│   │   ├── montecarlo.py      # trade-sequence shuffles, bootstrap CIs
│   │   └── walkforward.py     # rolling IS/OOS splits
│   ├── report/
│   │   ├── html.py            # report.html (self-contained, base64 charts)
│   │   ├── charts.py          # matplotlib figures
│   │   ├── snapshot.py        # chart of a day/trade with levels drawn (mplfinance)
│   │   └── summary.py         # summary.json for Claude to read
│   └── ledger.py              # append-only research ledger
├── mql5/
│   └── ExportCalendar.mq5     # read-only MQL5 script: economic calendar → CSV (SESSIONS_AND_CONTEXT §4)
├── config/
│   ├── windows.yaml           # ALL session windows (NY hours) — SESSIONS_AND_CONTEXT §1
│   ├── session_character.yaml # thresholds for trend/reversal/range/chop/quiet labels
│   ├── prop.yaml              # Maven 5k 2-step rules (targets, 4% daily, 8% max, static balance-based)
│   ├── features.yaml          # thresholds: swing fractal size, FVG min size, displacement k…
│   ├── costs.yaml
│   └── models/*.yaml          # parameters per model
├── research/
│   ├── hypotheses/*.yaml      # one file per hypothesis
│   ├── ledger.csv             # every test ever run (append-only)
│   └── JOURNAL.md             # human-readable research diary
├── data/                      # raw CSVs + *.meta.json (git-ignored)
├── reports/<YYYYmmdd-HHMM>/   # report.html, summary.json, days.csv, events.csv, trades.csv
└── tests/
```

## 2. Data flow

```
MT5 ──mt5_source──▶ data/*.csv ──loader+timezones+quality──▶ BARS
BARS ──features/*──▶ DAY table (1 row / td)      EVENT table (1 row / event)
DAY  ──hypotheses registry──▶ hypothesis results ─┐
BARS+DAY+EVENTS ──backtest engine + model──▶ TRADES ─┤──▶ stats ──▶ ledger + report + summary.json
```

## 3. Canonical schemas

**BARS** (index = RangeIndex, sorted by `ny`):
`server` (datetime64, naive) · `ny` (datetime64, naive, NY wall clock) · `td` (datetime64 date) ·
`h` (float NY hours rel. to td midnight; −7…17) · `open high low close` (float) ·
`spread_pips` (float, NaN if unknown) · `tick_volume` (int) · `thin_day`, `gappy` (bool, per td broadcast)

**DAY** (index = `td`): every level as price (`lon_high`, `asia_low`, `pdh`, `mid_open`, `o0930`…),
every window's `*_open/_high/_low/_close/_hi_t/_lo_t` (`_t` in NY hours), ranges in pips
(`*_range`), ADR/ATR, regime scores, raid flags (`ny_takes_lon_high` + `_t`), directions
(`ny_drive` = sign(ny_close − o0930)), `dow`, `is_oos`. Column naming: `<window>_<field>`.
**Rule:** a DAY column must document (in `days.py` COLUMN_DOCS dict) the latest NY hour whose
data it uses — `available_at_h`. Hypotheses/models may only condition on columns with
`available_at_h` ≤ the decision time. This is how look-ahead is prevented structurally.

**SESSION** (index = `td`, `session_id`): see SESSIONS_AND_CONTEXT §2. Also exposed to the DSL as dotted
columns (`lon.er`, `nyam.character`) by pivoting to wide format joined onto DAY.

**CALENDAR**: `release_ny, currency, event_id, event_name, family, importance, actual, forecast, previous, surprise, surprise_z`.

**EVENTS**: `event_id, td, type (sweep|fvg|mss|displacement), side (bull|bear), t_ny, h, level_name,
level_price, extreme_price, close_back_inside (bool), bars_to_close_back, size_pips, ...`

**TRADES**: `td, model, model_version, side, entry_time_ny, entry, stop, target, exit_time_ny, exit,
reason (stop|target|time|manual), risk_pips, R_gross, cost_R, R_net, is_oos, context columns copied
from DAY for later slicing`.

## 4. Model plugin interface

```python
class Model(Protocol):
    name: str
    version: str                        # bump on ANY rule change → new ledger row
    params: dict                        # from config/models/<name>.yaml

    def signals(self, day_bars: pd.DataFrame, day: pd.Series, events: pd.DataFrame) -> list[Signal]:
        """Return entry signals for one td using ONLY information available at each signal's bar.
        Signal = (bar_index, side, entry_price, stop_price, target_price | None, time_exit_h)."""
```

The **engine**, not the model, walks bars forward from the signal, applies the conservative
same-bar rule, time exits and costs. Models never see future bars: the engine passes
`day_bars.iloc[:i+1]` when asking for signals at bar `i` (slow but safe), or a model may
compute vectorised signals **if** it has a look-ahead test proving equivalence.

## 5. Hypothesis YAML format

```yaml
id: H014
title: "Pre-NY raid of London high only → NY drive down"
codex_ref: "Ch.3 sweeps, Ch.5 Judas swing"
decision_time_h: 9.5          # columns used must be available by 09:30 NY
condition: "pre_takes_lon_high and not pre_takes_lon_low"
outcome: "ny_drive < 0"
baseline: "ny_drive < 0"      # evaluated over all eligible days
min_n: 60
notes: "From report 2026-10-02: NY high forms 09:30-10:30 on 38% of days."
```

The DSL is a whitelist evaluator (column names, numbers, `and/or/not`, comparisons, `abs`,
`quantile(col, q)`, `median(col)`) — **never `eval` raw strings**.

## 6. summary.json (what Claude reads after each run)

```json
{"run_id": "...", "data": {"first": "...", "last": "...", "days": 1240, "tz_mode": "ny+7", "tz_sanity": "ok"},
 "ledger_total_tests": 37, "bonferroni_alpha": 0.00135,
 "descriptive": {"ny_high_hour_mode": 10, "ny_takes_lon_high": 0.41, ...},
 "hypotheses": [{"id": "H014", "n": 228, "hit": 0.544, "baseline": 0.531, "z": 0.4, "p": 0.69,
                 "bonf_sig": false, "bh_sig": false, "oos_hit": 0.52, "oos_holds": false, "verdict": "noise"}],
 "models": [{"name": "london_sweep_reversal", "version": "1.0", "oos": {"n": 82, "E": -0.26, "ci": [-0.55, 0.04]}, "verdict": "not proven"}]}
```
Verdict vocabulary (exact strings): `noise`, `weak`, `candidate`, `promising`, `not proven`,
`survives-oos`, `killed`.
