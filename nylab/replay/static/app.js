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
function currentFilters() {
  const weekdays = [...document.querySelectorAll("#fWeekdays input:checked")].map((c) => c.value).join(",");
  return {
    from: $("#fFrom").value || "", to: $("#fTo").value || "",
    weekdays, exclude_thin: $("#fExcludeThin").checked ? "true" : "false",
  };
}

async function loadDayList() {
  const f = currentFilters();
  const qs = new URLSearchParams();
  if (f.from) qs.set("from", f.from);
  if (f.to) qs.set("to", f.to);
  if (f.weekdays) qs.set("weekdays", f.weekdays);
  qs.set("exclude_thin", f.exclude_thin);
  const rows = await getJSON(`/api/days?${qs}`);

  let filtered = rows;
  if ($("#fLonHigh").checked) filtered = filtered.filter((r) => r.ny_takes_lon_high);
  if ($("#fLonLow").checked) filtered = filtered.filter((r) => r.ny_takes_lon_low);

  state.allDays = rows;
  state.filteredDays = filtered;
  $("#matchCount").textContent = `(${filtered.length} days)`;
  renderDayTable();
}

function renderDayTable() {
  const tbody = $("#dayTable tbody");
  tbody.innerHTML = "";
  const names = ["Mon", "Tue", "Wed", "Thu", "Fri"];
  state.filteredDays.forEach((r) => {
    const tr = document.createElement("tr");
    tr.className = "dayRow" + (r.date === state.currentTd ? " active" : "") + (state.blind ? " spoiler" : "");
    tr.innerHTML = `<td data-label="Date">${state.blind ? "••••••" : r.date}</td><td data-label="Day">${names[r.weekday] ?? ""}</td><td data-label="NY rng">${r.ny_range_pips ?? "—"}</td><td data-label="Lon rng">${r.lon_range_pips ?? "—"}</td>`;
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
  renderDayTable();
  updateClockLabel();
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
  const markers = SESSION_WINDOWS.map(([name, lo]) => {
    const t = Math.floor(new Date(tdPlusHours(state.currentTd, lo)).getTime() / 1000);
    return { time: t, position: "aboveBar", color: cssVar("--text-3"), shape: "circle", text: name };
  }).filter((m) => m.time <= toEpoch(state.until));
  try { state.series.setMarkers(markers); } catch (e) { /* time not in visible range yet */ }
}

function toEpoch(localIso) { return Math.floor(new Date(localIso).getTime() / 1000); }

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
  updateClockLabel();
}

$("#stepFwd").onclick = () => stepBars(1);
$("#stepHour").onclick = () => stepBars(12); // 12 M5 bars = 1 hour, resample handles coarser TFs
$("#jumpBtn").onclick = () => {
  const t = $("#jumpTime").value; // HH:MM
  if (!t) return;
  const [hh, mm] = t.split(":").map(Number);
  const d = new Date(state.currentTd + "T00:00:00");
  d.setHours(hh, mm, 0, 0);
  const pad = (n) => String(n).padStart(2, "0");
  state.until = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(hh)}:${pad(mm)}:00`;
  refreshBars(); refreshLevels(); updateClockLabel();
};

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
$("#blindMode").onchange = (e) => { state.blind = e.target.checked; renderDayTable(); drawLevelLines(); };
$("#darkToggle").onchange = (e) => applyTheme(e.target.checked);

document.querySelectorAll("#fWeekdays input, #fExcludeThin, #fLonHigh, #fLonLow").forEach((el) => el.addEventListener("change", loadDayList));
$("#fFrom").onchange = loadDayList;
$("#fTo").onchange = loadDayList;

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

// ---------------------------------------------------------------- presets
async function loadPresetList() {
  const presets = await getJSON("/api/presets");
  const sel = $("#presetSelect");
  sel.innerHTML = '<option value="">-- load preset --</option>';
  presets.forEach((p) => sel.insertAdjacentHTML("beforeend", `<option value="${p.name}">${p.name}</option>`));
  sel.onchange = () => {
    const p = presets.find((x) => x.name === sel.value);
    if (!p) return;
    if (p.from) $("#fFrom").value = p.from;
    if (p.to) $("#fTo").value = p.to;
    $("#fLonHigh").checked = !!p.lon_high;
    $("#fLonLow").checked = !!p.lon_low;
    loadDayList();
  };
}
$("#savePreset").onclick = async () => {
  const name = prompt("Preset name:");
  if (!name) return;
  const f = currentFilters();
  await postJSON("/api/presets", { name, from: f.from, to: f.to, lon_high: $("#fLonHigh").checked, lon_low: $("#fLonLow").checked });
  loadPresetList();
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
  if (state.filteredDays.length) await loadDay(state.filteredDays[Math.floor(state.filteredDays.length / 2)].date);
})();
