// EURUSD Session Research Lab -- replay trainer frontend.
// No-leak discipline: this file NEVER asks the server for anything past the currently
// revealed timestamp. Stepping forward means "reveal one more 5-minute bar" -- the next
// bar's TIME is known (fixed grid), its PRICE is not, until the server sends it.

// ---------------------------------------------------------------- theme colors (single source
// of truth: style.css's :root / :root[data-theme="dark"] custom properties. DESIGN_SYSTEM.md S1
// flagged chart colors as hardcoded THREE times (style.css vars, initChart(), applyTheme()) --
// every color below is read live from the CSS, so a palette change only ever happens in one file.
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function currentTheme() {
  return (typeof window.__currentTheme === "function") ? window.__currentTheme() : "dark";
}
// Session-box fills (S3: "reuse the theme's own accent/amber/bull/bear at low opacity ~6-8%
// per session" -- Asia/Lunch get a neutral text-3 tint since they aren't naturally one of those
// four hues). Rebuilt on every theme change, not hardcoded, so it always matches the live theme.
function sessionBoxes() {
  return [
    ["Asia", -4, 0, `rgba(${cssVar("--text-3-rgb")},.07)`],
    ["London KZ", 2, 5, `rgba(${cssVar("--accent-rgb")},.10)`],
    ["NY AM", 7, 12, `rgba(${cssVar("--bull-rgb")},.08)`],
    ["Lunch", 12, 13.5, `rgba(${cssVar("--text-3-rgb")},.07)`],
    ["NY PM", 13.5, 16, `rgba(${cssVar("--bear-rgb")},.07)`],
  ];
}
// Narrower sub-windows (killzones / silver bullets) -- point markers only, would overlap if shaded.
const SESSION_WINDOWS = [
  ["CBDR", -3], ["London SB", 3], ["NY AM KZ", 7], ["NY AM SB", 10], ["NY PM SB", 14],
];

const state = {
  allDays: [], filteredDays: [], currentIdx: -1, currentTd: null,
  tf: "M5", startAtH: 7, until: null, lastBarTime: null, dayEndH: 16,
  chart: null, series: null, markers: [],
  levels: {},
  pendingOrder: null, // {side, order_type: 'limit'|'stop', entry, sl, tp, riskPct}
  position: null,     // {side, entry, sl, tp, lots, riskDollars, riskPct, openedAt}
  account: { starting: 5000, balance: 5000, dayStart: 5000, peak: 5000, program: null },
  playing: false, playTimer: null, lastClosedTrade: null, blind: false,
};

const $ = (sel) => document.querySelector(sel);
const fmtPrice = (x) => (x == null ? "—" : x.toFixed(5));

async function api(path, opts) {
  const res = await fetch(path, opts);
  const j = await res.json();
  if (!res.ok || j.error) throw new Error(j.error || `HTTP ${res.status}`);
  return j;
}
const getJSON = (path) => api(path);
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function computeR(side, entry, exitPrice, sl) {
  // Single implementation of the R-math, in nylab/replay/sim.py -- the client never
  // reimplements it, so a mock trade's R can never drift from the backtest engine's formula.
  return postJSON("/api/sim/compute_r", { side, entry, exit_price: exitPrice, sl, cost_pips: 1.0, pip: 0.0001 });
}

// ---------------------------------------------------------------- chart setup
function initChart() {
  const el = $("#chart");
  state.chart = LightweightCharts.createChart(el, {
    layout: { background: { color: "transparent" }, textColor: cssVar("--text-1") },
    grid: { vertLines: { color: cssVar("--glass-border-dim") }, horzLines: { color: cssVar("--glass-border-dim") } },
    timeScale: { timeVisible: true, secondsVisible: false },
    rightPriceScale: { borderColor: cssVar("--glass-border-dim") },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  state.series = state.chart.addCandlestickSeries({
    upColor: cssVar("--bull"), downColor: cssVar("--bear"), borderVisible: false,
    wickUpColor: cssVar("--bull"), wickDownColor: cssVar("--bear"),
  });
  new ResizeObserver(() => { state.chart.resize(el.clientWidth, el.clientHeight); applySessionBoxes(); }).observe(el);
  state.chart.timeScale().subscribeVisibleLogicalRangeChange(() => applySessionBoxes());
  initDragHandlers();
}

// `dark` is kept as the parameter name for the #darkToggle onchange contract (DESIGN_SYSTEM.md
// S2), but the theme itself lives on <html data-theme>, set by whoever calls this -- see the
// #darkToggle handler below and the inline boot script in index.html for the two callers.
function applyTheme(dark) {
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  if (typeof window.__safeSetTheme === "function") window.__safeSetTheme("eurusd-theme", dark ? "dark" : "light");
  state.chart.applyOptions({
    layout: { textColor: cssVar("--text-1") },
    grid: { vertLines: { color: cssVar("--glass-border-dim") }, horzLines: { color: cssVar("--glass-border-dim") } },
    rightPriceScale: { borderColor: cssVar("--glass-border-dim") },
  });
  state.series.applyOptions({
    upColor: cssVar("--bull"), downColor: cssVar("--bear"),
    wickUpColor: cssVar("--bull"), wickDownColor: cssVar("--bear"),
  });
  applySessionBoxes();
  drawLevelLines();
  drawPositionLines();
  applySessionMarkers();
}

// ---------------------------------------------------------------- day list / filters
// ROADMAP 6.1: every filter REPLAY_TRAINER.md S3 lists (session character, news, raids, ADR
// ratio, a free-text DSL expression) now actually reaches nylab.replay.api.list_days() -- this
// used to be date/weekday/exclude-thin plus two hardcoded London-raid checkboxes only.
function currentFilters() {
  const weekdays = [...document.querySelectorAll("#fWeekdays input:checked")].map((c) => c.value).join(",");
  const news = [...document.querySelectorAll(".fNews:checked")].map((c) => c.value);
  const raids = [...document.querySelectorAll(".fRaid:checked")].map((c) => c.value);
  const chars = {};
  document.querySelectorAll(".charSelect").forEach((sel) => {
    const vals = [...sel.selectedOptions].map((o) => o.value);
    if (vals.length) chars[sel.dataset.sid] = vals;
  });
  return {
    from: $("#fFrom").value || "", to: $("#fTo").value || "",
    weekdays, exclude_thin: $("#fExcludeThin").checked,
    hide_outcome: $("#fHideOutcome").checked,
    news, raids, chars,
    adr_min: $("#fAdrMin").value || "", adr_max: $("#fAdrMax").value || "",
    dsl: $("#fDsl").value || "",
  };
}

function filtersToQuery(f) {
  const qs = new URLSearchParams();
  if (f.from) qs.set("from", f.from);
  if (f.to) qs.set("to", f.to);
  if (f.weekdays) qs.set("weekdays", f.weekdays);
  qs.set("exclude_thin", f.exclude_thin ? "true" : "false");
  qs.set("hide_outcome", f.hide_outcome ? "true" : "false");
  if (f.news && f.news.length) qs.set("news", f.news.join(","));
  if (f.raids && f.raids.length) qs.set("raids", f.raids.join(","));
  Object.entries(f.chars || {}).forEach(([sid, vals]) => qs.set(`char_${sid}`, vals.join(",")));
  if (f.adr_min) qs.set("adr_min", f.adr_min);
  if (f.adr_max) qs.set("adr_max", f.adr_max);
  if (f.dsl) qs.set("dsl", f.dsl);
  return qs;
}

async function loadDayList() {
  const f = currentFilters();
  $("#fDslError").textContent = "";
  let payload;
  try {
    payload = await getJSON(`/api/days?${filtersToQuery(f)}`);
  } catch (e) {
    $("#fDslError").textContent = e.message || String(e);
    return; // keep showing the previous (last-valid) day list rather than blanking it
  }
  state.allDays = payload.days;
  state.filteredDays = payload.days;
  $("#matchCount").textContent = `(${payload.count} of ${payload.total_before_filters} days)`;
  $("#spoilerBadge").style.display = payload.spoiler_filter_used ? "" : "none";
  renderDayTable();
}

function renderDayTable() {
  const tbody = $("#dayTable tbody");
  tbody.innerHTML = "";
  const names = ["Mon", "Tue", "Wed", "Thu", "Fri"];
  const mask = "••••••";
  state.filteredDays.forEach((r) => {
    const tr = document.createElement("tr");
    // Blind mode (REPLAY_TRAINER.md S3) masks EVERYTHING, including the date, with the hatched
    // spoiler treatment -- it's the "don't let me recall a famous day" mode. Plain hide-outcome
    // (the default) just leaves the two outcome-revealing columns as an em-dash placeholder, no
    // hatch -- the row still looks like an ordinary row, it just has nothing to show yet.
    tr.className = "dayRow" + (r.date === state.currentTd ? " active" : "") + (state.blind ? " spoiler" : "");
    const o = r.outcome || {};
    const nyRng = r.outcome ? (o.ny_range_pips ?? "—") : "—";
    const lonRng = r.outcome ? (o.lon_range_pips ?? "—") : "—";
    const lonChar = r.outcome ? (o.lon_character ?? "—") : "—";
    const dayType = r.outcome ? (o.day_type ?? "—") : "—";
    tr.innerHTML = `<td data-label="Date">${state.blind ? mask : r.date}</td><td data-label="Day">${names[r.weekday] ?? ""}</td>` +
      `<td data-label="NY rng">${state.blind ? mask : nyRng}</td><td data-label="Lon rng">${state.blind ? mask : lonRng}</td>` +
      `<td data-label="Lon char">${state.blind ? mask : lonChar}</td><td data-label="Day type">${state.blind ? mask : dayType}</td>`;
    tr.onclick = () => loadDay(r.date);
    tbody.appendChild(tr);
  });
}

// ---------------------------------------------------------------- loading a day
function h_to_hhmm(h) {
  h = ((h % 24) + 24) % 24;
  const hh = Math.floor(h), mm = Math.round((h - hh) * 60);
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

async function loadDay(td) {
  state.currentTd = td;
  state.currentIdx = state.filteredDays.findIndex((r) => r.date === td);
  state.tf = $("#tf").value;
  state.startAtH = parseFloat($("#startAt").value);
  state.position = null;
  state.pendingOrder = null;
  updateTicketUI();
  $("#datePicker").value = td;

  // "until" = the wall-clock NY timestamp at the chosen start hour on this td.
  const untilLocal = tdPlusHours(td, state.startAtH);
  state.until = untilLocal;
  state.lastBarTime = null;

  await refreshBars();
  await refreshLevels();
  await refreshNews();
  renderDayTable();
  updateClockLabel();
  updateReviewButtonState();
  $("#reviewPanel").style.display = "none";
}

function tdPlusHours(tdStr, h) {
  const d = new Date(tdStr + "T00:00:00");
  d.setMinutes(d.getMinutes() + Math.round(h * 60));
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

async function refreshBars() {
  const qs = new URLSearchParams({ td: state.currentTd, tf: state.tf, until: state.until, context_days: 10 });
  const { bars } = await getJSON(`/api/bars?${qs}`);
  state.series.setData(bars);
  if (bars.length) {
    state.lastBarTime = bars[bars.length - 1].time;
    state.chart.timeScale().scrollToPosition(2, false);
  }
  applySessionMarkers();
  applySessionBoxes();
  if (state.pendingOrder || state.position) await checkFillsAgainstNewBars(bars);
  drawPositionLines();
}

async function refreshLevels() {
  const qs = new URLSearchParams({ td: state.currentTd, until: state.until });
  const { levels } = await getJSON(`/api/levels?${qs}`);
  state.levels = levels || {};
  drawLevelLines();
}

let priceLines = [];
function drawLevelLines() {
  priceLines.forEach((pl) => state.series.removePriceLine(pl));
  priceLines = [];
  const show = [
    ["lon_high", "London high", cssVar("--accent")], ["lon_low", "London low", cssVar("--accent")],
    ["asia_high", "Asia high", cssVar("--level-asia")], ["asia_low", "Asia low", cssVar("--level-asia")],
    ["pdh", "PDH", cssVar("--amber")], ["pdl", "PDL", cssVar("--amber")],
    ["pwh", "Prev week high", cssVar("--level-weekly")], ["pwl", "Prev week low", cssVar("--level-weekly")],
    ["mid_open", "Midnight open", cssVar("--text-3")], ["o0830", "08:30 open", cssVar("--text-3")], ["o0930", "09:30 open", cssVar("--text-3")],
  ];
  show.forEach(([key, label, color]) => {
    const v = state.levels[key];
    if (v == null || state.blind) return;
    priceLines.push(state.series.createPriceLine({ price: v, color, lineWidth: 1, lineStyle: 2, title: label }));
  });
}

// Shaded session boxes (Phase 2 gap-close: real translucent rectangles, not just markers).
// Positioned with absolutely-placed <div>s over the chart, re-derived from the chart's own
// timeScale on every redraw/pan/zoom -- purely a function of FIXED session-hour boundaries
// (SESSIONS_AND_CONTEXT.md's session table), never of revealed price data, so there is nothing
// to leak here: the boxes would be in the same place even on a day with zero bars revealed.
let sessionBoxEls = [];
function applySessionBoxes() {
  const chartEl = $("#chart");
  sessionBoxEls.forEach((el) => el.remove());
  sessionBoxEls = [];
  if (!state.currentTd || !state.chart) return;
  const ts = state.chart.timeScale();
  const untilEpoch = toEpoch(state.until);
  sessionBoxes().forEach(([name, lo, hi, color]) => {
    const t0 = toEpoch(tdPlusHours(state.currentTd, lo));
    const t1 = Math.min(toEpoch(tdPlusHours(state.currentTd, hi)), untilEpoch);
    if (t1 <= t0) return; // hasn't started yet at the current `until`
    const x0 = ts.timeToCoordinate(t0);
    const x1 = ts.timeToCoordinate(t1);
    if (x0 == null && x1 == null) return;
    const left = x0 == null ? 0 : x0;
    const right = x1 == null ? chartEl.clientWidth : x1;
    if (right <= left) return;
    const div = document.createElement("div");
    div.className = "sessionBox";
    div.title = name;
    div.style.left = `${left}px`;
    div.style.width = `${right - left}px`;
    div.style.background = color;
    chartEl.appendChild(div);
    sessionBoxEls.push(div);
  });
}

function applySessionMarkers() {
  const sessionMarkers = SESSION_WINDOWS.map(([name, lo]) => {
    const t = toEpoch(tdPlusHours(state.currentTd, lo)); // see toEpoch() -- must match server epoch convention
    return { time: t, position: "aboveBar", color: cssVar("--text-3"), shape: "circle", text: name };
  }).filter((m) => m.time <= toEpoch(state.until));
  // ROADMAP 6.5: news events share the same setMarkers() call (lightweight-charts v4 replaces
  // the whole marker set each time it's called, so one combined array, not two competing calls).
  // Only ever built from state.news, which itself only ever holds what /api/news already agreed
  // to reveal -- no separate no-leak check needed here.
  const newsMarkers = (state.news || []).map((e) => ({
    time: e.time, position: "belowBar", shape: "square",
    color: e.currency === "USD" ? cssVar("--accent") : cssVar("--amber"),
    text: e.released ? `${e.currency} ${e.family || e.event_name}` : `${e.currency} ${e.family || e.event_name} (scheduled)`,
  }));
  const markers = [...sessionMarkers, ...newsMarkers].sort((a, b) => a.time - b.time);
  try { state.series.setMarkers(markers); } catch (e) { /* time not in visible range yet */ }
}

// PRE-EXISTING BUG FIX (found via Phase 6 smoke testing, see docs/PROGRESS.md): the server builds
// every bar/level epoch by treating NY wall-clock time as if it were UTC (pandas' Timestamp.
// timestamp() does this for naive datetimes) -- it is a deliberate convention, not a mistake, used
// so lightweight-charts (which always renders in UTC) shows the NY wall-clock numbers directly.
// The old implementation here, `new Date(localIso).getTime()/1000`, instead converts using the
// BROWSER's real OS timezone, so it only agreed with the server's convention when the browser's
// OS timezone happened to be UTC+0. On any other timezone (confirmed: IST, UTC+5:30, matching
// both this dev sandbox and Akash's real machine) every comparison against a server-epoch value
// was off by the browser's UTC offset -- this silently miscalculated shaded session-box
// placement, the session marker/news marker x-positions, AND (more seriously) the same-bar-fill
// eligibility checks (`bar.time > toEpoch(placedAt/openedAt)`) that gate order fills. Parsing a
// Date and reading its components back with the LOCAL getters is a no-op round-trip regardless of
// timezone (whatever offset was applied on parse is undone on read), so reinterpreting those same
// wall-clock numbers with Date.UTC() reproduces the server's convention exactly, with no
// dependence on the browser's timezone at all.
function toEpoch(localIso) {
  const d = new Date(localIso);
  return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes(), d.getSeconds()) / 1000);
}

function updateClockLabel() {
  const t = new Date(state.until);
  const hh = String(t.getHours()).padStart(2, "0"), mm = String(t.getMinutes()).padStart(2, "0");
  $("#clockLabel").textContent = `${state.currentTd} ${hh}:${mm} NY`;
}

// ---------------------------------------------------------------- stepping / playback
function addMinutesToUntil(mins) {
  const d = new Date(state.until);
  d.setMinutes(d.getMinutes() + mins);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

async function stepBars(nBars) {
  const stepMinutes = { M5: 5, M15: 15, H1: 60, H4: 240, D1: 1440 }[state.tf] || 5;
  state.until = addMinutesToUntil(stepMinutes * nBars);
  await refreshBars();
  await refreshLevels();
  await refreshNews();
  updateClockLabel();
  updateReviewButtonState();
}

$("#stepFwd").onclick = () => stepBars(1);
$("#stepHour").onclick = () => stepBars(12); // 12 M5 bars = 1 hour, resample handles coarser TFs
// ROADMAP 8.1: factored out of the #jumpBtn click handler so the deep-link boot code (see
// init() below) can reuse the exact same "jump to HH:MM on the currently loaded day" logic
// instead of a second copy of this date-arithmetic.
// Audit fix 2026-09-28: a trading day runs 17:00 -> 17:00 NY, so a time at/after 17:00 means
// the EVENING BEFORE the trading day's date (Asia / CBDR), i.e. h = HH:MM - 24. Previously
// 20:00 was placed on the trading day's own date, i.e. after the day had already ended.
function jumpToTime(hhmm) {
  if (!hhmm) return;
  const [hh, mm] = hhmm.split(":").map(Number);
  let h = hh + mm / 60;
  if (h >= 17) h -= 24;
  state.until = tdPlusHours(state.currentTd, h);
  return Promise.all([refreshBars(), refreshLevels(), refreshNews()]).then(() => {
    updateClockLabel(); updateReviewButtonState();
  });
}
$("#jumpBtn").onclick = () => jumpToTime($("#jumpTime").value);

$("#playPause").onclick = () => {
  state.playing = !state.playing;
  $("#playPause").textContent = state.playing ? "⏸ pause" : "▶ play";
  if (state.playing) playLoop(); else clearTimeout(state.playTimer);
};
function playLoop() {
  if (!state.playing) return;
  stepBars(1).then(() => {
    const h = new Date(state.until).getHours() + new Date(state.until).getMinutes() / 60;
    if (h >= state.dayEndH || h < 1) { state.playing = false; $("#playPause").textContent = "▶ play"; return; }
    state.playTimer = setTimeout(playLoop, parseInt($("#speed").value, 10));
  });
}

$("#prevDay").onclick = () => { if (state.currentIdx > 0) loadDay(state.filteredDays[state.currentIdx - 1].date); };
$("#nextDay").onclick = () => { if (state.currentIdx < state.filteredDays.length - 1) loadDay(state.filteredDays[state.currentIdx + 1].date); };
$("#randomDay").onclick = () => { if (state.filteredDays.length) loadDay(state.filteredDays[Math.floor(Math.random() * state.filteredDays.length)].date); };
$("#datePicker").onchange = (e) => { if (e.target.value) loadDay(e.target.value); };
$("#tf").onchange = () => { state.tf = $("#tf").value; refreshBars(); };
$("#blindMode").onchange = (e) => {
  state.blind = e.target.checked;
  // Blind mode implies hide-outcome (there is no point hiding the date but showing the day's
  // character/range next to it) -- force the checkbox and grey it out while blind mode is on.
  if (state.blind) { $("#fHideOutcome").checked = true; $("#fHideOutcome").disabled = true; }
  else { $("#fHideOutcome").disabled = false; }
  loadDayList();
  renderDayTable();
  drawLevelLines();
};
$("#darkToggle").onchange = (e) => applyTheme(e.target.checked);

document.querySelectorAll("#fWeekdays input, #fExcludeThin, #fHideOutcome, .fNews, .fRaid, .charSelect")
  .forEach((el) => el.addEventListener("change", loadDayList));
$("#fFrom").onchange = loadDayList;
$("#fTo").onchange = loadDayList;
$("#fAdrMin").onchange = loadDayList;
$("#fAdrMax").onchange = loadDayList;
$("#fDslApply").onclick = loadDayList;
$("#fDsl").addEventListener("keydown", (e) => { if (e.key === "Enter") loadDayList(); });

// ---------------------------------------------------------------- trading + account
$("#orderType").onchange = () => {
  $("#entryRow").style.display = $("#orderType").value === "market" ? "none" : "";
};

function updateTicketUI() {
  const hasPending = !!state.pendingOrder, hasPosition = !!state.position;
  $("#openTradeBtn").disabled = hasPending || hasPosition;
  $("#cancelPendingBtn").disabled = !hasPending;
  $("#closeTradeBtn").disabled = !hasPosition;
  $("#partialCloseBtn").disabled = !hasPosition;
  $("#moveBEBtn").disabled = !hasPosition || state.position.sl === state.position.entry;
  $("#saveJournalBtn").disabled = !state.lastClosedTrade;
  $("#pendingInfo").textContent = hasPending
    ? `Pending: ${state.pendingOrder.side.toUpperCase()} ${state.pendingOrder.order_type.toUpperCase()} @ ${fmtPrice(state.pendingOrder.entry)} SL ${fmtPrice(state.pendingOrder.sl)} TP ${fmtPrice(state.pendingOrder.tp)}`
    : "";
  $("#openTradeInfo").textContent = hasPosition
    ? `Open: ${state.position.side.toUpperCase()} @ ${fmtPrice(state.position.entry)} SL ${fmtPrice(state.position.sl)} TP ${fmtPrice(state.position.tp)} lots ${state.position.lots}` +
      (state.position.partialClosedFrac ? ` (${Math.round(state.position.partialClosedFrac * 100)}% partially closed)` : "")
    : "";
}

async function refreshLotsPreview() {
  const sl = parseFloat($("#slInput").value), riskPct = parseFloat($("#riskPct").value);
  const refPrice = $("#orderType").value === "market"
    ? state.series.data().slice(-1)[0]?.close
    : parseFloat($("#entryInput").value);
  if (!sl || !refPrice || !riskPct) { $("#lotsPreview").textContent = ""; return; }
  const slPips = Math.abs(refPrice - sl) / 0.0001;
  const { lots } = await postJSON("/api/sim/lots", { balance: state.account.balance, risk_pct: riskPct, sl_distance_pips: slPips });
  $("#lotsPreview").textContent = `${lots} lots (SL ${slPips.toFixed(1)} pips)`;
}
["slInput", "riskPct", "entryInput"].forEach((id) => $(`#${id}`).addEventListener("input", refreshLotsPreview));

async function openPosition(side, entry, sl, tp, riskPct) {
  const { lots } = await postJSON("/api/sim/lots", {
    balance: state.account.balance, risk_pct: riskPct, sl_distance_pips: Math.abs(entry - sl) / 0.0001,
  });
  state.position = {
    side, entry, sl, tp, lots, originalLots: lots, riskPct,
    riskDollars: state.account.balance * (riskPct / 100), // fixed at open so later partial closes are exact
    partialClosedFrac: 0, openedAt: state.until,
  };
}

$("#openTradeBtn").onclick = async () => {
  const lastBar = state.series.data().slice(-1)[0];
  if (!lastBar) return alert("No bar revealed yet.");
  const side = $("#side").value;
  const orderType = $("#orderType").value;
  const sl = parseFloat($("#slInput").value), tp = parseFloat($("#tpInput").value) || null;
  const riskPct = parseFloat($("#riskPct").value);
  if (!sl) return alert("Set a stop loss first.");

  if (orderType === "market") {
    const entry = lastBar.close; // filled at the close of the last revealed bar (conservative, no peeking)
    await openPosition(side, entry, sl, tp, riskPct);
  } else {
    const entry = parseFloat($("#entryInput").value);
    if (!entry) return alert("Set an entry price for a limit/stop order.");
    state.pendingOrder = { side, order_type: orderType, entry, sl, tp, riskPct, placedAt: state.until };
  }
  updateTicketUI();
  drawPositionLines();
};

$("#cancelPendingBtn").onclick = () => { state.pendingOrder = null; updateTicketUI(); drawPositionLines(); };

$("#closeTradeBtn").onclick = () => {
  const lastBar = state.series.data().slice(-1)[0];
  finishTrade(lastBar.close, "manual");
};

$("#moveBEBtn").onclick = () => {
  if (!state.position) return;
  state.position.sl = state.position.entry;
  $("#slInput").value = state.position.entry.toFixed(5);
  updateTicketUI();
  drawPositionLines();
};

$("#partialCloseBtn").onclick = async () => {
  if (!state.position) return;
  const lastBar = state.series.data().slice(-1)[0];
  const pos = state.position;
  const closeFrac = 0.5 * (1 - pos.partialClosedFrac); // "50%" means half of what's still open
  const r = await computeR(pos.side, pos.entry, lastBar.close, pos.sl);
  state.account.balance += r.R_net * pos.riskDollars * closeFrac; // dollars at risk on the closed slice only
  pos.partialClosedFrac += closeFrac;
  pos.lots = Math.round(pos.originalLots * (1 - pos.partialClosedFrac) * 100) / 100;
  updateTicketUI();
  await refreshAccountPanel();
};

async function checkFillsAgainstNewBars(newBars) {
  for (const bar of newBars) {
    if (state.pendingOrder && bar.time > toEpoch(state.pendingOrder.placedAt)) {
      const { filled, entry } = await postJSON("/api/sim/pending_fill_check", { order: state.pendingOrder, bar });
      if (filled) {
        const p = state.pendingOrder;
        await openPosition(p.side, entry, p.sl, p.tp, p.riskPct);
        state.pendingOrder = null;
        updateTicketUI();
      }
    }
    if (state.position && bar.time > toEpoch(state.position.openedAt)) {
      const { filled, reason, exit } = await postJSON("/api/sim/fill_check", { position: state.position, bar });
      if (filled) { await finishTrade(exit, reason); break; }
    }
  }
}

async function finishTrade(exitPrice, reason) {
  if (!state.position) return;
  const pos = state.position;
  const r = await computeR(pos.side, pos.entry, exitPrice, pos.sl);
  const remainingFrac = 1 - pos.partialClosedFrac;
  state.account.balance += r.R_net * pos.riskDollars * remainingFrac;
  state.lastClosedTrade = { ...pos, exit: exitPrice, reason, ...r, td: state.currentTd };
  state.position = null;
  updateTicketUI();
  drawPositionLines();
  await refreshAccountPanel();
  if (state.challengeState) await checkChallengeBreach();
}

async function refreshAccountPanel() {
  if (!state.account.program) {
    const prop = await getJSON("/api/prop");
    state.account.program = prop.programs[prop.default_program];
  }
  state.account.peak = Math.max(state.account.peak, state.account.balance);
  const s = await postJSON("/api/sim/maven_state", {
    starting_balance: state.account.starting, current_balance: state.account.balance,
    day_start_balance: state.account.dayStart, peak_balance: state.account.peak,
    program: state.account.program,
  });
  $("#acctSummary").innerHTML = `
    <div class="row"><span>Balance</span><b class="tabular">$${s.balance.toFixed(2)}</b></div>
    <div class="row"><span>Day P&amp;L</span><span class="tabular">${s.day_pnl_pct.toFixed(2)}%</span></div>
    <div class="row"><span>Daily DD used <button type="button" class="info-icon" data-tip="How much of today's allowed loss you've used. Resets every trading day. Hitting 100% ends today's trading on a real Maven account.">i</button></span><span class="badge ${s.day_dd_status} tabular">${s.day_dd_used_pct.toFixed(2)}% / ${s.day_dd_limit_pct}%</span></div>
    <div class="row"><span>Max DD used <button type="button" class="info-icon" data-tip="How much of your total allowed drawdown (from the account's peak balance) you've used. Hitting 100% ends the whole account on a real Maven account.">i</button></span><span class="badge ${s.max_dd_status} tabular">${s.max_dd_used_pct.toFixed(2)}% / ${s.max_dd_limit_pct}%</span></div>
    ${s.day_dd_breached || s.max_dd_breached ? `<div class="breach"><svg viewBox="0 0 24 24"><path d="M12 3 1 21h22L12 3z"/><line x1="12" y1="9" x2="12" y2="14"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>BREACHED</div>` : ""}
  `;
}

// ---------------------------------------------------------------- SL/TP chart lines + drag
// (Phase 2 gap-close: "drag SL/TP" -- lightweight-charts v4 has no built-in draggable price
// line, so this hit-tests the mouse against each line's own y-coordinate and repositions it
// by hand. Bounded to the currently open position; dragging never touches historical bars.)
let entryLine = null, slLine = null, tpLine = null, pendingLine = null;

function drawPositionLines() {
  [entryLine, slLine, tpLine, pendingLine].forEach((pl) => { if (pl) state.series.removePriceLine(pl); });
  entryLine = slLine = tpLine = pendingLine = null;

  if (state.pendingOrder) {
    pendingLine = state.series.createPriceLine({
      price: state.pendingOrder.entry, color: cssVar("--amber"), lineWidth: 1, lineStyle: 3,
      title: `PENDING ${state.pendingOrder.side.toUpperCase()}`, axisLabelVisible: true,
    });
  }
  if (!state.position) return;
  const pos = state.position;
  entryLine = state.series.createPriceLine({ price: pos.entry, color: cssVar("--text-3"), lineWidth: 1, lineStyle: 0, title: "Entry", axisLabelVisible: true });
  slLine = state.series.createPriceLine({ price: pos.sl, color: cssVar("--bear"), lineWidth: 2, lineStyle: 2, title: "SL (drag)", axisLabelVisible: true });
  if (pos.tp != null) tpLine = state.series.createPriceLine({ price: pos.tp, color: cssVar("--bull"), lineWidth: 2, lineStyle: 2, title: "TP (drag)", axisLabelVisible: true });
}

function initDragHandlers() {
  const chartEl = $("#chart");
  let dragTarget = null; // "sl" | "tp" | null

  const hitTest = (y) => {
    if (!state.position) return null;
    const slY = state.series.priceToCoordinate(state.position.sl);
    if (slY != null && Math.abs(y - slY) < 6) return "sl";
    if (state.position.tp != null) {
      const tpY = state.series.priceToCoordinate(state.position.tp);
      if (tpY != null && Math.abs(y - tpY) < 6) return "tp";
    }
    return null;
  };

  chartEl.addEventListener("mousedown", (e) => {
    const rect = chartEl.getBoundingClientRect();
    dragTarget = hitTest(e.clientY - rect.top);
    if (dragTarget) chartEl.classList.add("dragging-line");
  });
  window.addEventListener("mousemove", (e) => {
    const rect = chartEl.getBoundingClientRect();
    const y = e.clientY - rect.top;
    if (!dragTarget) {
      chartEl.style.cursor = hitTest(y) ? "ns-resize" : "";
      return;
    }
    const price = state.series.coordinateToPrice(y);
    if (price == null || !state.position) return;
    state.position[dragTarget] = Math.round(price * 100000) / 100000;
    if (dragTarget === "sl") $("#slInput").value = state.position.sl.toFixed(5);
    else $("#tpInput").value = state.position.tp.toFixed(5);
    drawPositionLines();
    updateTicketUI();
  });
  window.addEventListener("mouseup", () => {
    dragTarget = null;
    chartEl.classList.remove("dragging-line");
  });
}

// ---------------------------------------------------------------- journal + screenshot
$("#saveJournalBtn").onclick = async () => {
  const t = state.lastClosedTrade;
  if (!t) return;
  await postJSON("/api/journal/append", {
    td: t.td, side: t.side, entry: t.entry, sl: t.sl, tp: t.tp, exit: t.exit, reason: t.reason,
    risk_pips: t.risk_pips, R_gross: t.R_gross, R_net: t.R_net,
    setup_tag: $("#setupTag").value, rules_followed: $("#rulesFollowed").value,
    emotion: $("#emotion").value, notes: $("#notes").value,
    preset: state.currentPresetName || "", challenge: state.challengeState ? "yes" : "",
  });
  try {
    const canvas = state.chart.takeScreenshot();
    const png = canvas.toDataURL("image/png");
    await postJSON("/api/journal/screenshot", { png_base64: png, filename: `${t.td}_${Date.now()}.png` });
  } catch (e) { /* screenshot best-effort; journal row is already saved */ }
  state.lastClosedTrade = null;
  updateTicketUI();
  alert("Saved to research/replay/trades.csv");
};

// ---------------------------------------------------------------- presets (ROADMAP 6.3)
// Saves the FULL current filter state -- every field currentFilters() returns -- not just the
// two original date/raid fields, so a preset genuinely reproduces "exactly these days" later.
state.currentPresetName = null;

async function loadPresetList() {
  const presets = await getJSON("/api/presets");
  state.presets = presets;
  const sel = $("#presetSelect");
  const prevValue = sel.value;
  sel.innerHTML = '<option value="">-- load preset --</option>';
  presets.forEach((p) => sel.insertAdjacentHTML("beforeend", `<option value="${p.name}">${p.name}</option>`));
  sel.value = prevValue;
  sel.onchange = () => applyPreset(sel.value);
}

function applyPreset(name) {
  const p = (state.presets || []).find((x) => x.name === name);
  state.currentPresetName = name || null;
  if (!p) return;
  $("#fFrom").value = p.from || "";
  $("#fTo").value = p.to || "";
  document.querySelectorAll("#fWeekdays input").forEach((c) => { c.checked = !p.weekdays || p.weekdays.includes(c.value); });
  $("#fExcludeThin").checked = p.exclude_thin !== false;
  $("#fHideOutcome").checked = p.hide_outcome !== false;
  document.querySelectorAll(".fNews").forEach((c) => { c.checked = (p.news || []).includes(c.value); });
  document.querySelectorAll(".fRaid").forEach((c) => { c.checked = (p.raids || []).includes(c.value); });
  document.querySelectorAll(".charSelect").forEach((sel) => {
    const wanted = (p.chars || {})[sel.dataset.sid] || [];
    [...sel.options].forEach((o) => { o.selected = wanted.includes(o.value); });
  });
  $("#fAdrMin").value = p.adr_min || "";
  $("#fAdrMax").value = p.adr_max || "";
  $("#fDsl").value = p.dsl || "";
  loadDayList();
}

$("#savePreset").onclick = async () => {
  const name = prompt("Preset name:", state.currentPresetName || "");
  if (!name) return;
  const f = currentFilters();
  await postJSON("/api/presets", { name, ...f });
  state.currentPresetName = name;
  await loadPresetList();
  $("#presetSelect").value = name;
};
$("#deletePreset").onclick = async () => {
  const name = $("#presetSelect").value;
  if (!name || !confirm(`Delete preset "${name}"?`)) return;
  await postJSON("/api/presets/delete", { name });
  state.currentPresetName = null;
  await loadPresetList();
};

// ---------------------------------------------------------------- responsive: drawers + sheet
// (DESIGN_SYSTEM.md S8: nav/account become slide-in drawers below 1440px, and on phones (<600px)
// both fold into a single bottom sheet the user switches between with the tabs above #layout.
// Pure UI state -- opening/closing never re-fetches or changes what data is shown.)
const overlay = $("#overlayDim");
function closeDrawers() {
  $("#navigator").classList.remove("open");
  $("#accountPanel").classList.remove("open");
  overlay.classList.remove("on");
}
$("#navToggle").onclick = () => {
  const willOpen = !$("#navigator").classList.contains("open");
  closeDrawers();
  if (willOpen) { $("#navigator").classList.add("open"); overlay.classList.add("on"); }
};
$("#acctToggle").onclick = () => {
  const willOpen = !$("#accountPanel").classList.contains("open");
  closeDrawers();
  if (willOpen) { $("#accountPanel").classList.add("open"); overlay.classList.add("on"); }
};
overlay.onclick = closeDrawers;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawers(); });

// Phone-only bottom sheet: #navigator and #accountPanel share the same fixed-bottom slot
// (style.css, <600px only) and this just picks which one is visible -- both keep their full,
// un-duplicated markup and event listeners, nothing here re-implements them.
function showSheetTab(which) {
  $("#tabDays").classList.toggle("active", which === "days");
  $("#tabAccount").classList.toggle("active", which === "account");
  $("#navigator").classList.toggle("sheetActive", which === "days");
  $("#accountPanel").classList.toggle("sheetActive", which === "account");
}
$("#tabDays").onclick = () => showSheetTab("days");
$("#tabAccount").onclick = () => showSheetTab("account");
showSheetTab("days");

// Generic tap-accessible info tooltip (DESIGN_SYSTEM.md S9: "not hover-only"). One shared
// floating element, positioned next to whichever .info-icon was tapped; event-delegated so it
// works for icons added dynamically (e.g. refreshAccountPanel's DD-used rows) with no extra wiring.
const tooltipEl = document.createElement("div");
tooltipEl.className = "tooltip-pop elev-raised";
document.body.appendChild(tooltipEl);
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".info-icon");
  if (!btn) { tooltipEl.classList.remove("open"); return; }
  e.stopPropagation();
  const r = btn.getBoundingClientRect();
  tooltipEl.textContent = btn.dataset.tip || "";
  tooltipEl.classList.add("open");
  const top = r.bottom + 8;
  let left = r.left;
  const maxLeft = window.innerWidth - 248;
  if (left > maxLeft) left = Math.max(8, maxLeft);
  tooltipEl.style.top = `${top}px`;
  tooltipEl.style.left = `${left}px`;
});

// ---------------------------------------------------------------- ROADMAP 6.4 review mode
// "End-of-day -> Review mode: full day revealed + the lab's computed events... overlaid so he
// can compare what he saw vs what the rules detected" (REPLAY_TRAINER.md S5). This is NOT a
// separate code path: it calls the SAME /api/levels no-leak endpoint the live chart already
// uses, just with `until` pushed to day-close (h=17, when day_range/day_type finally resolve),
// so it can never show more than a normal API call at that same `until` would.
function currentHourOfDay() {
  if (!state.currentTd) return -99;
  const tdMid = new Date(state.currentTd + "T00:00:00").getTime();
  return (new Date(state.until).getTime() - tdMid) / 3600000;
}
function updateReviewButtonState() {
  $("#reviewBtn").disabled = currentHourOfDay() < 17;
}
$("#reviewBtn").onclick = async () => {
  const endOfDay = tdPlusHours(state.currentTd, 17);
  const { levels } = await getJSON(`/api/levels?${new URLSearchParams({ td: state.currentTd, until: endOfDay })}`);
  const rows = [
    ["Day type", levels.day_type], ["Day range (pips)", levels.day_range],
    ["London character", levels.lon_character], ["Asia character", levels.asia_character],
    ["NY AM KZ character", levels.nyam_kz_character], ["NY PM character", levels.nypm_character],
    ["NY took London high", levels.ny_takes_lon_high], ["NY took London low", levels.ny_takes_lon_low],
    ["NY took PDH", levels.ny_takes_pdh], ["NY took PDL", levels.ny_takes_pdl],
    ["NY formed the day's high", levels.ny_forms_day_high], ["NY formed the day's low", levels.ny_forms_day_low],
  ].filter(([, v]) => v !== undefined && v !== null);
  $("#reviewPanel").innerHTML = `<button class="press closeBtn" id="reviewClose">close</button>` +
    `<h4>What the rules detected -- ${state.currentTd}</h4>` +
    `<table>${rows.map(([k, v]) => `<tr><td>${k}</td><td><b>${typeof v === "boolean" ? (v ? "yes" : "no") : v}</b></td></tr>`).join("")}</table>` +
    `<p class="muted">Compare this against what YOU thought was happening while stepping through the day above.</p>`;
  $("#reviewPanel").style.display = "block";
  $("#reviewClose").onclick = () => { $("#reviewPanel").style.display = "none"; };
};

// ---------------------------------------------------------------- ROADMAP 6.5 news markers
// Scheduled events show as soon as the day loads (the calendar is known in advance); actual/
// surprise are withheld by the SERVER (nylab.replay.api.get_news), not just hidden in the UI,
// until release time <= `until` -- same no-leak rule as bars/levels.
async function refreshNews() {
  if (!state.currentTd) return;
  let news = [];
  try {
    const r = await getJSON(`/api/news?${new URLSearchParams({ td: state.currentTd, until: state.until })}`);
    news = r.news || [];
  } catch (e) { /* calendar not attached -- leave the strip empty, not an error to the user */ }
  state.news = news;
  renderNewsStrip();
  applyNewsMarkers();
}
function renderNewsStrip() {
  const strip = $("#newsStrip");
  if (!state.news || !state.news.length) { strip.innerHTML = ""; return; }
  strip.innerHTML = state.news.map((e) => {
    // NY-clock display MUST come from the server's h (hours since td midnight, NY time) via
    // h_to_hhmm -- never from `new Date(e.time*1000).getHours()`, which reads the epoch back
    // in the BROWSER's local timezone and silently shows the wrong clock time whenever the
    // browser's OS timezone isn't UTC+0 (discovered via real-browser smoke testing: an 08:30 NY
    // NFP release showed as "14:00" under IST). `e.time` (the raw epoch) is kept in the payload
    // only for chart marker placement, which lightweight-charts consumes as UTC seconds and is
    // unaffected by browser-local timezone.
    const hhmm = h_to_hhmm(e.h);
    if (!e.released) return `<span class="newsChip pending">${hhmm} ${e.currency} ${e.event_name}</span>`;
    const cls = e.surprise > 0 ? "surprise-up" : e.surprise < 0 ? "surprise-down" : "";
    return `<span class="newsChip ${cls}" title="forecast ${e.forecast ?? '—'}, previous ${e.previous ?? '—'}">` +
           `${hhmm} ${e.currency} ${e.event_name}: ${e.actual ?? '—'}</span>`;
  }).join("");
}
// News markers share ONE setMarkers() call with the session-window markers below (lightweight-
// charts v4 replaces the whole marker set on every call) -- applySessionMarkers() is the
// combined renderer now; keep this name for the news-only half so refreshNews() can call it
// without needing to know about session windows.
function applyNewsMarkers() { applySessionMarkers(); }

// ---------------------------------------------------------------- ROADMAP 6.6 challenge mode
// Plays a sequence of the CURRENTLY FILTERED days in chronological order with the account
// balance carried over, enforcing the active Maven program's daily/max drawdown limits (the
// same sim.maven_state() the free-practice account panel already uses) until the profit target
// is hit (pass), a limit is breached (fail), or the filtered day queue runs out (incomplete).
// Deliberately single-step only (disclosed simplification, docs/PROGRESS.md): a real Maven
// 2-step program's step-2 re-entry isn't modeled here.
state.challengeState = null;
$("#startChallenge").onclick = () => {
  if (!state.filteredDays.length) { alert("No days match the current filters."); return; }
  const queue = [...state.filteredDays].map((r) => r.date).sort();
  state.challengeState = {
    queue, idx: 0,
    startingBalance: state.account.starting,
    target: state.account.program
      ? state.account.starting * (1 + (state.account.program.profit_targets_pct?.[0] || 8) / 100)
      : state.account.starting * 1.08,
    outcome: null,
  };
  state.account.balance = state.account.starting;
  state.account.peak = state.account.starting;
  state.account.dayStart = state.account.starting;
  $("#challengeBanner").style.display = "flex";
  loadDay(queue[0]);
  updateChallengeBanner();
};
$("#challengeStop").onclick = () => { state.challengeState = null; $("#challengeBanner").style.display = "none"; };
$("#challengeNextDay").onclick = async () => {
  const c = state.challengeState;
  if (!c) return;
  await refreshAccountPanel(); // settle any breach state before evaluating
  c.idx += 1;
  state.account.dayStart = state.account.balance; // ROADMAP 6.6: daily DD resets each new challenge day
  if (state.account.balance >= c.target) { c.outcome = "pass"; }
  else if (c.idx >= c.queue.length) { c.outcome = "incomplete"; }
  if (c.outcome) { finishChallenge(); return; }
  await loadDay(c.queue[c.idx]);
  updateChallengeBanner();
};
async function checkChallengeBreach() {
  const c = state.challengeState;
  if (!c || c.outcome) return;
  const s = await postJSON("/api/sim/maven_state", {
    starting_balance: state.account.starting, current_balance: state.account.balance,
    day_start_balance: state.account.dayStart, peak_balance: state.account.peak,
    program: state.account.program,
  });
  if (s.day_dd_breached || s.max_dd_breached) { c.outcome = "fail"; finishChallenge(); }
}
function updateChallengeBanner() {
  const c = state.challengeState;
  if (!c) return;
  $("#challengeStatus").textContent =
    `Challenge: day ${c.idx + 1} of ${c.queue.length} -- balance $${state.account.balance.toFixed(2)} -- target $${c.target.toFixed(2)}`;
}
function finishChallenge() {
  const c = state.challengeState;
  $("#challengeBanner").style.display = "none";
  const verdictText = { pass: "PASSED", fail: "FAILED (a drawdown limit was breached)", incomplete: "ran out of filtered days (incomplete)" }[c.outcome];
  alert(`Challenge ${verdictText}.\nDays played: ${c.idx + 1}\nFinal balance: $${state.account.balance.toFixed(2)}`);
  state.challengeState = null;
}

// ---------------------------------------------------------------- ROADMAP 6.7 stats tab
// Fetches the SAME aggregate stats nylab.replay.journal_stats.build() computes with
// nylab.stats.r_stats() -- one implementation of expectancy/win-rate math, not a second one here.
async function openStatsPanel() {
  $("#statsPanel").classList.add("open");
  $("#statsBody").textContent = "Loading...";
  try {
    const s = await getJSON("/api/journal/stats");
    const fmtPct = (x) => x == null ? "—" : (x * 100).toFixed(1) + "%";
    const fmtNum = (x) => x == null ? "—" : x.toFixed(2);
    const groupTable = (title, rows) => rows.length
      ? `<h4>${title}</h4><table><tr><th>Group</th><th>n</th><th>Win%</th><th>Exp (R)</th></tr>` +
        rows.map((r) => `<tr><td>${r.group}</td><td>${r.n}</td><td>${fmtPct(r.win_rate)}</td><td>${fmtNum(r.expectancy)}</td></tr>`).join("") +
        `</table>` : "";
    $("#statsBody").innerHTML =
      `<h4>Overall (${s.n_trades} trades)</h4>` +
      `<table><tr><td>Win rate</td><td><b>${fmtPct(s.overall.win_rate)}</b></td></tr>` +
      `<tr><td>Expectancy</td><td><b>${fmtNum(s.overall.expectancy)} R</b></td></tr>` +
      `<tr><td>Profit factor</td><td><b>${fmtNum(s.overall.profit_factor)}</b></td></tr></table>` +
      groupTable("By setup tag", s.by_setup_tag) + groupTable("By weekday", s.by_weekday) + groupTable("By preset", s.by_preset);
  } catch (e) {
    $("#statsBody").textContent = `Could not load stats: ${e.message || e}`;
  }
}
$("#statsToggle").onclick = openStatsPanel;
$("#statsClose").onclick = () => $("#statsPanel").classList.remove("open");

// ---------------------------------------------------------------- boot
(async function init() {
  // Sync the switch's initial position with whatever theme index.html's inline boot script
  // already applied to <html data-theme> (stored preference, or system default) -- the HTML
  // markup hardcodes checked="" as a sensible no-JS fallback only.
  $("#darkToggle").checked = currentTheme() === "dark";
  initChart();
  await loadDayList();
  await loadPresetList();
  await refreshAccountPanel();
  // ROADMAP 8.1 "open in replay" deep link: ?date=YYYY-MM-DD&until=HH:MM (nylab.report.deeplink
  // .replay_url() builds this exact URL from a trades DataFrame row). `date` need not be one of
  // state.filteredDays (a report's trade gallery can link to a day the current filter set
  // excludes) -- loadDay() fetches it directly from the API regardless of the filtered list.
  const deepLinkParams = new URLSearchParams(window.location.search);
  const deepDate = deepLinkParams.get("date");
  const deepUntil = deepLinkParams.get("until");
  if (deepDate) {
    // `date` is the CALENDAR date of the moment (nylab.report.deeplink.replay_url). A time at or
    // after 17:00 NY belongs to the NEXT trading day (audit fix 2026-09-28 -- before this, a
    // pre-midnight Asia-session trade opened the previous trading day instead).
    let deepTd = deepDate;
    if (deepUntil && Number(deepUntil.split(":")[0]) >= 17) {
      const nd = new Date(Date.UTC(...deepDate.split("-").map((x, i) => Number(x) - (i === 1 ? 1 : 0))) + 86400000);
      deepTd = nd.toISOString().slice(0, 10);
    }
    await loadDay(deepTd);
    if (deepUntil) await jumpToTime(deepUntil);
  } else if (state.filteredDays.length) {
    await loadDay(state.filteredDays[Math.floor(state.filteredDays.length / 2)].date);
  }
})();
