# REPLAY_TRAINER.md — free, offline bar-replay trainer with day navigation

Goal: replace TradingView's paid intraday Bar Replay with a tool that is **better for this user**:
it runs on his own MT5 data, jumps straight to any date, lists days in a table he can **filter**
(by date, weekday, news, session character, what got raided…), and simulates his Maven account.

## 1. How it runs

- `python -m nylab replay` → starts a local server on `http://localhost:8765` and opens the browser.
- **Fully offline:** vendor `lightweight-charts` (TradingView's open-source charting library, Apache-2.0)
  into `nylab/replay/static/vendor/`. No CDN. No internet needed after install.
- Backend: Python standard-library `http.server` + a small JSON router (FastAPI only if it clearly
  simplifies things). Data loaded once from the parquet cache built by `nylab run`
  (`data/cache/bars_M5.parquet`, `days.parquet`, `sessions.parquet`, `calendar.parquet`, `events.parquet`).
- Front-end: one `index.html` + `app.js` + `style.css`, plain JS (no build step, no npm).

## 2. Screen layout

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ [Date ▾ 2024-03-12] [◀ prev day] [next day ▶] [🎲 random]  TF: M1 M5 M15 H1 H4 D1 │
│ Start at: (•) 17:00 prev  ( ) 02:00  ( ) 07:00  ( ) 09:30  ( ) custom __:__      │
├──────────────────────────────┬────────────────────────────────────────────────┤
│  DAY NAVIGATOR (left, 30%)   │                 CHART (70%)                    │
│  Filters ▾                   │   session boxes · levels · news markers        │
│  ┌ table of trading days ──┐ │                                                │
│  │date dow news Asia Lon   │ │                                                │
│  │     NYAM NYPM range ... │ │                                                │
│  └─────────────────────────┘ │                                                │
│  Presets: [London chop] ...  │  [⏮ -1] [▶ play] [⏭ +1 bar] speed ▾  jump to __:__ │
├──────────────────────────────┴────────────────────────────────────────────────┤
│ ACCOUNT: Maven 5k Step 1 · Balance $5,120 · Day P&L −1.2% (limit 4%) · Max DD 2.1% (limit 8%) │
│ [BUY] [SELL]  risk % [0.5]  SL [____] TP [____]  → lots 0.12   Open trade: +0.8R  [Close]   │
└───────────────────────────────────────────────────────────────────────────────┘
```
Layout is a guide, not a pixel spec; keep it clean and readable, dark theme default with a light toggle.

## 3. Day navigation — the feature the user asked for

- **Date picker** (calendar popup + typed `YYYY-MM-DD`): loads that trading day immediately — no scrolling.
- **Day table** (virtualised list; 1,300+ rows must scroll smoothly). Columns (sortable, toggleable):
  `date, weekday, news badges (NFP/CPI/FOMC/ECB/red USD/red EUR), asia/lon/nyam/nypm character,
  day_type, day range (pips), NY AM range, which levels NY raided`. Click a row → load that day.
- **Filters** (combine with AND; count of matching days shown live):
  - date range (from/to), specific months/years, weekdays
  - news: has any red USD / red EUR / specific families; surprise sign; "no news days only"
  - session character per session (multi-select, e.g. London ∈ {chop, quiet})
  - raids: e.g. "NY AM took London high", "London took Asia low", "outside day"
  - ranges: ADR ratio above/below X, London range_rel > X
  - **advanced:** free-text DSL (same safe DSL as hypotheses), e.g. `lon.character=='chop' and nyam.took_prev_high`
  - "exclude thin/holiday days" (default on)
- **Hide outcome columns** toggle (default ON while practising): columns describing the *current* day's
  later sessions (NY AM/PM character, day_type, day range) are hidden so the table doesn't spoil the day.
  Filters on those columns still work but show a "spoiler" warning icon.
- **Prev/next day** buttons move through the *filtered* list; **Random** picks a random filtered day.
- **Presets**: save/load named filter sets to `research/replay/presets.json`. The research agent writes
  presets for every candidate hypothesis (CLAUDE.md §6.6) so the user can study exactly those days.
- **Blind mode** (toggle): hides the date and the price axis labels' absolute level (shows pips relative
  to the day open) so he can't recall famous days.

## 4. Context & timeframes

- On load, the chart shows **all history before the start time** (default: the previous 10 trading days
  on M5; D1/H4 show 6 months) — so HTF context is there without scrolling.
- Timeframes M1 (if data exists), M5, M15, H1, H4, D1. Higher-TF candles are built server-side by
  resampling **only revealed bars**; the currently-forming HTF candle updates live as bars are revealed.
- Keep scroll/zoom when switching TF; "jump to cursor" button.

## 5. Playback controls

- `→` / `+1 bar` reveal next M5 bar (or next bar of the smallest loaded TF); `Shift+→` +1 hour
- Play/pause with speeds (1 bar per 1s, 0.5s, 0.2s, 0.05s)
- **Jump to time** (e.g. 08:25) — reveals everything up to that time
- `←` step back: allowed only in **Review mode** (after the day is finished) or if the user toggles
  "allow rewind" — every rewind is logged on open trades to keep practice honest
- End-of-day → Review mode: full day revealed + the lab's computed events (sweeps, FVGs, MSS, session
  characters) overlaid so he can compare what he saw vs what the rules detected.

## 6. Overlays (all computed from revealed data only)

Toggle each: session shaded boxes (Asia/London/NY AM/lunch/NY PM, SB windows in a distinct colour),
Asia & London high/low lines extending right, PDH/PDL, PWH/PWL, midnight/08:30/09:30 opens, CBDR and
Asia SD projection levels (±1, ±2, ±2.5), news markers (vertical line + tooltip with event, forecast;
**actual only after release time**). Minimal drawing tools: horizontal line, rectangle, Fibonacci with
OTE (0.62/0.705/0.79) — drawings saved per day in `research/replay/drawings/<date>.json`.

## 7. The no-leak rule (critical)

The **server** never sends bars later than the cursor. API:
- `GET /api/days?filter=...` → day list (outcome columns omitted unless "hide outcome" is off)
- `GET /api/bars?td=2024-03-12&tf=M5&until=2024-03-12T08:25` → bars with close time ≤ until
- `GET /api/levels?td=...&until=...` → only levels whose `available_at` ≤ until
- `GET /api/news?td=...&until=...` → scheduled events; `actual` only if release ≤ until
Automated test: for 100 random (td, until) pairs, assert no returned bar/level/news-actual is after `until`.

## 8. Mock trading & Maven account simulation

- Order ticket: BUY/SELL at market (next bar open — conservative) or limit/stop at a price; SL and TP
  required (warn if missing); risk % → lot size computed from balance, SL distance and EURUSD pip value
  (Formula Handbook 2.1), rounded **down** to 0.01.
- Fill engine = the same backtest engine rules (stop wins same-bar ties; spread from data or 1.0 pip default).
- Drag SL/TP lines on chart; move to BE button; partial close (25/50/75%).
- **Account panel:** Maven preset ($5,000, step 1 +10%, step 2 +8%, 4% daily, 8% max, static balance-based);
  live day P&L %, distance to daily and max limit (turns amber at 50%, red at 75%); breach → trade closed,
  attempt marked failed.
- **Challenge mode:** plays a sequence of random filtered days in chronological order with the balance
  carried over, until pass or fail. Report: days, trades, win rate, expectancy R, max DD.
- **Journal:** after each closed trade, a small form: setup tag (from his model list), rules followed Y/N,
  emotion 1–5, notes; auto screenshot of the chart (canvas → PNG). Saved to `research/replay/trades.csv`
  in the Strategy Guide's trade-log columns + `research/replay/shots/`.
- Stats tab: all replay trades → expectancy, win rate, by setup tag, by session, by filter preset —
  same stats module as the backtests, so manual and coded results are directly comparable.

## 9. Acceptance criteria

1. Date picker jump to any date in < 1 s on 5 years of M5.
2. Filter "London = chop AND has red USD news" returns the correct days (cross-check with sessions table).
3. No-leak test passes; D1/H4 forming candle equals resample of revealed M5 bars.
4. A full mock trade (limit entry, SL, TP, BE move, partial) produces the same R as the engine would.
5. Maven daily-limit breach triggers correctly in a scripted test.
6. Works with the Wi-Fi off.
