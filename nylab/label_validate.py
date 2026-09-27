"""nylab.label_validate -- ROADMAP 5.6: label validation with Akash. Samples trading days,
packages each one's bars + the computed `character` label (for a fixed set of sessions) and
`day_type` into a single self-contained HTML page he can open and click through offline (no
server, no internet -- consistent with REPLAY_TRAINER.md's "no build step" philosophy), and
scores his agree/disagree answers once he exports them.

Scope cut (disclosed here and in docs/PROGRESS.md): validates `character` for five sessions --
asia, lon, nyam_kz, nyam_full (the new broader NY AM session, S1's `nyam` id), nypm -- rather
than all 11 SESSION_IDS. These five were picked because they're the ones existing hypotheses/
the example model actually condition on, and PROGRESS.md's Phase 5.3 write-up specifically
flagged nyam_full's `trend` label (2/~1300 days) and asia's (9 days) as worth Akash's own eye.
`day_type` is included too since S6/S2 gives it the same "same rules, own catch-all" scrutiny.

Two sampling strategies (both stratified-floor-first, ROADMAP 5.6's "never let a rare label
silently drop out" concern -- see `_stratified_floor` below):

- `sample_days()` (round 1 and 2, "random" strategy): floor + uniform-random fill. Kept
  unchanged (existing tests depend on its exact behaviour).
- `sample_days_curated()` (round 3 onward, the default, "curated" strategy): floor +
  near-threshold fill. Akash found random days "tiring and time consuming" because most of
  them are obviously-correct, far from any rule boundary -- they don't actually test the
  rules. The curated fill instead ranks every remaining candidate day by how CLOSE its real
  feature values come to any of the frozen numeric thresholds in `sessions.py`'s
  `_label_character` / `_day_type` rule cascades, and takes the closest ones first -- the
  genuinely ambiguous, informative edge cases where a human eyeball actually adds
  information. See `_character_boundary_distance` / `_day_type_boundary_distance` for exactly
  what "distance to boundary" means here.

Disclosed in the generated HTML itself, not hidden.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

# v2 (confirmed with Akash 2026-09-25): dropped the broad "nyam" (7-12) session in favor of
# nyam_kz (7-10, the NY AM killzone) plus nyam_sb (10-11, Silver Bullet) on their own -- the
# two overlapping NY-morning windows were confusing him more than they were adding signal.
# v3 (same day): added lon_ny_gap (5-7, the untracked London-close -> NY-AM-killzone-start
# stretch) at his request, so he can review its character calls too.
SESSIONS_TO_VALIDATE = ["asia", "lon", "lon_ny_gap", "nyam_kz", "nyam_sb", "nypm"]
_PREFIX = {"asia": "asia", "lon": "lon", "lon_ny_gap": "lon_ny_gap", "nyam_kz": "nyam_kz",
           "nyam_sb": "nyam_sb", "nypm": "nypm"}
MIN_PER_LABEL = 1
BAR_LO, BAR_HI = -7.0, 17.0  # full trading day span (asia start .. nypm/cbdr-adjacent end)

# Frozen thresholds mirrored from nylab/sessions.py -- `_label_character` (session-level) and
# `_day_type` (day-level). These are copied, not imported, because label_validate.py works
# purely off the cached `days` table's already-computed columns (range_rel/er/close_loc/
# took_prev_high/took_prev_low/both_sides for sessions; day_high/day_low/day_close/pdh/pdl for
# days) and must not reach into sessions.py's private helpers. RESEARCH_PROTOCOL.md and
# CLAUDE.md rule that session-character thresholds are FROZEN once validated (ROADMAP 5.6) --
# if sessions.py's numbers ever change, these must be updated to match in the same commit, or
# the "distance to boundary" ranking below silently drifts out of sync with the real rule.
_QUIET_RANGE_REL = 0.6
_CHOP_ER = 0.25
_TREND_ER = 0.45
_TREND_ER_CLOSE_LOC = (0.25, 0.75)
_TREND_RANGE_REL = 1.4
_TREND_RANGE_CLOSE_LOC = (0.20, 0.80)
_MID_CLOSE_LOC = (0.35, 0.65)  # reversal's / range_both's / range_day's / reversal_day's split
_DAY_TREND_CLOSE_LOC = (0.25, 0.75)  # trend_day's close_loc split (same numbers, own rule)


def _stratified_floor(days: pd.DataFrame, seed: int,
                       min_per_label: int = MIN_PER_LABEL) -> tuple[set, random.Random]:
    """The floor step shared by both sampling strategies: >=min_per_label days per occurring
    `{prefix}_character` label, per validated session, chosen from a seed-shuffled pool of that
    label's own days (so which of several tied candidates gets picked is reproducible from
    `seed`, not insertion-order-dependent). Returns the chosen set AND the still-in-use
    `random.Random` so a caller's later random consumption (uniform-random fill, or nothing at
    all for the curated path) continues deterministically from exactly where the floor left
    off -- this is what keeps `sample_days()`'s output byte-identical to before this refactor."""
    rng = random.Random(seed)
    chosen: set = set()
    for sid in SESSIONS_TO_VALIDATE:
        col = f"{_PREFIX[sid]}_character"
        if col not in days.columns:
            continue
        for label, sub in days.groupby(col):
            if pd.isna(label):
                continue
            pool = list(sub.index)
            rng.shuffle(pool)
            chosen.update(pool[:min_per_label])
    return chosen, rng


def sample_days(days: pd.DataFrame, n: int = 30, seed: int = 42) -> list[pd.Timestamp]:
    """Stratified-then-random. The stratified floor (>=MIN_PER_LABEL days per occurring label,
    per validated session) is NEVER trimmed back down, even if it alone exceeds `n` -- trimming
    it would silently re-introduce the exact "rare label never gets checked" problem this
    function exists to avoid. So the result is `max(n, len(stratified floor))` days: usually
    exactly `n`, occasionally a few more when a session has many distinct labels each needing
    their own floor. This is disclosed in the generated HTML's own header text."""
    chosen, rng = _stratified_floor(days, seed)
    remaining_pool = [td for td in days.index if td not in chosen]
    rng.shuffle(remaining_pool)
    while len(chosen) < n and remaining_pool:
        chosen.add(remaining_pool.pop())
    return sorted(chosen)


def _character_boundary_distance(row: pd.Series, prefix: str) -> float:
    """How close this ONE session-row's real feature values come to flipping across ANY of the
    numeric thresholds in `_label_character`'s frozen rule cascade (sessions.py). Rather than
    modelling the exact AND/OR structure of each branch (which would need the underlying price
    series to reconstruct properly, and this module only ever sees the cached `days` table's
    aggregated columns -- CLAUDE.md forbids touching sessions.py to get more), we treat every
    individual scalar threshold as its own candidate decision line and score the row by its
    minimum absolute distance to any one of them. A day sitting right on top of ANY of these
    lines is a day where the rule's verdict could easily have gone the other way -- exactly the
    case Akash's own eyeball is most useful for; a day far from all of them is the "obviously
    normal" / "obviously trend" case a random sample wastes his time on.

    Normalization: range_rel, er and close_loc are all already unit-free ratios living in
    roughly the same O(1) neighbourhood (close_loc in [0,1] by construction; range_rel and er
    cluster tightly around 1 and 0-1 respectively in the real 5-year sample), so raw absolute
    distance is used directly rather than an IQR-scaled one -- scaling by each feature's own
    IQR was considered, but on inspection of the real cached data the three features' IQRs are
    all within roughly a factor of 2 of each other, so a raw-distance minimum doesn't let one
    feature dominate in practice, and it's far easier for a future reader to verify by eye
    ("threshold is 0.6, value is 0.58, distance is 0.02") than a rescaled one would be.
    """
    range_rel = row.get(f"{prefix}_range_rel")
    er = row.get(f"{prefix}_er")
    close_loc = row.get(f"{prefix}_close_loc")
    if pd.isna(range_rel) or pd.isna(er) or pd.isna(close_loc):
        return float("nan")
    margins = [
        abs(range_rel - _QUIET_RANGE_REL),                      # quiet's own line
        abs(er - _CHOP_ER),                                      # chop's own line
        abs(er - _TREND_ER),                                     # trend_er's er line
        min(abs(close_loc - _TREND_ER_CLOSE_LOC[0]),
            abs(close_loc - _TREND_ER_CLOSE_LOC[1])),            # trend_er's close_loc line
        abs(range_rel - _TREND_RANGE_REL),                       # trend_range's range_rel line
        min(abs(close_loc - _TREND_RANGE_CLOSE_LOC[0]),
            abs(close_loc - _TREND_RANGE_CLOSE_LOC[1])),         # trend_range's close_loc line
        min(abs(close_loc - _MID_CLOSE_LOC[0]),
            abs(close_loc - _MID_CLOSE_LOC[1])),                 # reversal / range_both split
    ]
    return min(margins)


def _day_type_boundary_distance(row: pd.Series) -> float:
    """Same idea as `_character_boundary_distance`, for `_day_type` (sessions.py). Unlike the
    session-level rule, the cached `days` table DOES carry the raw price levels this rule
    compares (day_high/day_low/pdh/pdl), so the took-prev-high/took-prev-low booleans get a
    real continuous distance here (normalized by the day's own range, so it reads as "how many
    day-ranges away from the pdh/pdl line was today's high/low" -- a day whose high missed
    yesterday's high by 0.01 of today's range is a near-miss; by 2x today's range, it's not)
    instead of the boolean-gated treatment `_character_boundary_distance` has to fall back on
    for the session-level rule's took_high/took_low flags."""
    day_high, day_low = row.get("day_high"), row.get("day_low")
    day_close = row.get("day_close")
    pdh, pdl = row.get("pdh"), row.get("pdl")
    if any(pd.isna(v) for v in (day_high, day_low, day_close, pdh, pdl)):
        return float("nan")
    day_range = day_high - day_low
    if pd.isna(day_range) or day_range <= 0:
        return float("nan")
    close_loc = (day_close - day_low) / day_range
    margins = [
        abs(day_high - pdh) / day_range,                         # took_prev_high's own line
        abs(day_low - pdl) / day_range,                          # took_prev_low's own line
        min(abs(close_loc - _DAY_TREND_CLOSE_LOC[0]),
            abs(close_loc - _DAY_TREND_CLOSE_LOC[1])),           # trend_day's close_loc line
        min(abs(close_loc - _MID_CLOSE_LOC[0]),
            abs(close_loc - _MID_CLOSE_LOC[1])),                 # reversal_day / range_day split
    ]
    return min(margins)


def _day_ambiguity_score(row: pd.Series) -> float:
    """A day's overall "how informative would Akash's eyeball be here" score: the smallest
    boundary distance across every validated session's character rule AND day_type -- i.e. a
    day earns a place in the curated sample if ANY ONE of its labels is a near-call, not only
    if all of them are."""
    scores = [_character_boundary_distance(row, _PREFIX[sid]) for sid in SESSIONS_TO_VALIDATE]
    scores.append(_day_type_boundary_distance(row))
    scores = [s for s in scores if not (s is None or (isinstance(s, float) and np.isnan(s)))]
    return min(scores) if scores else float("nan")


def sample_days_curated(days: pd.DataFrame, n: int = 20, seed: int = 43,
                         min_per_label: int = MIN_PER_LABEL) -> list[pd.Timestamp]:
    """Stratified-floor-then-near-threshold. Same floor guarantee as `sample_days()` (a rare
    label is its own boundary case -- it doesn't need to be "near a threshold" in the usual
    sense to earn a place, since it barely has any other members to compare against at all --
    so the floor step is reused verbatim, not replaced). The FILL beyond the floor is where
    this differs from `sample_days()`: instead of uniform-random days, remaining candidates are
    ranked by `_day_ambiguity_score` (smallest distance to any rule boundary = picked first) and
    the most boundary-adjacent ones are added until `n` is reached. Selection runs over the
    FULL cached day table every time (never restricted to a previous review round or to days
    Akash has already flagged -- that would be a form of look-ahead into which round produced
    disagreements, RESEARCH_PROTOCOL.md's spirit if not its letter).

    Ties (multiple days at the same distance, common with rounded cached values) are broken by
    a seed-shuffle before the stable sort, so the result is reproducible for a given `seed` but
    not an artifact of `days.index` insertion order. Like `sample_days()`, the floor is never
    trimmed back down, so the result can be a few days more than `n`.
    """
    chosen, rng = _stratified_floor(days, seed, min_per_label=min_per_label)
    if len(chosen) >= n:
        return sorted(chosen)
    remaining = [td for td in days.index if td not in chosen]
    scored = []
    for td in remaining:
        score = _day_ambiguity_score(days.loc[td])
        if not (score is None or (isinstance(score, float) and np.isnan(score))):
            scored.append((score, td))
    rng.shuffle(scored)          # seeded tie-break
    scored.sort(key=lambda t: t[0])  # stable: shuffle order survives within a tie
    for _, td in scored:
        if len(chosen) >= n:
            break
        chosen.add(td)
    return sorted(chosen)


def build_payload(bars: pd.DataFrame, days: pd.DataFrame, sessions_cfg: dict,
                   tds: list[pd.Timestamp]) -> dict:
    days_out = []
    bars_by_td = {td: g for td, g in bars.groupby("td")}
    for td in tds:
        row = days.loc[td]
        bslice = bars_by_td.get(td)
        bar_rows = []
        if bslice is not None:
            sub = bslice[(bslice["h"] >= BAR_LO) & (bslice["h"] < BAR_HI)]
            bar_rows = [[round(float(r.h), 4), round(float(r.open), 5), round(float(r.high), 5),
                         round(float(r.low), 5), round(float(r.close), 5)] for r in sub.itertuples()]
        sessions_out = []
        for sid in SESSIONS_TO_VALIDATE:
            prefix = _PREFIX[sid]
            col = f"{prefix}_character"
            if col not in days.columns:
                continue
            label = row.get(col)
            label = None if pd.isna(label) else str(label)
            lo, hi = sessions_cfg[sid]

            def _num(colname, ndp=3):
                v = row.get(f"{prefix}_{colname}")
                return None if v is None or pd.isna(v) else round(float(v), ndp)

            sessions_out.append(dict(
                id=sid, prefix=prefix, lo=lo, hi=hi, label=label,
                range_rel=_num("range_rel"), er=_num("er"), close_loc=_num("close_loc"),
            ))
        day_type = row.get("day_type")

        def _dnum(colname, ndp=5):
            v = row.get(colname)
            return None if v is None or pd.isna(v) else round(float(v), ndp)

        day_high, day_low, day_close = row.get("day_high"), row.get("day_low"), row.get("day_close")
        day_close_loc = None
        if not any(pd.isna(v) for v in (day_high, day_low, day_close)) and (day_high - day_low) > 0:
            day_close_loc = round(float((day_close - day_low) / (day_high - day_low)), 3)

        days_out.append(dict(
            td=td.strftime("%Y-%m-%d"), bars=bar_rows, sessions=sessions_out,
            day_type=(None if pd.isna(day_type) else str(day_type)),
            day_close_loc=day_close_loc,
            day_high=_dnum("day_high"), day_low=_dnum("day_low"),
            pdh=_dnum("pdh"), pdl=_dnum("pdl"),
        ))
    return dict(days=days_out, generated_for="EURUSD Session Research Lab -- ROADMAP 5.6")


_HTML_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Label validation -- ROADMAP 5.6</title>
<style>
/* Porcelain (light, default) / Espresso (dark) -- design/preview.html is the approved source
   of truth for these token values; docs/DESIGN_SYSTEM.md documents the system in prose. */
:root{
  --font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Manrope, sans-serif;
  --font-mono: "SF Mono", "Cascadia Code", ui-monospace, "Roboto Mono", monospace;
  --ease-glide: cubic-bezier(0.22, 1, 0.36, 1);
  --t-fast: 140ms; --t-med: 320ms;
  --radius-card: 18px; --radius-pill: 999px;
  --base: #F0EDE8; --shadow-dark: rgba(163,150,133,.45); --shadow-light: #FFFFFF;
  --text-1: #2B2822; --text-2: #6B6459; --text-3: #968F82;
  --accent: #0EA5A0; --accent-rgb: 14,165,160;
  --amber: #E39B2F; --amber-rgb: 227,155,47;
  --bull: #0F9D76; --bear: #E5484D;
  --glass-border-dim: rgba(163,150,133,.18);
  --focus-ring: rgba(14,165,160,.55);
}
:root[data-theme="dark"]{
  --base: #1E1B18; --shadow-dark: #12100E; --shadow-light: rgba(255,255,255,.045);
  --text-1: #EFE9E1; --text-2: #A79E92; --text-3: #746B60;
  --accent: #2DD4BF; --accent-rgb: 45,212,191;
  --amber: #F5B04C; --amber-rgb: 245,176,76;
  --bull: #22C39A; --bear: #FF6369;
  --glass-border-dim: rgba(0,0,0,.4);
  --focus-ring: rgba(45,212,191,.6);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]):not([data-theme="dark"]){
    --base: #1E1B18; --shadow-dark: #12100E; --shadow-light: rgba(255,255,255,.045);
    --text-1: #EFE9E1; --text-2: #A79E92; --text-3: #746B60;
    --accent: #2DD4BF; --accent-rgb: 45,212,191;
    --amber: #F5B04C; --amber-rgb: 245,176,76;
    --bull: #22C39A; --bear: #FF6369;
    --glass-border-dim: rgba(0,0,0,.4);
    --focus-ring: rgba(45,212,191,.6);
  }
}
*{box-sizing:border-box}
body{font-family:var(--font-ui);background:var(--base);color:var(--text-1);margin:0;padding:0 0 70px;
  transition:background var(--t-med) var(--ease-glide),color var(--t-med) var(--ease-glide)}
.tabular{font-variant-numeric:tabular-nums;font-family:var(--font-mono)}
button,input{font-family:inherit;color:inherit}
:focus-visible{outline:2px solid var(--focus-ring);outline-offset:3px;border-radius:8px}
.elev-raised{background:var(--base);box-shadow:8px 8px 18px var(--shadow-dark),-8px -8px 18px var(--shadow-light);
  transition:box-shadow var(--t-fast) var(--ease-glide)}
.elev-raised-soft{background:var(--base);box-shadow:4px 4px 10px var(--shadow-dark),-4px -4px 10px var(--shadow-light);
  transition:box-shadow var(--t-fast) var(--ease-glide)}
.elev-inset{background:var(--base);box-shadow:inset 5px 5px 12px var(--shadow-dark),inset -5px -5px 12px var(--shadow-light)}
.press:active{box-shadow:inset 4px 4px 10px var(--shadow-dark),inset -4px -4px 10px var(--shadow-light)!important;
  transform:scale(0.98);transition:box-shadow 80ms linear,transform 80ms linear}
header{background:var(--base);padding:14px 20px;border-bottom:1px solid var(--glass-border-dim);
  position:sticky;top:0;z-index:5;display:flex;align-items:flex-start;gap:14px}
header .htext{flex:1;min-width:0}
h1{font-size:18px;margin:0;color:var(--text-1)}
.muted{color:var(--text-2);font-size:13px}
#themeBtn{width:36px;height:36px;min-width:36px;border-radius:50%;border:none;background:none;
  color:var(--text-2);display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0}
#themeBtn:hover{color:var(--accent)}
#themeBtn svg{width:18px;height:18px;stroke:currentColor;stroke-width:1.7;fill:none;stroke-linecap:round;stroke-linejoin:round}
.day{margin:18px auto;max-width:1060px;border-radius:var(--radius-card);padding:16px 20px}
.day h2{margin:0 0 8px;font-size:15px;color:var(--text-1)}
canvas{width:100%;background:var(--base);border-radius:12px;display:block}
.zoombar{margin:8px 0 10px;display:flex;flex-wrap:wrap;gap:6px}
.zoombtn{border:none;background:var(--base);color:var(--text-2);border-radius:var(--radius-pill);
  padding:6px 12px;cursor:pointer;font-size:12px;box-shadow:4px 4px 10px var(--shadow-dark),-4px -4px 10px var(--shadow-light)}
.zoombtn.active{color:var(--accent);font-weight:700;box-shadow:inset 3px 3px 7px var(--shadow-dark),inset -3px -3px 7px var(--shadow-light)}
table{border-collapse:collapse;width:100%;margin-top:10px;font-size:13px}
th,td{padding:6px 8px;text-align:left;border-bottom:1px solid var(--glass-border-dim)}
th{color:var(--text-3);font-weight:600}
.featvals{display:block;color:var(--text-3);font-size:11px;margin-top:2px}
button.ans{border:none;background:var(--base);color:var(--text-2);border-radius:var(--radius-pill);
  padding:5px 14px;cursor:pointer;margin-right:6px;font-size:12px;
  box-shadow:4px 4px 10px var(--shadow-dark),-4px -4px 10px var(--shadow-light)}
button.ans.sel-agree{color:var(--bull);font-weight:700;box-shadow:inset 3px 3px 7px var(--shadow-dark),inset -3px -3px 7px var(--shadow-light)}
button.ans.sel-disagree{color:var(--bear);font-weight:700;box-shadow:inset 3px 3px 7px var(--shadow-dark),inset -3px -3px 7px var(--shadow-light)}
#bar{position:sticky;bottom:0;background:var(--base);padding:14px 20px;border-top:1px solid var(--glass-border-dim);
  text-align:center;box-shadow:0 -6px 18px var(--shadow-dark)}
#bar button{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-pill);
  padding:10px 24px;font-size:14px;cursor:pointer;font-weight:600}
#progress{margin-bottom:8px;font-size:13px;color:var(--text-2)}
input.note{width:96%;background:var(--base);border:none;color:var(--text-1);border-radius:8px;
  padding:6px 8px;font-size:12px;margin-top:4px;box-shadow:inset 3px 3px 7px var(--shadow-dark),inset -3px -3px 7px var(--shadow-light)}
details{max-width:1060px;margin:14px auto;border-radius:var(--radius-card);padding:12px 20px}
summary{cursor:pointer;color:var(--accent);font-size:14px;font-weight:700}
details table{margin-top:10px}
.lbl{text-decoration:underline dotted var(--text-3);cursor:help}
.footer-note{max-width:1060px;margin:18px auto 0;color:var(--text-3);font-size:11.5px;text-align:center}
@media (max-width:640px){
  .day, details, .footer-note{max-width:100%;border-radius:0;margin-left:0;margin-right:0}
  header{padding:12px 16px} h1{font-size:16px}
}
</style></head><body class="elev-flat">
<header><div class="htext"><h1>Session-character &amp; day-type label validation</h1>
<div class="muted">ROADMAP 5.6 -- for each label below: does it look right on the chart? Use the zoom buttons to
look closely at one session at a time, click Agree or Disagree for every row, then use "Download my answers"
at the bottom and send that file back. %%COUNT%% days, curated near a rule boundary so each one is an
informative call, not an obvious one. Hover any bold label for a plain-English definition, or open
"What do these labels mean?" below for the full list. Dashed lines on the full-day chart mark yesterday's
high (PDH) and low (PDL) for day_type calls.</div></div>
<button id="themeBtn" aria-label="Toggle theme"><svg id="themeIcon" viewBox="0 0 24 24"></svg></button>
</header>

<details class="elev-raised">
<summary>What do these labels mean? (click to expand)</summary>
<p class="muted">These are the SAME rules for every session (asia/london/etc.) -- "character" describes how that
one session's price action behaved. Priority when a session could match more than one rule: quiet beats
reversal beats trend beats range_both beats chop beats normal (the catch-all).</p>
<table>
<tr><th>Label</th><th>Meaning</th></tr>
<tr><td><b>quiet</b></td><td>This session's range was well below its usual size (under 60% of its trailing
20-day median range) -- a noticeably slow, low-volatility session.</td></tr>
<tr><td><b>reversal</b></td><td>Price swept beyond the PREVIOUS session's high (or low), then closed back
on the other side by the end of this session -- a stop-run / fakeout shape.</td></tr>
<tr><td><b>trend</b></td><td>Price moved fairly directly in one direction and closed near this session's own
extreme (top or bottom quarter of its range) -- little back-and-forth, real net progress.</td></tr>
<tr><td><b>range_both</b></td><td>Price took out BOTH the previous session's high and low, but closed
back near the middle -- swept liquidity on both sides and went nowhere net.</td></tr>
<tr><td><b>chop</b></td><td>Lots of back-and-forth price movement with very little net progress
(inefficient -- the close ended up close to where it started, even though price moved a lot).</td></tr>
<tr><td><b>normal</b></td><td>None of the above -- an ordinary session, no strong bias either way.</td></tr>
</table>
<p class="muted" style="margin-top:14px">day_type applies the same idea to the WHOLE trading day, using
YESTERDAY's high/low as the reference level instead of the previous session's. Priority: inside_day beats
outside_day beats reversal_day beats trend_day beats range_day beats normal_day.</p>
<table>
<tr><th>Label</th><th>Meaning</th></tr>
<tr><td><b>inside_day</b></td><td>Today's entire range stayed INSIDE yesterday's high-low range --
a contraction / consolidation day.</td></tr>
<tr><td><b>outside_day</b></td><td>Today's high went ABOVE yesterday's high AND today's low went BELOW
yesterday's low -- today's range fully engulfed yesterday's.</td></tr>
<tr><td><b>reversal_day</b></td><td>Today swept yesterday's high (or low), then closed back on the
other side -- same stop-run shape as the session-level "reversal", for the whole day.</td></tr>
<tr><td><b>trend_day</b></td><td>Today closed near its own extreme (top or bottom quarter of the day's
range) -- a directional day.</td></tr>
<tr><td><b>range_day</b></td><td>Today took out BOTH yesterday's high and low, but closed back near
the middle.</td></tr>
<tr><td><b>normal_day</b></td><td>None of the above -- an ordinary day.</td></tr>
</table>
</details>

<div id="days"></div>
<div id="bar" class="elev-raised"><div id="progress">0 / 0 answered</div><button onclick="downloadAnswers()">Download my answers</button></div>
<div class="footer-note">Not financial advice -- this is a rule-review tool, no live trading, read-only against MT5.</div>
<script>
const DATA = %%DATA%%;
const answers = {};
const LABEL_DESC = {
  quiet: "Range well below this session's usual size (<60% of its 20-day trailing median).",
  reversal: "Swept the previous session's high or low, then closed back on the other side.",
  trend: "Moved fairly directly one way and closed near its own extreme (top/bottom quarter).",
  range_both: "Took out BOTH the previous session's high and low, but closed back near the middle.",
  chop: "Lots of back-and-forth, very little net progress.",
  normal: "None of the above -- an ordinary session.",
  inside_day: "Today's whole range stayed inside yesterday's high-low range.",
  outside_day: "Today's high beat yesterday's high AND today's low beat yesterday's low.",
  reversal_day: "Swept yesterday's high or low, then closed back on the other side.",
  trend_day: "Closed near today's own extreme (top or bottom quarter of the day's range).",
  range_day: "Took out BOTH yesterday's high and low, but closed back near the middle.",
  normal_day: "None of the above -- an ordinary day.",
};
const zoomState = {};

/* ---------- THEME (same pattern as design/preview.html) ---------- */
(function(){
  var root = document.documentElement;
  function safeGet(k){ try{ return localStorage.getItem(k); }catch(e){ return null; } }
  function safeSet(k,v){ try{ localStorage.setItem(k,v); }catch(e){} }
  var stored = safeGet('eurusd-theme');
  if(stored === 'light' || stored === 'dark'){ root.setAttribute('data-theme', stored); }
  function current(){
    var a = root.getAttribute('data-theme');
    if(a) return a;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function setIcon(){
    document.getElementById('themeIcon').innerHTML = current() === 'dark'
      ? '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>'
      : '<circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4.2" y1="4.2" x2="5.6" y2="5.6"/><line x1="18.4" y1="18.4" x2="19.8" y2="19.8"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.2" y1="19.8" x2="5.6" y2="18.4"/><line x1="18.4" y1="5.6" x2="19.8" y2="4.2"/>';
  }
  setIcon();
  document.getElementById('themeBtn').addEventListener('click', function(){
    var next = current() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next); safeSet('eurusd-theme', next); setIcon();
    Object.keys(zoomState).forEach(function(idx){ render(idx); });
  });
})();

function hourLabel(h){
  const c = ((h % 24) + 24) % 24;
  const hh = Math.floor(c);
  return String(hh).padStart(2, "0") + ":00";
}

function cssVar(name){
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function fmtFeatVals(v){
  if (v.range_rel == null && v.er == null && v.close_loc == null) return "";
  const parts = [];
  if (v.range_rel != null) parts.push("range_rel " + v.range_rel.toFixed(2));
  if (v.er != null) parts.push("er " + v.er.toFixed(2));
  if (v.close_loc != null) parts.push("close_loc " + v.close_loc.toFixed(2));
  return parts.join(" · ");
}

function drawDay(day, idx){
  const wrap = document.createElement("div"); wrap.className = "day elev-raised";
  const h2 = document.createElement("h2"); h2.textContent = day.td + "  ·  day_type: ";
  const dtLabel = document.createElement("span"); dtLabel.className = "lbl";
  dtLabel.textContent = day.day_type || "—";
  dtLabel.title = LABEL_DESC[day.day_type] || "";
  h2.appendChild(dtLabel);
  wrap.appendChild(h2);

  const zbar = document.createElement("div"); zbar.className = "zoombar";
  const zoomOptions = [{key: "full", label: "Full day"}].concat(
    day.sessions.map(s => ({key: s.id, label: s.id + ": " + (s.label || "?")})));
  zoomOptions.forEach(opt => {
    const b = document.createElement("button");
    b.className = "zoombtn" + (opt.key === "full" ? " active" : "");
    b.id = "zoom_" + idx + "_" + opt.key;
    b.textContent = opt.label;
    b.onclick = () => setZoom(idx, opt.key);
    zbar.appendChild(b);
  });
  wrap.appendChild(zbar);

  const canvas = document.createElement("canvas"); canvas.id = "cv_" + idx;
  canvas.width = 1000; canvas.height = 340;
  wrap.appendChild(canvas);

  const tbl = document.createElement("table");
  tbl.innerHTML = "<tr><th>Label</th><th>Computed value</th><th>Your call</th><th>Note (optional)</th></tr>";
  const rows = day.sessions.map(s => ["session:" + s.id, s.label,
    {range_rel: s.range_rel, er: s.er, close_loc: s.close_loc}]);
  rows.push(["day_type", day.day_type, {range_rel: null, er: null, close_loc: day.day_close_loc}]);
  rows.forEach(([key, val, featVals]) => {
    const tr = document.createElement("tr");
    const ansKey = day.td + "|" + key;
    const desc = LABEL_DESC[val] || "";
    const fv = fmtFeatVals(featVals);
    tr.innerHTML = "<td>" + key + "</td><td><b class='lbl' title=\"" + desc.replace(/"/g, "&quot;") + "\">" +
      (val || "—") + "</b>" + (fv ? "<span class='featvals tabular'>" + fv + "</span>" : "") + "</td>" +
      "<td><button class='ans' id='a_" + ansKey + "' onclick=\"setAns('" + ansKey + "','agree')\">Agree</button>" +
      "<button class='ans' id='d_" + ansKey + "' onclick=\"setAns('" + ansKey + "','disagree')\">Disagree</button></td>" +
      "<td><input class='note' placeholder='optional note' oninput=\"setNote('" + ansKey + "', this.value)\"></td>";
    tbl.appendChild(tr);
  });
  wrap.appendChild(tbl);
  document.getElementById("days").appendChild(wrap);
  zoomState[idx] = "full";
  requestAnimationFrame(() => render(idx));
}

function setZoom(idx, key){
  zoomState[idx] = key;
  const day = DATA.days[idx];
  ["full"].concat(day.sessions.map(s => s.id)).forEach(k => {
    document.getElementById("zoom_" + idx + "_" + k).classList.toggle("active", k === key);
  });
  render(idx);
}

function render(idx){
  const day = DATA.days[idx];
  const canvas = document.getElementById("cv_" + idx);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const key = zoomState[idx] || "full";
  let winLo, winHi;
  if (key === "full") {
    winLo = Math.min(...day.bars.map(b => b[0]));
    winHi = Math.max(...day.bars.map(b => b[0]));
  } else {
    const s = day.sessions.find(s => s.id === key);
    const pad = (s.hi - s.lo) * 0.15 || 0.25;
    winLo = s.lo - pad; winHi = s.hi + pad;
  }
  const bars = day.bars.filter(b => b[0] >= winLo && b[0] <= winHi);
  const muted = cssVar("--text-3") || "#9aa6bd";
  const accent = cssVar("--accent") || "#0EA5A0";
  const bull = cssVar("--bull") || "#0F9D76";
  const bear = cssVar("--bear") || "#E5484D";
  if (!bars.length) { ctx.fillStyle = muted; ctx.fillText("no bars in this window", 10, 20); return; }

  const W = canvas.width, H = canvas.height, padL = 55, padR = 12, padT = 30, padB = 26;
  let hi = Math.max(...bars.map(b => b[2])), lo = Math.min(...bars.map(b => b[3]));
  // widen the price axis to fit PDH/PDL reference lines when they're in view (full-day zoom)
  if (key === "full" && day.pdh != null) hi = Math.max(hi, day.pdh);
  if (key === "full" && day.pdl != null) lo = Math.min(lo, day.pdl);
  const span = (hi - lo) || 1e-6;
  const xOf = h => padL + (h - winLo) / (winHi - winLo || 1) * (W - padL - padR);
  const yOf = p => H - padB - (p - lo) / span * (H - padT - padB);

  // price gridlines (5 ticks)
  ctx.font = "11px sans-serif"; ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const p = lo + span * i / 4;
    const y = yOf(p);
    ctx.strokeStyle = "rgba(150,143,130,0.18)"; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillStyle = muted; ctx.fillText(p.toFixed(5), padL - 6, y + 3);
  }
  // hour gridlines: every hour if zoomed (span<=6h), else every 2h
  const hourStep = (winHi - winLo) <= 7 ? 1 : 2;
  ctx.textAlign = "center";
  for (let h = Math.ceil(winLo / hourStep) * hourStep; h <= winHi; h += hourStep) {
    const x = xOf(h);
    ctx.strokeStyle = "rgba(150,143,130,0.14)"; ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke();
    ctx.fillStyle = muted; ctx.fillText(hourLabel(h), x, H - 8);
  }
  // range annotation (pips, assuming EURUSD pip = 0.0001)
  ctx.textAlign = "left"; ctx.fillStyle = muted;
  ctx.fillText("range shown: " + ((hi - lo) / 0.0001).toFixed(1) + " pips", padL, 14);

  // session shading + labels (only the ones overlapping this window)
  day.sessions.forEach(s => {
    if (s.hi < winLo || s.lo > winHi) return;
    const x0 = xOf(Math.max(s.lo, winLo)), x1 = xOf(Math.min(s.hi, winHi));
    ctx.fillStyle = "rgba(" + (getComputedStyle(document.documentElement).getPropertyValue("--amber-rgb") || "227,155,47") + ",0.07)";
    ctx.fillRect(x0, padT, x1 - x0, H - padT - padB);
    ctx.strokeStyle = "rgba(" + (getComputedStyle(document.documentElement).getPropertyValue("--amber-rgb") || "227,155,47") + ",0.35)";
    ctx.beginPath(); ctx.moveTo(x0, padT); ctx.lineTo(x0, H - padB); ctx.stroke();
    ctx.fillStyle = cssVar("--amber") || "#E39B2F"; ctx.textAlign = "left"; ctx.font = "11px sans-serif";
    ctx.fillText(s.id + ": " + (s.label || "?"), x0 + 3, padT + 13);
  });

  // previous-day high/low reference lines (day_type calls) -- full-day zoom only: they're
  // whole-day levels, and drawing them on a single-session zoom (whose window is usually much
  // narrower than the day's range) would mostly just clip off-canvas or crowd the session's
  // own labels for no benefit -- Akash's day_type calls happen looking at the full day anyway.
  if (key === "full") {
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1.2;
    if (day.pdh != null) {
      const y = yOf(day.pdh);
      ctx.strokeStyle = accent; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.setLineDash([]); ctx.fillStyle = accent; ctx.textAlign = "right"; ctx.font = "10px sans-serif";
      ctx.fillText("PDH " + day.pdh.toFixed(5), W - padR - 2, y - 3); ctx.setLineDash([5, 4]);
    }
    if (day.pdl != null) {
      const y = yOf(day.pdl);
      ctx.strokeStyle = accent; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.setLineDash([]); ctx.fillStyle = accent; ctx.textAlign = "right"; ctx.font = "10px sans-serif";
      ctx.fillText("PDL " + day.pdl.toFixed(5), W - padR - 2, y + 11); ctx.setLineDash([5, 4]);
    }
    ctx.setLineDash([]);
  }

  // candles
  const bw = Math.max(2, (W - padL - padR) / bars.length * 0.7);
  bars.forEach(([h, o, hh, l, c]) => {
    const x = xOf(h);
    ctx.strokeStyle = c >= o ? bull : bear;
    ctx.beginPath(); ctx.moveTo(x, yOf(hh)); ctx.lineTo(x, yOf(l)); ctx.stroke();
    ctx.fillStyle = c >= o ? bull : bear;
    ctx.fillRect(x - bw / 2, yOf(Math.max(o, c)), bw, Math.max(1, Math.abs(yOf(o) - yOf(c))));
  });
}

function setAns(key, val){
  answers[key] = Object.assign(answers[key] || {}, {call: val});
  const a = document.getElementById("a_" + key), d = document.getElementById("d_" + key);
  a.classList.toggle("sel-agree", val === "agree");
  d.classList.toggle("sel-disagree", val === "disagree");
  updateProgress();
}
function setNote(key, val){ answers[key] = Object.assign(answers[key] || {}, {note: val}); }
function updateProgress(){
  const total = DATA.days.reduce((n, d) => n + d.sessions.length + 1, 0);
  const answered = Object.values(answers).filter(a => a.call).length;
  document.getElementById("progress").textContent = answered + " / " + total + " answered";
}
function downloadAnswers(){
  const out = {generated_for: DATA.generated_for, answers: answers};
  const blob = new Blob([JSON.stringify(out, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = "label_validation_answers.json";
  document.body.appendChild(a); a.click(); a.remove();
}

DATA.days.forEach(drawDay);
updateProgress();
</script>
</body></html>"""


def render_html(payload: dict) -> str:
    return (_HTML_TEMPLATE
            .replace("%%DATA%%", json.dumps(payload))
            .replace("%%COUNT%%", str(len(payload["days"]))))


def score(answers: dict, payload: dict) -> pd.DataFrame:
    """Per-label-VALUE agreement (e.g. all 'reversal' calls across every session pooled
    together, not split by session -- SESSIONS_AND_CONTEXT S3 intends `character` to mean the
    same qualitative thing regardless of which session produced it). Also breaks out
    `day_type` separately since it's a different label family (S2, not S3)."""
    rows = []
    by_value: dict[str, list[bool]] = {}
    by_daytype: dict[str, list[bool]] = {}
    for day in payload["days"]:
        for s in day["sessions"]:
            key = f"{day['td']}|session:{s['id']}"
            a = answers.get(key)
            if a and a.get("call") and s["label"]:
                by_value.setdefault(s["label"], []).append(a["call"] == "agree")
        key = f"{day['td']}|day_type"
        a = answers.get(key)
        if a and a.get("call") and day["day_type"]:
            by_daytype.setdefault(day["day_type"], []).append(a["call"] == "agree")

    for label, calls in sorted(by_value.items()):
        n = len(calls)
        rate = sum(calls) / n if n else float("nan")
        rows.append(dict(family="character", label=label, n=n, agree_rate=rate, passes_80pct=rate >= 0.8))
    for label, calls in sorted(by_daytype.items()):
        n = len(calls)
        rate = sum(calls) / n if n else float("nan")
        rows.append(dict(family="day_type", label=label, n=n, agree_rate=rate, passes_80pct=rate >= 0.8))
    return pd.DataFrame(rows)


def build(cache_dir: str, sessions_cfg: dict, n: int = 20, seed: int = 43, strategy: str = "curated"):
    from nylab import cache as cache_mod
    bars, days = cache_mod.load(cache_dir)
    missing = [f"{_PREFIX[sid]}_character" for sid in SESSIONS_TO_VALIDATE
               if f"{_PREFIX[sid]}_character" not in days.columns]
    if missing or "day_type" not in days.columns:
        raise SystemExit(
            "The cached day table doesn't have session/day-type columns yet "
            f"(missing: {missing or ['day_type']}). Run `python -m nylab run <csv>` first "
            "(without --no-cache) so the Phase 5 session attach runs before caching.")
    if strategy == "random":
        tds = sample_days(days, n=n, seed=seed)
    elif strategy == "curated":
        tds = sample_days_curated(days, n=n, seed=seed)
    else:
        raise SystemExit(f"Unknown --strategy {strategy!r}; use 'curated' or 'random'.")
    payload = build_payload(bars, days, sessions_cfg, tds)
    html = render_html(payload)
    return html, payload
