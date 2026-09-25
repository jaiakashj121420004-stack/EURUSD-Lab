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

Sampling is NOT pure random: SESSIONS_AND_CONTEXT S3's own concern is that a RARE label (like
nyam_full trend, 2/1300 days) could simply never appear in 30 uniform-random days, making the
80% bar untestable for it. So sample_days() first tries to include at least MIN_PER_LABEL
occurrences of every label that occurs for each validated session (stratified), then fills the
remainder up to n with uniform-random days -- ROADMAP 5.6 says "30 random days"; this is that,
plus a floor under the rare labels so validation can't silently skip them. Disclosed in the
generated HTML itself, not hidden.
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
SESSIONS_TO_VALIDATE = ["asia", "lon", "nyam_kz", "nyam_sb", "nypm"]
_PREFIX = {"asia": "asia", "lon": "lon", "nyam_kz": "nyam_kz", "nyam_sb": "nyam_sb", "nypm": "nypm"}
MIN_PER_LABEL = 1
BAR_LO, BAR_HI = -7.0, 17.0  # full trading day span (asia start .. nypm/cbdr-adjacent end)


def sample_days(days: pd.DataFrame, n: int = 30, seed: int = 42) -> list[pd.Timestamp]:
    """Stratified-then-random. The stratified floor (>=MIN_PER_LABEL days per occurring label,
    per validated session) is NEVER trimmed back down, even if it alone exceeds `n` -- trimming
    it would silently re-introduce the exact "rare label never gets checked" problem this
    function exists to avoid. So the result is `max(n, len(stratified floor))` days: usually
    exactly `n`, occasionally a few more when a session has many distinct labels each needing
    their own floor. This is disclosed in the generated HTML's own header text."""
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
            chosen.update(pool[:MIN_PER_LABEL])
    remaining_pool = [td for td in days.index if td not in chosen]
    rng.shuffle(remaining_pool)
    while len(chosen) < n and remaining_pool:
        chosen.add(remaining_pool.pop())
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
            sessions_out.append(dict(id=sid, prefix=prefix, lo=lo, hi=hi, label=label))
        day_type = row.get("day_type")
        days_out.append(dict(
            td=td.strftime("%Y-%m-%d"), bars=bar_rows, sessions=sessions_out,
            day_type=(None if pd.isna(day_type) else str(day_type)),
        ))
    return dict(days=days_out, generated_for="EURUSD Session Research Lab -- ROADMAP 5.6")


_HTML_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Label validation -- ROADMAP 5.6</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;background:#0f1a2e;color:#e8ecf5;margin:0;padding:0 0 60px}
header{background:#0b1220;padding:14px 20px;border-bottom:2px solid #e8c77a;position:sticky;top:0;z-index:5}
h1{font-size:18px;margin:0}
.muted{color:#9aa6bd;font-size:13px}
.day{margin:18px auto;max-width:1060px;background:#16213a;border-radius:10px;padding:14px 18px;border:1px solid #263457}
.day h2{margin:0 0 6px;font-size:15px;color:#e8c77a}
canvas{width:100%;background:#0b1220;border-radius:6px;display:block}
.zoombar{margin:8px 0 4px;display:flex;flex-wrap:wrap;gap:6px}
.zoombtn{border:1px solid #3b4a70;background:#1c2a48;color:#e8ecf5;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px}
.zoombtn.active{background:#2f73d6;border-color:#2f73d6}
table{border-collapse:collapse;width:100%;margin-top:10px;font-size:13px}
th,td{padding:5px 8px;text-align:left;border-bottom:1px solid #263457}
th{color:#9aa6bd}
button.ans{border:1px solid #3b4a70;background:#1c2a48;color:#e8ecf5;border-radius:6px;padding:4px 12px;cursor:pointer;margin-right:4px;font-size:12px}
button.ans.sel-agree{background:#119469;border-color:#119469}
button.ans.sel-disagree{background:#c8354b;border-color:#c8354b}
#bar{position:sticky;bottom:0;background:#0b1220;padding:12px 20px;border-top:2px solid #e8c77a;text-align:center}
#bar button{background:#2f73d6;color:#fff;border:none;border-radius:6px;padding:10px 22px;font-size:14px;cursor:pointer}
#progress{margin-bottom:6px;font-size:13px;color:#9aa6bd}
input.note{width:96%;background:#0b1220;border:1px solid #263457;color:#e8ecf5;border-radius:4px;padding:4px 6px;font-size:12px;margin-top:4px}
details{max-width:1060px;margin:14px auto;background:#16213a;border:1px solid #263457;border-radius:10px;padding:10px 18px}
summary{cursor:pointer;color:#e8c77a;font-size:14px;font-weight:600}
details table{margin-top:10px}
.lbl{text-decoration:underline dotted #9aa6bd;cursor:help}
</style></head><body>
<header><h1>Session-character &amp; day-type label validation</h1>
<div class="muted">ROADMAP 5.6 -- for each label below: does it look right on the chart? Use the zoom buttons to
look closely at one session at a time, click Agree or Disagree for every row, then use "Download my answers"
at the bottom and send that file back. %%COUNT%% days. Hover any bold label for a plain-English definition,
or open "What do these labels mean?" below for the full list.</div></header>

<details>
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
<div id="bar"><div id="progress">0 / 0 answered</div><button onclick="downloadAnswers()">Download my answers</button></div>
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

function hourLabel(h){
  const c = ((h % 24) + 24) % 24;
  const hh = Math.floor(c);
  return String(hh).padStart(2, "0") + ":00";
}

function drawDay(day, idx){
  const wrap = document.createElement("div"); wrap.className = "day";
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
  const rows = day.sessions.map(s => ["session:" + s.id, s.label]);
  rows.push(["day_type", day.day_type]);
  rows.forEach(([key, val]) => {
    const tr = document.createElement("tr");
    const ansKey = day.td + "|" + key;
    const desc = LABEL_DESC[val] || "";
    tr.innerHTML = "<td>" + key + "</td><td><b class='lbl' title=\"" + desc.replace(/"/g, "&quot;") + "\">" +
      (val || "—") + "</b></td>" +
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
  if (!bars.length) { ctx.fillStyle = "#9aa6bd"; ctx.fillText("no bars in this window", 10, 20); return; }

  const W = canvas.width, H = canvas.height, padL = 55, padR = 12, padT = 30, padB = 26;
  const hi = Math.max(...bars.map(b => b[2])), lo = Math.min(...bars.map(b => b[3]));
  const span = (hi - lo) || 1e-6;
  const xOf = h => padL + (h - winLo) / (winHi - winLo || 1) * (W - padL - padR);
  const yOf = p => H - padB - (p - lo) / span * (H - padT - padB);

  // price gridlines (5 ticks)
  ctx.font = "11px sans-serif"; ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const p = lo + span * i / 4;
    const y = yOf(p);
    ctx.strokeStyle = "rgba(154,166,189,0.15)"; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillStyle = "#9aa6bd"; ctx.fillText(p.toFixed(5), padL - 6, y + 3);
  }
  // hour gridlines: every hour if zoomed (span<=6h), else every 2h
  const hourStep = (winHi - winLo) <= 7 ? 1 : 2;
  ctx.textAlign = "center";
  for (let h = Math.ceil(winLo / hourStep) * hourStep; h <= winHi; h += hourStep) {
    const x = xOf(h);
    ctx.strokeStyle = "rgba(154,166,189,0.12)"; ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke();
    ctx.fillStyle = "#9aa6bd"; ctx.fillText(hourLabel(h), x, H - 8);
  }
  // range annotation (pips, assuming EURUSD pip = 0.0001)
  ctx.textAlign = "left"; ctx.fillStyle = "#9aa6bd";
  ctx.fillText("range shown: " + ((hi - lo) / 0.0001).toFixed(1) + " pips", padL, 14);

  // session shading + labels (only the ones overlapping this window)
  day.sessions.forEach(s => {
    if (s.hi < winLo || s.lo > winHi) return;
    const x0 = xOf(Math.max(s.lo, winLo)), x1 = xOf(Math.min(s.hi, winHi));
    ctx.fillStyle = "rgba(232,199,122,0.06)"; ctx.fillRect(x0, padT, x1 - x0, H - padT - padB);
    ctx.strokeStyle = "rgba(232,199,122,0.35)"; ctx.beginPath(); ctx.moveTo(x0, padT); ctx.lineTo(x0, H - padB); ctx.stroke();
    ctx.fillStyle = "#e8c77a"; ctx.textAlign = "left"; ctx.font = "11px sans-serif";
    ctx.fillText(s.id + ": " + (s.label || "?"), x0 + 3, padT + 13);
  });

  // candles
  const bw = Math.max(2, (W - padL - padR) / bars.length * 0.7);
  bars.forEach(([h, o, hh, l, c]) => {
    const x = xOf(h);
    ctx.strokeStyle = c >= o ? "#119469" : "#c8354b";
    ctx.beginPath(); ctx.moveTo(x, yOf(hh)); ctx.lineTo(x, yOf(l)); ctx.stroke();
    ctx.fillStyle = c >= o ? "#119469" : "#c8354b";
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


def build(cache_dir: str, sessions_cfg: dict, n: int = 30, seed: int = 42):
    from nylab import cache as cache_mod
    bars, days = cache_mod.load(cache_dir)
    missing = [f"{_PREFIX[sid]}_character" for sid in SESSIONS_TO_VALIDATE
               if f"{_PREFIX[sid]}_character" not in days.columns]
    if missing or "day_type" not in days.columns:
        raise SystemExit(
            "The cached day table doesn't have session/day-type columns yet "
            f"(missing: {missing or ['day_type']}). Run `python -m nylab run <csv>` first "
            "(without --no-cache) so the Phase 5 session attach runs before caching.")
    tds = sample_days(days, n=n, seed=seed)
    payload = build_payload(bars, days, sessions_cfg, tds)
    html = render_html(payload)
    return html, payload
