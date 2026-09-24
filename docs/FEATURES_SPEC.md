# FEATURES_SPEC.md — ICT concepts as code-precise definitions

ICT concepts are usually taught visually and loosely. Code needs exact rules. These are the
definitions for this project. If the user wants a different definition, change it **here first**,
bump the affected model/hypothesis versions, and note it in `research/JOURNAL.md`.

Notation: bars are the working timeframe (M5 default). `i` = bar index within a td. `ATR` = ATR(14)
of the working timeframe at bar `i−1` (known before bar `i`). Prices in price units; pips = /0.0001.
All thresholds live in `config/features.yaml` — defaults below.

## 1. Session windows

**The authoritative list is SESSIONS_AND_CONTEXT.md §1** (Asia, London, London SB, NY AM + KZ, NY AM SB,
lunch, NY PM, NY PM SB, London close, CBDR). v0 additionally used `preny` = 07:00–09:30 (available 9.5)
and `ny` = 07:00–16:00 (available 16) — keep both as extra windows for backward compatibility.

Opens: `mid_open` = open of first bar with h ≥ 0 · `o0830` · `o0930` · `o0700`. Available at their time.
Previous-day: `pdh`, `pdl`, `pdc` = previous td high/low/close (available at h = −7).
Weekly: `pwh`, `pwl` = previous week's high/low. Monday `td` has `pdh` = Friday's.

## 2. Ranges & projections

- `X_range = (X_high − X_low)/pip`.
- `adr_n` = mean of previous n `day_range` (excludes today). `adr5`, `adr20`. `adr_ratio = adr5/adr20`.
- `adr_used_at(h)` = (high − low from h = −7 up to h) / pip / adr5.
- SD projections of a range R=[lo,hi]: `hi + k·(hi−lo)` and `lo − k·(hi−lo)`, k ∈ {1, 1.5, 2, 2.5, 4}.
  Applied to `asia` and `cbdr`. Flag `ny_hits_<range>_<±k>sd`. CBDR considered "valid" if ≤ 40 pips.

## 3. Raid / sweep (the core event)

A **raid** of level `L` (above-side) in window `W` occurs at the first bar `i` in `W` with `high_i > L + tol`.
`tol` default 0.1 pip (i.e., any trade-through). Below-side mirrors with `low_i < L − tol`.

A raid is a **sweep** (liquidity grab) if within `k_back` bars (default 6 on M5 = 30 min) a bar
closes back on the original side: `close_j < L` (above-side). Record `bars_to_close_back`.
Otherwise it is a **break** (acceptance). If a bar *closes* beyond L by more than
`break_close_pips` (default 3) before closing back, classify as break even if it later returns.

Record: `level_name, level_price, t_raid, t_close_back, sweep_extreme` (max high between raid and
close-back), `penetration_pips = (sweep_extreme − L)/pip`.

Levels swept (config list): `lon_high/low, asia_high/low, pdh/pdl, pwh/pwl, cbdr_high/low,
equal_highs/lows` (see §6), `mid_open` (as a reference, not liquidity).

## 4. Swing points & structure

- **Fractal swing high** at bar j: `high_j` > highs of `n` bars each side (default n = 2 on M5; 3 on M15+).
  **It is only known at bar j + n** — the event's `available_at` is j + n. (Classic look-ahead trap.)
- Label each new swing high HH/LH vs the previous swing high; swing low HL/LL vs previous swing low.
- `structure_score(k)` = (HH + HL − LH − LL) / k over the last k confirmed swings (Formula Handbook 6.5).
- **Internal vs external:** external = swings on M15 (n = 2) or the session window extremes;
  internal = M5 swings inside the current external leg. Start with M5 only; add M15 in Phase 7.

## 5. Displacement

Bar i is a **displacement candle** if: `body_i ≥ k_disp · ATR` (default k_disp = 1.3) **and**
`body_i / (high_i − low_i) ≥ 0.6`. A **displacement leg** = ≥ 1 displacement candle, optionally
flanked by same-direction bars, that creates at least one FVG (§7). Record direction and size in ATR.

## 6. Equal highs / lows

Two confirmed swing highs within the last `lookback` bars (default 48 on M5 = 4 h) whose prices
differ by ≤ `eq_tol` (default max(1.0 pip, 0.1·ATR)) → `equal_highs` level at the higher of the two.
Available when the second swing is confirmed.

## 7. Fair Value Gap (FVG)

Three consecutive bars 1,2,3 (3 is the latest):
- **Bullish FVG (BISI):** `low_3 > high_1`. Gap = [high_1, low_3]. Available at close of bar 3.
- **Bearish FVG (SIBI):** `high_3 < low_1`. Gap = [high_3, low_1].
- Minimum size: `gap ≥ max(fvg_min_pips (0.8), fvg_min_atr (0.15)·ATR)`.
- `ce = (top + bottom)/2`. Track afterwards: `first_touch_t` (price re-enters gap), `ce_touch_t`,
  `full_fill_t` (price trades through the far side), `invalidated` (close beyond far side → becomes an
  **inversion FVG** candidate).
- An FVG "belongs" to a displacement leg if bar 2 is a displacement candle.

## 8. Market Structure Shift (MSS)

After a **sweep** of an above-side level (bearish context): the MSS occurs at the first bar that
**closes** below the most recent confirmed swing low that formed *before* the sweep extreme, **and**
the move from sweep extreme to that close contains a displacement candle. Mirror for bullish.
Record `mss_t`, `mss_level`, `bars_from_sweep`, `leg_fvgs` (FVGs created between sweep extreme and MSS).
Max bars from sweep to MSS: `mss_max_bars` (default 24 on M5 = 2 h).

## 9. Order block (define but low priority)

Bearish OB: the last **up-close** bar before the displacement leg that caused an MSS down.
Zone = [low, high] of that bar (body-only variant: [open, close]). Mean threshold = 50% of zone.
Bullish mirrors. Only computed for legs that produced an MSS.

## 10. Premium / discount

Dealing range for NY = [`nyrange_low`, `nyrange_high`] where by default this is the range from 00:00
to the decision bar (configurable: previous-day range, or last external swing pair).
`pd_pos = (price − low)/(high − low)`; premium > 0.5, discount < 0.5; OTE = 0.62–0.79 retracement
of the leg into the entry.

## 11. Regime features (Formula Handbook Part 6)

Daily, available at h = −7 (use previous completed days only): `adr_ratio`, `er10` (codex variant:
|net 10-day move| / Σ 10 daily ranges), `adx14_d1`, `chop14_d1`, `realized_vol_pct` (percentile of
20-day realized vol over 126 days). Bucket each into terciles for slicing results.

## 12. Economic calendar

Now a core feature — full spec in SESSIONS_AND_CONTEXT §4 (free export from MT5 via an MQL5 script,
surprise z-scores, per-session news features, release-time availability). Models must support
`skip_if: day.has_fomc` style rules. Do not scrape websites without the user's approval.
