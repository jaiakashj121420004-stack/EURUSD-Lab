# DATA_AND_TIME.md — getting the data and the clock right

Most wrong research results come from here, not from clever maths. Treat this file as law.

## 1. Getting data out of MT5

**Source:** the `MetaTrader5` Python package talks to a *running, logged-in* MT5 terminal on the
same Windows machine. It is read-only for our purposes.

```python
import MetaTrader5 as mt5
mt5.initialize()                                   # terminal must be open
rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, dt_from_utc, dt_to_utc)
mt5.shutdown()
```

Returned fields: `time` (int seconds — **broker server time presented as if UTC**), `open`, `high`,
`low`, `close`, `tick_volume`, `spread` (in **points**), `real_volume` (0 for FX).

Known pitfalls (v0 `mt5_export.py` already handles 1–4):
1. **Symbol suffixes.** Brokers name it `EURUSD`, `EURUSD.m`, `EURUSDm`, `EURUSD.raw`… search
   `mt5.symbols_get()` for names starting with the base and prefer the shortest.
2. **History depth.** Limited by *Tools → Options → Charts → Max bars in chart* (set Unlimited,
   restart MT5) and by what the broker's server stores. M1 is often only 1–2 years; M5 usually 5+.
   If fewer years come back than asked, say so; suggest scrolling the chart back (Home key) to force
   a download, or using M5.
3. **Chunk requests** (≤ 1 year per `copy_rates_range` call) — large single requests sometimes fail.
4. **`time` is server time.** Never label it UTC. Convert (§2).
5. **Alternative path (no Python on Windows):** MT5 → View → Symbols → Bars tab → select EURUSD,
   M5, date range → *Request* → *Export Bars* → CSV with `<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE>
   <TICKVOL> <VOL> <SPREAD>` (tab-separated). The loader must accept this format too
   (v0 accepts DATE/TIME columns; make it robust to `<>` headers and tab separators).

Future (Phase 9): a Windows Task Scheduler job runs the export nightly after 17:30 NY so `data/`
stays current. The export appends only new bars (incremental by last timestamp).

## 2. Server time → New York time

The chart the user sees in MT5 is in broker server time. Our analysis is in **New York time**.

| Broker convention | What it means | How to convert |
|---|---|---|
| **"NY close" (most common)** | Server = UTC+2 in NY winter, UTC+3 in NY summer; midnight server = 17:00 NY | `ny = server − 7h` (all year, DST handled automatically because the server follows US DST) |
| Fixed UTC | Server = UTC | localise UTC → convert to `America/New_York` |
| Fixed UTC+N | Server = UTC+N, no DST | subtract N h → UTC → convert to NY |
| EU-DST servers (UTC+2/+3 following **EU** DST) | Mismatch with US DST for ~3 weeks/year (Mar/Oct–Nov) | Localise with `Europe/Athens` (or broker's stated zone) → convert to NY. Must be supported as `--tz eu` |

**Auto-detection (v0):** find weekend gaps (> 30 h); take the modal hour of the first bar after the
gap. `0` → "NY close" (`ny+7`); `21/22` → UTC; `23` → UTC+1. Otherwise default `ny+7` **with a
warning**.

**Mandatory sanity check (report Section 0):** plot median range by NY hour. For EURUSD there must be
a visible rise around 02:00–04:00 and the largest bars between 08:00 and 11:00 NY. If the peak is
shifted by whole hours, the time zone is wrong — the report must print a red warning if the
08:00–11:00 median isn't within the top 4 hours of the day. Add also a check around the DST switch
weeks: the 08:30 news spike (NFP first Friday) must land at 08:30 NY in both March and November.

## 3. The trading day

- A trading day `td` runs **17:00 NY (previous calendar day) → 17:00 NY**. Label it by the calendar
  date it *ends* on. Computation: `td = floor_day(ny + 7h)`.
- `h` = hours on the NY clock relative to midnight of `td`: 17:00 prev day = −7, 20:00 = −4,
  00:00 = 0, 09:30 = 9.5, 16:55 = 16.92. All windows in config are expressed in `h`.
- Keep Mon–Fri `td` only. A Sunday-evening open belongs to Monday's `td` automatically.
- **Holidays / half days** (Christmas, New Year, US Thanksgiving, Good Friday): flag days whose bar
  count is < 70% of the median or whose NY range is < 30% of the 20-day median as `thin_day=True`.
  Report stats both with and without thin days; default analysis excludes them.

## 4. Units

- EURUSD `pip = 0.0001`. Most brokers are 5-digit: `point = 0.00001` (a pipette). MT5 "points"
  = pipettes. **`spread` column is in points → pips = spread / 10** on 5-digit, `/1` on 4-digit.
  Read `digits` from `symbol_info` and store it in a sidecar `*.meta.json` next to the CSV.
- Internally keep prices as floats; convert to pips only for display and for cost/risk fields that
  are explicitly named `*_pips`.
- R-multiples are unitless. Never mix R and pips in one column.

## 5. Data-quality checks (run on every load, write to `reports/<run>/data_quality.json`)

| Check | Rule | Action |
|---|---|---|
| Bar interval | modal diff = 1 or 5 min | abort if > 15 min |
| OHLC integrity | low ≤ min(open, close) ≤ max(open, close) ≤ high | drop bar, count it |
| Duplicates | duplicate timestamps | keep last, count |
| Intraday gaps | > 3 missing bars inside 02:00–16:00 NY on a weekday | flag day `gappy=True` |
| Price spikes | bar range > 15 × rolling median range | flag bar; list in report for manual review |
| Coverage | first/last date, number of td, % thin/gappy days | print in report header |
| Spread | median / 95th pct spread in pips by NY hour | show in report; used by cost model |

## 6. Synthetic data for tests

`tests/fixtures/make_synth.py` produces random-walk M5 bars in NY+7 server time with an intraday
volatility profile (quiet Asia, bump London, peak 08:00–11:00) and **no edge**. Also add *planted-edge*
variants: e.g. on 60% of days where the pre-NY window raids the London high, force the 09:30→16:00
drive down. The pipeline must (a) find nothing in the clean set, (b) find the planted edge with
the right hypothesis in the planted set. That's how we know the detector works both ways.
