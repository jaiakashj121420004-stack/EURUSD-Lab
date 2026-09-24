// EURUSD Session Research Lab -- replay trainer frontend.
// No-leak discipline: this file NEVER asks the server for anything past the currently
// revealed timestamp. Stepping forward means "reveal one more 5-minute bar" -- the next
// bar's TIME is known (fixed grid), its PRICE is not, until the server sends it.

const SESSION_WINDOWS = [ // h-relative to td midnight -- for on-chart labels only (times aren't secret)
  ["CBDR", -3, 3], ["Asia", -4, 0], ["London KZ", 2, 5], ["London SB", 3, 4],
  ["NY AM", 7, 12], ["NY AM KZ", 7, 10], ["NY AM SB", 10, 11], ["Lunch", 12, 13.5],
  ["NY PM", 13.5, 16], ["NY PM SB", 14, 15],
];

const state = {
  allDays: [], filteredDays: [], currentIdx: -1, currentTd: null,
  tf: "M5", startAtH: 7, until: null, lastBarTime: null, dayEndH: 16,
  chart: null, series: null, markers: [],
  levels: {}, position: null, // {side, entry, sl, tp, lots, riskDollars, openedAt}
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

// ---------------------------------------------------------------- chart setup
function initChart() {
  const el = $("#chart");
  state.chart = LightweightCharts.createChart(el, {
    layout: { background: { color: "transparent" }, textColor: "#dbe2f0" },
    grid: { vertLines: { color: "#22283a" }, horzLines: { color: "#22283a" } },
    timeScale: { timeVisible: true, secondsVisible: false },
    rightPriceScale: { borderColor: "#2a3348" },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  state.series = state.chart.addCandlestickSeries({
    upColor: "#22b07d", downColor: "#e0526a", borderVisible: false,
    wickUpColor: "#22b07d", wickDownColor: "#e0526a",
  });
  new ResizeObserver(() => state.chart.resize(el.clientWidth, el.clientHeight)).observe(el);
}

function applyTheme(dark) {
  document.body.classList.toggle("light", !dark);
  state.chart.applyOptions({
    layout: { textColor: dark ? "#dbe2f0" : "#1a2130" },
    grid: { vertLines: { color: dark ? "#22283a" : "#e7ebf3" }, horzLines: { color: dark ? "#22283a" : "#e7ebf3" } },
  });
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
    tr.innerHTML = `<td>${state.blind ? "••••••" : r.date}</td><td>${names[r.weekday] ?? ""}</td><td>${r.ny_range_pips ?? "—"}</td><td>${r.lon_range_pips ?? "—"}</td>`;
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
  if (state.position) checkFillsAgainstNewBars(bars);
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
    ["lon_high", "London high", "#4f8cff"], ["lon_low", "London low", "#4f8cff"],
    ["asia_high", "Asia high", "#9a7fd1"], ["asia_low", "Asia low", "#9a7fd1"],
    ["pdh", "PDH", "#d9a441"], ["pdl", "PDL", "#d9a441"],
    ["mid_open", "Midnight open", "#7f8bab"], ["o0930", "09:30 open", "#7f8bab"],
  ];
  show.forEach(([key, label, color]) => {
    const v = state.levels[key];
    if (v == null || state.blind) return;
    priceLines.push(state.series.createPriceLine({ price: v, color, lineWidth: 1, lineStyle: 2, title: label }));
  });
}

function applySessionMarkers() {
  const markers = SESSION_WINDOWS.map(([name, lo]) => {
    const t = Math.floor(new Date(tdPlusHours(state.currentTd, lo)).getTime() / 1000);
    return { time: t, position: "aboveBar", color: "#7f8bab", shape: "circle", text: name };
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
function updateTicketUI() {
  $("#openTradeBtn").disabled = !!state.position;
  $("#closeTradeBtn").disabled = !state.position;
  $("#saveJournalBtn").disabled = !state.lastClosedTrade;
  $("#openTradeInfo").textContent = state.position
    ? `Open: ${state.position.side.toUpperCase()} @ ${fmtPrice(state.position.entry)} SL ${fmtPrice(state.position.sl)} TP ${fmtPrice(state.position.tp)} lots ${state.position.lots}`
    : "";
}

async function refreshLotsPreview() {
  const sl = parseFloat($("#slInput").value), riskPct = parseFloat($("#riskPct").value);
  const lastClose = state.series.data().slice(-1)[0]?.close;
  if (!sl || !lastClose || !riskPct) { $("#lotsPreview").textContent = ""; return; }
  const slPips = Math.abs(lastClose - sl) / 0.0001;
  const { lots } = await postJSON("/api/sim/lots", { balance: state.account.balance, risk_pct: riskPct, sl_distance_pips: slPips });
  $("#lotsPreview").textContent = `${lots} lots (SL ${slPips.toFixed(1)} pips)`;
}
["slInput", "riskPct"].forEach((id) => $(`#${id}`).addEventListener("input", refreshLotsPreview));

$("#openTradeBtn").onclick = () => {
  const lastBar = state.series.data().slice(-1)[0];
  if (!lastBar) return alert("No bar revealed yet.");
  const side = $("#side").value;
  const sl = parseFloat($("#slInput").value), tp = parseFloat($("#tpInput").value) || null;
  if (!sl) return alert("Set a stop loss first.");
  const entry = lastBar.close; // filled at the close of the last revealed bar (conservative, no peeking)
  state.position = { side, entry, sl, tp, openedAt: state.until };
  updateTicketUI();
};

$("#closeTradeBtn").onclick = () => {
  const lastBar = state.series.data().slice(-1)[0];
  finishTrade(lastBar.close, "manual");
};

async function checkFillsAgainstNewBars(newBars) {
  if (!state.position) return;
  for (const bar of newBars) {
    if (bar.time <= toEpoch(state.position.openedAt)) continue;
    const { filled, reason, exit } = await postJSON("/api/sim/fill_check", { position: state.position, bar });
    if (filled) { await finishTrade(exit, reason); break; }
  }
}

async function finishTrade(exitPrice, reason) {
  if (!state.position) return;
  const pos = state.position;
  const R = computeRLocal(pos, exitPrice);
  state.account.balance += R.R_net * (state.account.balance * (parseFloat($("#riskPct").value) / 100));
  state.lastClosedTrade = { ...pos, exit: exitPrice, reason, ...R, td: state.currentTd };
  state.position = null;
  updateTicketUI();
  await refreshAccountPanel();
}

function computeRLocal(pos, exitPrice) {
  const risk = Math.abs(pos.entry - pos.sl);
  const pnl = pos.side === "long" ? exitPrice - pos.entry : pos.entry - exitPrice;
  const costPips = 1.0, pip = 0.0001;
  return { risk_pips: risk / pip, R_gross: pnl / risk, R_net: (pnl - costPips * pip) / risk };
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
    <div class="row"><span>Balance</span><b>$${s.balance.toFixed(2)}</b></div>
    <div class="row"><span>Day P&amp;L</span><span>${s.day_pnl_pct.toFixed(2)}%</span></div>
    <div class="row"><span>Daily DD used</span><span class="badge ${s.day_dd_status}">${s.day_dd_used_pct.toFixed(2)}% / ${s.day_dd_limit_pct}%</span></div>
    <div class="row"><span>Max DD used</span><span class="badge ${s.max_dd_status}">${s.max_dd_used_pct.toFixed(2)}% / ${s.max_dd_limit_pct}%</span></div>
    ${s.day_dd_breached || s.max_dd_breached ? '<div class="row" style="color:#e0526a">BREACHED</div>' : ""}
  `;
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

// ---------------------------------------------------------------- boot
(async function init() {
  initChart();
  await loadDayList();
  await loadPresetList();
  await refreshAccountPanel();
  if (state.filteredDays.length) await loadDay(state.filteredDays[Math.floor(state.filteredDays.length / 2)].date);
})();
