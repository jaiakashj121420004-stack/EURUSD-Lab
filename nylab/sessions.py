"""nylab.sessions -- Phase 5's SESSION table (SESSIONS_AND_CONTEXT.md S1-S3): one row per
session per trading day, for every session window except `cbdr` (see NOTE below), plus day
types and the wide day-table join that lets hypothesis YAMLs use dotted cross-session syntax
(`lon.character`, `nyam_full.took_prev_high`, `day.has_fomc`) with ZERO changes to
nylab.hyp_dsl/hyp_engine -- the dotted rewrite there is a pure `name.attr` -> `name_attr` text
substitution, and hyp_engine builds its evaluation namespace directly from whatever columns
the day table `d` already has. This module's job is to put the right columns, under the right
names, onto `d`.

NOTE on `cbdr`: deliberately excluded from this module. Its high/low/range already exist as
DAY columns (`cbdr_high/low/range`, computed correctly in nylab.days.build_days from absolute
NY timestamps because it spans the td boundary -- window()'s h-relative logic can't handle
that). It is not one of SESSIONS_AND_CONTEXT S5.1's default transition-matrix pairs either.
Character/day-type/cross-session machinery here simply doesn't touch it -- a defensible scope
cut, not an oversight (see docs/PROGRESS.md's Phase 5 section).

NOTE on a real naming collision with the PRE-EXISTING (v0-era) day columns: v0's "nyam_*"
columns (nyam_open/high/low/close/hi_t/lo_t, available_at_h=10) are actually the 07:00-10:00 NY
AM KILLZONE window -- what SESSIONS_AND_CONTEXT S1 calls `nyam_kz`. The NEW `nyam` id in that
same table is the BROADER 07:00-12:00 NY AM session, a genuinely different window with no
legacy equivalent. Emitting its raw price columns under the natural prefix "nyam_" would
silently collide with (and shadow the meaning of) the existing "nyam_*" legacy columns. So:
  - `asia`, `lon`, `nyam_kz` (session ids that are EXACT duplicates of an existing legacy
    window, same bounds, same numbers): this module does NOT re-emit open/high/low/close/
    hi_t/lo_t/range_pips for them -- use the existing `asia_*`/`lon_*`/`nyam_*` (sic -- that's
    `nyam_kz`'s window) legacy columns. It DOES add every genuinely new SESSION-table column
    (character, range_rel, swing_count, ...) under that id's own prefix, e.g. `nyam_kz_character`.
  - `nyam` (the new, broader session -- no legacy equivalent, but a NAME COLLISION with legacy
    `nyam_*`): ALL of its columns, raw price included, are emitted under the prefix
    `nyam_full_` instead, i.e. a hypothesis writes `nyam_full.high` / `nyam_full.character`,
    never `nyam.high` (that stays the legacy 07:00-10:00 number).
  - every other id (`lon_sb`, `lon_full`, `nyam_sb`, `lunch`, `nypm`, `nypm_sb`, `lon_close`,
    `lon_ny_gap`) has no legacy equivalent and no name collision: full column set under its
    own id.

NOTE on `lon_ny_gap` (added 2026-09-25, Akash's own request after reviewing the first label-
validation round -- "observe the time in between sessions, especially London to NY"): the
07:00-... London killzone (`lon`) ends at h=5.0 and the NY AM killzone (`nyam_kz`) starts at
h=7.0; nothing tracked that 2-hour gap before. It's added as its own full session (window
5.0-7.0), predecessor `lon` (same as `nyam`/`nyam_kz`/`nyam_sb`/`lon_close` already use) --
so its raid/character features ask "did the gap take out London's high/low", which is the
actual question a London-to-NY transition is about. Deliberately NOT inserted into the
asia->lon->nyam->lunch->nypm chain itself (i.e. `nyam`'s own `_PREV_IN_CHAIN` stays `lon`,
unchanged) -- that would silently redefine what "immediately preceding session" means for
`nyam`/`nyam_kz`/`nyam_sb`'s already-computed raid features, which RESEARCH_PROTOCOL.md's
frozen-thresholds rule says needs its own explicit decision, not a side effect of adding an
unrelated session.

NOTE on `raids`/`first_raid` scope: SESSIONS_AND_CONTEXT S2 lists candidate levels as "prior
sessions' highs/lows (same td), pdh/pdl, pwh/pwl, o_mid". This module raids against the
IMMEDIATELY PRECEDING chain session's high/low (via _PREV_IN_CHAIN) plus pdh/pdl/pwh/pwl --
six candidate levels, three "above" (prev_high, pdh, pwh) and three "below" (prev_low, pdl,
pwl). `o_mid` is deliberately left out: FEATURES_SPEC.md S3 itself calls it out as "a
reference, not liquidity" in its own level list, and a directionless "traded through the
midnight open" event doesn't fit the above/below sweep-vs-break classification below without
inventing a rule the spec never states. `raids` is stored as a COUNT (`raids_count`), not the
full structured list the doc sketches -- the list's information (which level, when, sweep or
break) is fully captured by `first_raid_level`/`first_raid_type`/`first_raid_t` for the
earliest one; a hypothesis wanting a specific later level needs a new column, not yet built.
Both cuts are disclosed here and in docs/PROGRESS.md, not silent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import calendar_features
from nylab import ict_features as ictf
from nylab.days import first_cross, window

# The 11 SESSIONS_AND_CONTEXT S1 ids this module builds (cbdr excluded, see module docstring),
# plus `lon_ny_gap` (added 2026-09-25, not part of the original spec -- see the docstring above).
SESSION_IDS = ["asia", "lon", "lon_sb", "lon_full", "nyam", "nyam_kz", "nyam_sb",
               "lunch", "nypm", "nypm_sb", "lon_close", "lon_ny_gap"]

# S1's chain: asia -> lon -> nyam -> lunch -> nypm (cbdr excluded, Silver Bullets are outcome
# windows not separate chain links). A sub/context window inherits its PARENT session's
# predecessor (e.g. lon_sb's "immediately preceding session" is asia, same as lon's).
_PREV_IN_CHAIN = {
    "asia": None,
    "lon": "asia", "lon_sb": "asia", "lon_full": "asia",
    "nyam": "lon", "nyam_kz": "lon", "nyam_sb": "lon", "lon_close": "lon", "lon_ny_gap": "lon",
    "lunch": "nyam",
    "nypm": "lunch", "nypm_sb": "lunch",
}

_LEGACY_DUP = {"asia", "lon", "nyam_kz"}   # exact legacy duplicate -> skip raw OHLC re-emit
_WIDE_PREFIX = {"nyam": "nyam_full"}       # collision override, see module docstring

_RAW_COLS = ["open", "high", "low", "close", "hi_t", "lo_t"]
_NEW_COLS = ["range_pips", "range_rel", "net_pips", "dir", "er", "close_loc",
             "swing_count", "disp_count", "fvg_count_bull", "fvg_count_bear",
             "took_prev_high", "took_prev_low", "both_sides",
             "first_raid_level", "first_raid_type", "first_raid_t", "raids_count",
             "news_high_usd", "news_high_eur", "news_surprise_z", "character"]

DEAD_BAND = 0.15          # |net_pips| < DEAD_BAND * range_pips -> dir = 0 (flat)
RANGE_REL_LOOKBACK = 20   # trailing td, excludes the current day (RESEARCH_PROTOCOL-style: no look-ahead)
K_BACK = 6                # FEATURES_SPEC S3 default: bars to look for a close-back (M5 -> 30 min)
BREAK_CLOSE_PIPS = 3.0    # FEATURES_SPEC S3 default
RAID_TOL_PIPS = 0.1       # FEATURES_SPEC S3 default ("any trade-through")
HIGH_IMPORTANCE = calendar_features.HIGH_IMPORTANCE

CHARACTER_ORDER = ("quiet", "reversal", "trend", "range_both", "chop", "normal")
DAY_TYPE_ORDER = ("inside_day", "outside_day", "reversal_day", "trend_day", "range_day", "normal_day")


def _efficiency_ratio(df: pd.DataFrame, lo: float, hi: float) -> pd.Series:
    """FEATURES_SPEC-style ER on M5 closes within [lo, hi): |close_end - close_start| /
    sum(|delta close|) over the bars in the window. 0 = pure chop, 1 = a straight line."""
    sub = df[(df.h >= lo) & (df.h < hi)]
    g = sub.groupby("td")["close"]
    net = (g.last() - g.first()).abs()
    denom = g.apply(lambda s: s.diff().abs().sum())
    return (net / denom).replace([np.inf, -np.inf], np.nan)


def _confirmed_count(df: pd.DataFrame, event: pd.Series, lo: float, hi: float, confirm_lag: int = 0) -> pd.Series:
    """Count of True `event` bars whose PIVOT is inside [lo, hi) for this td, AND whose
    confirmation (event bar position + confirm_lag) is ALSO inside the same window -- so a
    fractal swing sitting right at the window's edge, not yet confirmed by the window's own
    close, is correctly excluded (FEATURES_SPEC S4's own look-ahead trap). confirm_lag=0 for
    displacement candles / FVGs, which the spec says are knowable at their own bar's close."""
    in_win = (df.h >= lo) & (df.h < hi)
    if confirm_lag:
        confirmed_in_win = in_win & in_win.shift(-confirm_lag, fill_value=False)
    else:
        confirmed_in_win = in_win
    hit = event & confirmed_in_win
    return df.loc[hit, "td"].value_counts()


def _news_for_window(cal: pd.DataFrame, trading_days: pd.DatetimeIndex, lo: float, hi: float) -> pd.DataFrame:
    """news_high_usd / news_high_eur (counts) + news_surprise_z (sign-kept, largest |z| among
    ALL high-importance events -- any currency -- inside [lo, hi) that td). `cal` must already
    have `surprise_z` (nylab.calendar_features.compute_surprise)."""
    td, h = calendar_features._assign_td_h(cal["time_ny"])
    c = cal.assign(td=td, h=h)
    c = c[(c["importance"] >= HIGH_IMPORTANCE) & (c["h"] >= lo) & (c["h"] < hi) & c["td"].isin(trading_days)]
    out = pd.DataFrame(index=trading_days)
    out["news_high_usd"] = c[c["currency"] == "USD"].groupby("td").size().reindex(trading_days, fill_value=0)
    out["news_high_eur"] = c[c["currency"] == "EUR"].groupby("td").size().reindex(trading_days, fill_value=0)
    # Only events that HAVE a surprise_z can be the "largest |z|" (surprise_z is NaN until an
    # event has >= 8 prior releases). Dropping NaN first gives the same result pandas 2 gave
    # for an all-NaN day (NaN), and avoids pandas 3's hard error on an all-NA idxmax group.
    cz = c.dropna(subset=["surprise_z"])
    if len(cz):
        idx = cz.assign(absz=cz["surprise_z"].abs()).groupby("td")["absz"].idxmax()
        out["news_surprise_z"] = idx.map(cz["surprise_z"])
        out["news_surprise_z"] = out["news_surprise_z"].reindex(trading_days)
    else:
        out["news_surprise_z"] = np.nan
    return out


def _classify_raid_side(highs, lows, closes, start_pos: int, end_pos: int, level: float, side: str, pip: float):
    """Scan bar positions [start_pos, end_pos) for the first raid of `level` on `side`
    ('above': high > level+tol; 'below': low < level-tol). If found, classify sweep vs break
    (FEATURES_SPEC S3) using up to K_BACK bars AFTER the raid bar (confirmation is allowed to
    run past the session window's own close -- the spec places no such restriction on it).
    Returns None, or (raid_pos, raid_type)."""
    tol = RAID_TOL_PIPS * pip
    n = len(highs)
    raid_pos = None
    for i in range(start_pos, end_pos):
        if side == "above" and highs[i] > level + tol:
            raid_pos = i
            break
        if side == "below" and lows[i] < level - tol:
            raid_pos = i
            break
    if raid_pos is None:
        return None
    raid_type = None
    for j in range(raid_pos, min(raid_pos + K_BACK + 1, n)):
        c = closes[j]
        if side == "above":
            if c > level and (c - level) / pip > BREAK_CLOSE_PIPS:
                raid_type = "break"
                break
            if c < level:
                raid_type = "sweep"
                break
        else:
            if c < level and (level - c) / pip > BREAK_CLOSE_PIPS:
                raid_type = "break"
                break
            if c > level:
                raid_type = "sweep"
                break
    if raid_type is None:
        raid_type = "break"  # never closed back within K_BACK -> acceptance
    return raid_pos, raid_type


def _first_raid_table(df: pd.DataFrame, lo: float, hi: float, levels: dict, pip: float) -> pd.DataFrame:
    """`levels`: {name: (side, per-td level Series)}. One row per td with columns
    first_raid_level, first_raid_type, first_raid_t (NY h of the raid bar), raids_count
    (distinct levels raided, not just the first)."""
    highs, lows, closes, hs, tds = (df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(),
                                     df["h"].to_numpy(), df["td"])
    out = {}
    for td_val, day_slice in df.groupby("td").groups.items():
        pos = day_slice.to_numpy()
        win_pos = pos[(hs[pos] >= lo) & (hs[pos] < hi)]
        if len(win_pos) == 0:
            continue
        start_pos, end_pos = int(win_pos.min()), int(win_pos.max()) + 1
        events = []
        for name, (side, level_series) in levels.items():
            level = level_series.get(td_val, np.nan)
            if pd.isna(level):
                continue
            found = _classify_raid_side(highs, lows, closes, start_pos, end_pos, float(level), side, pip)
            if found is not None:
                raid_pos, raid_type = found
                events.append((raid_pos, name, raid_type))
        if not events:
            out[td_val] = (None, None, np.nan, 0)
        else:
            events.sort(key=lambda e: e[0])
            first_pos, first_name, first_type = events[0]
            out[td_val] = (first_name, first_type, float(hs[first_pos]), len(events))
    res = pd.DataFrame.from_dict(out, orient="index",
                                  columns=["first_raid_level", "first_raid_type", "first_raid_t", "raids_count"])
    res.index.name = "td"
    return res


def _label_character(s: pd.DataFrame) -> pd.Series:
    """SESSIONS_AND_CONTEXT S3's ordered rule table, first match wins.

    `trend` has two independent paths (v2, confirmed with Akash 2026-09-25 after his first
    30-day label-validation round surfaced 7+ disagreements of the same shape): the original
    efficiency-ratio path, OR an "unusually large range + strongly extreme close" path that
    catches decisive, wide sessions that closed at an extreme even when price chopped enough
    inside the session to keep er below 0.45. Thresholds (range_rel>=1.4, close_loc<=0.20/
    >=0.80) were set from his own flagged examples (lowest observed range_rel=1.48,
    loosest observed close_loc=0.17/0.94) with a little headroom -- not just AI-picked.
    """
    took_high = s["took_prev_high"].fillna(False)
    took_low = s["took_prev_low"].fillna(False)
    quiet = s["range_rel"] < 0.6
    reversal = (took_high & (s["close_loc"] <= 0.35)) | (took_low & (s["close_loc"] >= 0.65))
    trend_er = (s["er"] >= 0.45) & ((s["close_loc"] >= 0.75) | (s["close_loc"] <= 0.25))
    trend_range = (s["range_rel"] >= 1.4) & ((s["close_loc"] >= 0.80) | (s["close_loc"] <= 0.20))
    trend = trend_er | trend_range
    range_both = s["both_sides"].fillna(False) & (s["close_loc"] > 0.35) & (s["close_loc"] < 0.65)
    chop = s["er"] < 0.25

    out = pd.Series("normal", index=s.index, dtype=object)
    out[chop] = "chop"
    out[range_both] = "range_both"
    out[trend] = "trend"
    out[reversal] = "reversal"
    out[quiet] = "quiet"  # applied last so it overwrites -- i.e. wins first, matching CHARACTER_ORDER
    out[s["range_rel"].isna() | s["er"].isna() | s["close_loc"].isna()] = np.nan
    return out


def build_one_session(df: pd.DataFrame, d: pd.DataFrame, cal: pd.DataFrame | None,
                       sessions_cfg: dict, sid: str, pip: float) -> pd.DataFrame:
    """The full SESSION table (SESSIONS_AND_CONTEXT S2) for ONE session id, indexed by td."""
    lo, hi = sessions_cfg[sid]
    raw = window(df, lo, hi, sid)
    raw.columns = [c.replace(f"{sid}_", "") for c in raw.columns]  # -> open/high/low/close/hi_t/lo_t
    out = raw.copy()
    out["range_pips"] = (out["high"] - out["low"]) / pip
    out["net_pips"] = (out["close"] - out["open"]) / pip
    out["dir"] = np.sign(out["net_pips"])
    out.loc[out["net_pips"].abs() < DEAD_BAND * out["range_pips"], "dir"] = 0.0
    out["close_loc"] = (out["close"] - out["low"]) / (out["high"] - out["low"])
    out["er"] = _efficiency_ratio(df, lo, hi)
    out["range_rel"] = out["range_pips"] / out["range_pips"].shift(1).rolling(RANGE_REL_LOOKBACK).median()

    sh, sl = ictf.fractal_swings(df, n=2)
    atr = ictf.atr(df)
    disp = ictf.displacement_candles(df, atr)
    fvg_bull, fvg_bear = ictf.fair_value_gaps(df, atr, pip=pip)
    out["swing_count"] = (_confirmed_count(df, sh, lo, hi, confirm_lag=2)
                           .add(_confirmed_count(df, sl, lo, hi, confirm_lag=2), fill_value=0)
                           .reindex(out.index, fill_value=0))
    out["disp_count"] = _confirmed_count(df, disp, lo, hi).reindex(out.index, fill_value=0)
    out["fvg_count_bull"] = _confirmed_count(df, fvg_bull, lo, hi).reindex(out.index, fill_value=0)
    out["fvg_count_bear"] = _confirmed_count(df, fvg_bear, lo, hi).reindex(out.index, fill_value=0)

    pred = _PREV_IN_CHAIN[sid]
    if pred is None:
        out["took_prev_high"] = False
        out["took_prev_low"] = False
    else:
        plo, phi = sessions_cfg[pred]
        pred_raw = window(df, plo, phi, pred)
        prev_high = pred_raw[f"{pred}_high"]
        prev_low = pred_raw[f"{pred}_low"]
        t_hi = first_cross(df, lo, hi, prev_high, above=True)
        t_lo = first_cross(df, lo, hi, prev_low, above=False)
        out["took_prev_high"] = out.index.isin(t_hi.index)
        out["took_prev_low"] = out.index.isin(t_lo.index)
    out["both_sides"] = out["took_prev_high"] & out["took_prev_low"]

    levels = {}
    if pred is not None:
        plo, phi = sessions_cfg[pred]
        pred_raw = window(df, plo, phi, pred)
        levels["prev_high"] = ("above", pred_raw[f"{pred}_high"])
        levels["prev_low"] = ("below", pred_raw[f"{pred}_low"])
    if "pdh" in d.columns:
        levels["pdh"] = ("above", d["pdh"])
        levels["pdl"] = ("below", d["pdl"])
    if "pwh" in d.columns:
        levels["pwh"] = ("above", d["pwh"])
        levels["pwl"] = ("below", d["pwl"])
    raid_tbl = _first_raid_table(df, lo, hi, levels, pip)
    out = out.join(raid_tbl)
    for c in ("first_raid_level", "first_raid_type"):
        if c not in out.columns:
            out[c] = None
    for c in ("first_raid_t",):
        if c not in out.columns:
            out[c] = np.nan
    if "raids_count" not in out.columns:
        out["raids_count"] = 0
    out["raids_count"] = out["raids_count"].fillna(0).astype(int)

    if cal is not None and len(cal):
        news = _news_for_window(cal, out.index, lo, hi)
        out = out.join(news)
    else:
        out["news_high_usd"] = 0
        out["news_high_eur"] = 0
        out["news_surprise_z"] = np.nan

    out["character"] = _label_character(out)
    return out


def build_all_sessions(df: pd.DataFrame, d: pd.DataFrame, calendar: pd.DataFrame | None,
                        sessions_cfg: dict, pip: float) -> dict[str, pd.DataFrame]:
    """{session_id: SESSION table} for every id in SESSION_IDS. `calendar` is
    nylab.calendar_io's canonical schema (or None to skip news columns entirely)."""
    cal = None
    if calendar is not None and len(calendar):
        cal = calendar_features.compute_surprise(calendar) if "surprise_z" not in calendar.columns else calendar
    return {sid: build_one_session(df, d, cal, sessions_cfg, sid, pip) for sid in SESSION_IDS}


def attach_session_features(d: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Wide-join the SESSION tables onto the DAY table `d`, column-named `{prefix}_{col}` so
    nylab.hyp_dsl's dotted rewrite (`lon.character` -> `lon_character`) resolves them with no
    change to hyp_dsl/hyp_engine. See the module docstring for exactly which columns are
    skipped (legacy duplicates) or renamed (the `nyam` collision).

    One more collision, found by running this against real data rather than guessed up front:
    legacy `lon_dir` (plain sign(close-open), no dead-band) already exists, and this module's
    new `dir` (SAME idea, but with a dead-band -- SESSIONS_AND_CONTEXT S2) would collide under
    the name `lon_dir`. Rather than silently overwrite the legacy column's meaning (every
    existing hypothesis/report number that reads `lon_dir` must keep meaning exactly what it
    always meant), this function detects ANY such collision generically -- not just this one --
    and skips the NEW column, keeping the legacy one. So `lon.dir` in a hypothesis's DSL is the
    legacy, non-dead-banded value; every other session id's `dir` is the new dead-banded one.
    Any columns skipped this way are returned as a list for the caller to log/document."""
    out = d
    skipped: list[str] = []
    for sid, tbl in tables.items():
        prefix = _WIDE_PREFIX.get(sid, sid)
        cols = list(tbl.columns) if sid not in _LEGACY_DUP else [c for c in tbl.columns if c not in _RAW_COLS]
        renamed = tbl[cols].rename(columns={c: f"{prefix}_{c}" for c in cols})
        collide = [c for c in renamed.columns if c in out.columns]
        if collide:
            skipped.extend(collide)
            renamed = renamed.drop(columns=collide)
        out = out.join(renamed)
    out.attrs["sessions_skipped_columns"] = sorted(set(skipped))
    return out


def _day_type(d: pd.DataFrame) -> pd.Series:
    """Day type (SESSIONS_AND_CONTEXT S2, 'same logic on the full day vs the previous day'):
    the previous COMPLETED day plays the role of the 'predecessor session'. inside_day/
    outside_day are the two S2-specific labels (relative to pdh/pdl); trend_day/reversal_day/
    range_day reuse S3's character rules verbatim with the day's own open/high/low/close,
    er/close_loc computed the same way, and 'took prev high/low' meaning pdh/pdl. `normal_day`
    is this module's own catch-all (S2 doesn't name one, but every td needs SOME label) --
    disclosed here and in docs/PROGRESS.md, not silent."""
    rng = d["day_high"] - d["day_low"]
    close_loc = (d["day_close"] - d["day_low"]) / rng
    took_high = d["day_high"] > d["pdh"]
    took_low = d["day_low"] < d["pdl"]
    inside = ~took_high & ~took_low
    outside = took_high & took_low
    reversal = (took_high & (close_loc <= 0.35)) | (took_low & (close_loc >= 0.65))
    er = (d["day_close"] - d["day_open"]).abs() / (d["day_range"].where(d["day_range"] != 0))
    trend = (close_loc >= 0.75) | (close_loc <= 0.25)
    range_day = (took_high & took_low) & (close_loc > 0.35) & (close_loc < 0.65)

    out = pd.Series("normal_day", index=d.index, dtype=object)
    out[range_day] = "range_day"
    out[trend & ~outside] = "trend_day"
    out[reversal] = "reversal_day"
    out[outside] = "outside_day"
    out[inside] = "inside_day"
    return out


def build_day_types(d: pd.DataFrame) -> pd.DataFrame:
    """New day-level columns: day_type (categorical) plus the two S2-named booleans it's built
    from (day_inside_prev_range, day_outside_prev_range) for anyone who wants the raw flags."""
    out = pd.DataFrame(index=d.index)
    out["day_inside_prev_range"] = (d["day_high"] <= d["pdh"]) & (d["day_low"] >= d["pdl"])
    out["day_outside_prev_range"] = (d["day_high"] > d["pdh"]) & (d["day_low"] < d["pdl"])
    out["day_type"] = _day_type(d)
    return out


def column_docs(sessions_cfg: dict) -> dict[str, float]:
    """available_at_h for every column this module can produce -- merged into
    nylab.days.COLUMN_DOCS exactly like Phase 4's calendar columns, so the Phase 3 look-ahead
    check covers Phase 5's session/day-type columns too."""
    docs = {}
    for sid in SESSION_IDS:
        prefix = _WIDE_PREFIX.get(sid, sid)
        avail = sessions_cfg[sid][1]  # S1's "Ends (available at h)" column == the window's own hi bound
        cols = _NEW_COLS if sid in _LEGACY_DUP else _RAW_COLS + _NEW_COLS
        for c in cols:
            docs[f"{prefix}_{c}"] = avail
    docs["day_inside_prev_range"] = 17.0
    docs["day_outside_prev_range"] = 17.0
    docs["day_type"] = 17.0
    return docs


def column_starts_at_h(sessions_cfg: dict) -> dict[str, float]:
    """ROADMAP 5.7.2: starts_at_h for every column this module produces -- merged into
    nylab.days.COLUMN_STARTS_AT_H the same way column_docs() merges into COLUMN_DOCS. Every one
    of these (range_pips, range_rel, er, close_loc, character, ...) is derived from that
    session's own OHLC path, so it genuinely needs the WHOLE session window (a big early move
    inside the window can flip range_rel/er/character just as easily as a late one) -- same
    conservative "needs the whole window" treatment as that session's own raw _high/_low, even
    for columns like `open`/`close` that could in principle be argued point-like: no currently
    loaded hypothesis's outcome references a session-level open/close/dir, so there is no reason
    to carve out that narrower exception here the way nylab.days does for the DAY table's own
    _close/_dir columns (see nylab.days.COLUMN_STARTS_AT_H's docstring)."""
    docs = {}
    for sid in SESSION_IDS:
        prefix = _WIDE_PREFIX.get(sid, sid)
        lo = sessions_cfg[sid][0]  # S1's "Starts (h)" column -- the window's own lo bound
        cols = _NEW_COLS if sid in _LEGACY_DUP else _RAW_COLS + _NEW_COLS
        for c in cols:
            docs[f"{prefix}_{c}"] = lo
    docs["day_inside_prev_range"] = -7.0
    docs["day_outside_prev_range"] = -7.0
    docs["day_type"] = -7.0
    return docs
