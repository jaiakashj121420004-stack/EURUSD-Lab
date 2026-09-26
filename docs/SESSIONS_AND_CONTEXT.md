# SESSIONS_AND_CONTEXT.md — every session, its "character", news, and how sessions condition each other

The user's core research question is **relational**: *given what Asia and London did (and what news hit),
what tends to happen next?* This file defines the sessions, how we label each session's behaviour
objectively, how news is attached, and how the cross-session analysis must be run without drowning in
false positives.

---

## 1. Session windows (NY clock; all configurable in `config/windows.yaml`)

`h` = NY hours relative to the trading day's midnight (DATA_AND_TIME §3). Trading day = 17:00→17:00 NY.

| id | Name | NY time | h range | Ends (available at h) | Notes |
|---|---|---|---|---|---|
| `cbdr` | Central Bank Dealers Range | 14:00–20:00 (prev) | −3 … +3* | −4 | *spans td boundary; compute from absolute timestamps |
| `asia` | Asian session | 20:00–00:00 | −4 … 0 | 0 | Asian range high/low = liquidity for London |
| `lon` | London killzone | 02:00–05:00 | 2 … 5 | 5 | |
| `lon_sb` | London Silver Bullet | 03:00–04:00 | 3 … 4 | 4 | inside `lon` |
| `lon_full` | London session (context) | 02:00–07:00 | 2 … 7 | 7 | optional, for "London overall" stats |
| `lon_ny_gap` | London→NY gap | 05:00–07:00 | 5 … 7 | 7 | added 2026-09-25 at Akash's request; untracked stretch between `lon`'s close and `nyam_kz`'s start |
| `nyam` | NY AM session | 07:00–12:00 | 7 … 12 | 12 | |
| `nyam_kz` | NY AM killzone | 07:00–10:00 | 7 … 10 | 10 | |
| `nyam_sb` | NY AM Silver Bullet (widened) | 10:00–12:00 | 10 … 12 | 12 | widened 2026-09-26 to close the 11-12 gap left by dropping `nyam` from the review page; no longer the strict 1hr ICT Silver Bullet window |
| `lunch` | NY lunch | 12:00–13:30 | 12 … 13.5 | 13.5 | usually no-trade; still measured |
| `nypm` | NY PM session | 13:30–16:00 | 13.5 … 16 | 16 | |
| `nypm_sb` | NY PM Silver Bullet | 14:00–15:00 | 14 … 15 | 15 | FOMC days: 14:00 release inside it |
| `lon_close` | London close KZ | 10:00–12:00 | 10 … 12 | 12 | overlaps nyam; context only |

Reference opens: `o_mid` 00:00, `o_0700`, `o_0830`, `o_0930`, `o_1330`. Previous-day `pdh/pdl/pdc`,
previous week `pwh/pwl`, current week-to-date high/low (available at each bar).

**Session ordering for "earlier → later" analysis:** `cbdr → asia → lon → nyam → lunch → nypm`
(Silver Bullets are sub-windows analysed as *outcome* windows, not as separate chain links).
`lon_ny_gap` is NOT inserted into this chain -- its raid features look back at `lon` (same
predecessor `nyam`/`nyam_kz`/`nyam_sb`/`lon_close` already use), so adding it doesn't change what
"immediately preceding session" means for any already-frozen column.

---

## 2. The SESSION table (new — one row per session per trading day)

Built in `nylab/sessions.py`. Primary key `(td, session_id)`. All columns available at the session's end.

| Column | Definition |
|---|---|
| `open, high, low, close` | first open, max high, min low, last close in window |
| `hi_t, lo_t` | NY hour of the high / low |
| `range_pips` | (high − low)/pip |
| `range_rel` | range_pips ÷ median range_pips of the **same session** over the previous 20 td |
| `net_pips` | (close − open)/pip, signed |
| `dir` | sign(net) with a dead-band: \|net\| < 0.15 × range → 0 (flat) |
| `er` | efficiency ratio within session on M5 closes: \|close − open\| ÷ Σ\|Δclose\| (0 = chop, 1 = straight line) |
| `close_loc` | (close − low)/(high − low): 1 = closed at high, 0 = at low |
| `swing_count` | number of confirmed M5 fractal swings (n = 2) inside the session |
| `disp_count` | displacement candles (FEATURES_SPEC §5) |
| `fvg_count_bull/bear` | FVGs created (FEATURES_SPEC §7) |
| `raids` | list of prior levels traded through: prior sessions' highs/lows (same td), pdh/pdl, pwh/pwl, o_mid |
| `first_raid` | which level was raided first + time; `raid_type` sweep / break (FEATURES_SPEC §3) |
| `took_prev_high / took_prev_low` | traded beyond the **immediately preceding session's** high / low |
| `both_sides` | took both prev high and prev low |
| `news_high_usd / news_high_eur` | count of high-impact events whose release time is inside the window (§4) |
| `news_surprise_z` | largest \|surprise z\| among those events (sign kept) |
| `character` | categorical label (§3) |

---

## 3. Session character — objective labels

Discretionary words ("London was choppy") must become rules. Default thresholds below; the user must
validate them by eye on 30 random days in the replay trainer (ROADMAP ticket 6.4) before any research
uses them. Evaluate in this order; first match wins:

| Label | Rule (defaults) | Plain English |
|---|---|---|
| `quiet` | `range_rel < 0.6` | Much smaller than normal for this session |
| `reversal` | took one side of the previous session's range (sweep **or** break), then `close_loc` on the **opposite** side: took prev high & `close_loc ≤ 0.35`, or took prev low & `close_loc ≥ 0.65` | Raided one side, then went the other way (Judas-style) |
| `trend` | `er ≥ 0.45` and (`close_loc ≥ 0.75` or `≤ 0.25`) | Moved one way and closed near the extreme |
| `range_both` | `both_sides` and `0.35 < close_loc < 0.65` | Took out both sides, closed in the middle |
| `chop` | `er < 0.25` | Lots of movement, little progress |
| `normal` | none of the above | Unremarkable |

Also compute a **continuous** score set (range_rel, er, close_loc, net relative to ADR) — research can use
terciles of these instead of labels. Labels are for humans and the replay filter; continuous scores are
preferred for statistics (fewer arbitrary cut-offs).

**Day type** (whole td, available at 17:00): `trend_day`, `reversal_day`, `range_day`, `inside_day`
(inside previous day's range), `outside_day` (took both pdh and pdl) — same logic on the full day vs the
previous day.

---

## 4. News — getting it for free from MT5 and attaching it to sessions

The `MetaTrader5` **Python** package does **not** expose the economic calendar. MT5's **MQL5** language
does (`CalendarValueHistory`, `CalendarEventById`, `CalendarCountryById`). So:

**Build `mql5/ExportCalendar.mq5`** (a *Script*, read-only), which the user compiles in MetaEditor (F7)
and runs once on any chart:
- Inputs: `DateFrom` (default 5 years ago), `DateTo` (now), `Currencies` = "USD,EUR", `MinImportance` = LOW.
- Loop `CalendarValueHistory(values, from, to, NULL, currency)` per currency (chunk by year if large).
- For each value: `CalendarEventById(value.event_id, ev)`; `CalendarCountryById(ev.country_id, c)`.
- Write CSV to `MQL5/Files/calendar_export.csv` (FILE_COMMON not needed) with columns:
  `time_server, currency, event_id, event_name, importance (0-3), actual, forecast, previous, revised_previous, unit, multiplier`.
  Values are stored ×10⁶ as `long`; `LONG_MIN` means "not set" → write empty. Divide by 1e6.
- Print the output path. `nylab calendar-import` then converts `time_server` → NY with the **same**
  timezone mode as the bars (DATA_AND_TIME §2) and saves `data/calendar.parquet`.
- Note: calendar functions do not work inside the Strategy Tester; run the script on a live chart.
  History depth depends on MetaQuotes' calendar database — report the earliest event date found.

**Fallback:** if the script can't be run, accept a user-supplied CSV with columns
`datetime_ny, currency, event, impact, actual, forecast, previous`.

**Derived features:**
- `surprise = actual − forecast`; `surprise_z` = surprise ÷ stdev of the same event's past surprises
  (≥ 8 prior releases, else NaN). Positive z = stronger-than-expected data *for that currency*.
- Event families (regex on name): `NFP`, `CPI`, `FOMC` (rate decision / statement / press conference),
  `ECB` (rate decision / press conference), `PMI`, `GDP`, `retail_sales`, `claims`, `speech` (Fed/ECB speakers).
- Per SESSION row: counts and max \|z\| of high-impact USD and EUR events **inside** the window; per DAY:
  flags `has_nfp`, `has_cpi`, `has_fomc`, `has_ecb`, `red_usd_0830`, `red_eur_london`.
- **Look-ahead rule:** `actual`/`surprise` are available only from the release minute. Pre-release,
  only "event scheduled" and `forecast` may be used (e.g. "red USD event scheduled at 08:30 today" is
  known at 00:00; its surprise is known at 08:30).

---

## 5. Cross-session analysis — the relational layer

Two levels. Keep them separate in code and in the report.

### 5.1 Descriptive transition matrices (context, not signals)

For each ordered pair of sessions (A earlier, B later) in the chain, build:
- `P(B.character | A.character)` — rows = A label, columns = B label, cells show count, conditional %,
  and the **unconditional** % of that B label for comparison, plus Wilson 95% CI.
- `P(B.dir | A.dir)` and `P(B takes A.high / A.low)` (e.g. "NY AM takes the London high").
- Conditioning on news: rows = A had high-impact news (none / USD / EUR / both), and by surprise sign.
- Default pairs: asia→lon, lon→nyam, nyam→nypm, lon→nypm, (asia+lon combined label)→nyam.
- Show cells with n < 25 greyed out ("too few days").
- Label the section **DESCRIPTIVE — not tested for significance**.

Example rows the user asked for:
- "London `chop` → NY AM character distribution vs normal".
- "London had red EUR news with \|z\| > 1 → NY AM `reversal` rate".
- "NY AM `trend` → NY PM continues (same dir) vs reverses".
- "Asia `quiet` + London `trend` → NY AM takes London's extreme in the same direction?"

### 5.2 Relational hypotheses (tested, counted)

Only a matrix cell that the user or you **promote** becomes a hypothesis YAML, e.g.:
```yaml
id: H031
title: "London chop → NY AM KZ reversal of the London range"
decision_time_h: 7.0
condition: "lon.character == 'chop'"
outcome: "nyam.character == 'reversal'"
baseline: "nyam.character == 'reversal'"
family: cross_session_lon_nyam
```
The DSL gains dotted session access `lon.er`, `nyam.took_prev_high`, `lon.news_high_eur`, `day.has_fomc`.

**Multiple-testing rule specific to matrices:** looking at a matrix is free (descriptive), but once you
pick a cell *because it looked extreme*, you must count **every cell of that matrix** as tested
(`m += rows × cols`) — you implicitly compared them all. Record the matrix as a "family" in the ledger and
apply Benjamini-Hochberg within the family plus the global Bonferroni. Then require OOS confirmation.
This is what stops "London chop → NY PM Tuesday reversal" style flukes.

### 5.3 Session context as a FILTER for models

The most productive use is usually not "London chop predicts NY direction" but "the NY AM sweep
model works better **after** a London reversal". Models accept `context_filter:` (DSL) in YAML;
results are always reported for filtered vs unfiltered vs complement, with the filter counted as one
extra test per filter tried.

---

## 6. Report sections (added to report.html)

1. Session overview table: median range, ER, character distribution per session, by year.
2. Heat-map of median range by NY hour × weekday (sanity + context).
3. Transition matrices (5.1) with greying and the "descriptive" banner.
4. News impact: median session range and character mix on days with/without each event family, by
   surprise tercile; time-to-high/low after 08:30 and 14:00 releases.
5. Silver Bullet windows: for each SB, how often an FVG forms inside it, how often price reaches the
   nearest opposite liquidity within the window, median range — context for the SB models.
6. Relational hypotheses table (5.2) with family-level corrections.
