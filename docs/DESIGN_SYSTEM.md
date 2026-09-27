# DESIGN_SYSTEM.md — EURUSD Session Research Lab

Visual layer only. Nothing here changes numbers, routes, or the no-leak/read-only logic (CLAUDE.md
rules 1–9 always win over anything in this file). This doc is the audit + token/spec reference;
`design/preview.html` is where the 3 palette directions are actually seen and picked.

## 1. Surfaces audited

**A. Replay trainer** (`nylab/replay/static/{index.html,style.css,app.js}`, served by `server.py`/`api.py`).
Currently: fixed 3-column CSS grid (300px | 1fr | 260px), no responsive breakpoints at all, dark-only
palette with a `.light` body-class toggle already wired (`app.js:applyTheme`, `#darkToggle`), chart
colors hardcoded twice — once in `style.css` custom properties, once again as literal hex inside
`app.js` (`initChart`, `applyTheme`, `SESSION_BOXES`) — these two must become one source of truth.
States: empty (no day loaded), loading (day list fetch), day loaded/no trade, pending order, open
trade, trade closed, blind mode, spoiler day-table rows (`.spoiler`), breach (not yet styled —
account panel is plain text rows today), dragging SL/TP line (`.dragging-line`).

**B. Research report** (`nylab/report/html.py` + `charts.py` + `sessions_section.py`). Single inline
`<style>` block, light-only, fixed max-width 980px column, no dark mode. Charts are matplotlib PNGs
baked in at generation time (`charts.py:fig_b64`) — a dark-mode report needs a second PNG rendered
with a dark matplotlib style, not CSS filters (filters would distort data colors). Verdict words
today: `survives-oos`/`candidate`/`noise`/`not proven` (informal, inline text, no consistent badge)
plus the new `negative` word Phase 5.7 will add. Descriptive vs tested sections aren't visually
distinguished at all right now — section 3 (tested) and sections 5–9 (descriptive, `DESIGN_BANNER`
text only) look identical.

**C. Label-validation review page** (`nylab/label_validate.py`'s `_HTML_TEMPLATE`). Dark-only, its own
third palette (gold `#e8c77a` accent — different from both A and B), single fixed-width column,
already has zoom buttons, a glossary `<details>`, and Agree/Disagree buttons (`.ans`, `.sel-agree`,
`.sel-disagree`) that must keep their exact class names — `render_html()`'s JS reads them.

**D. Ahead-only previews** (Phase 6/8, not built yet): stats tab, challenge mode, review-mode overlay,
news markers with a reveal state, spoiler icons, advanced DSL filter, trade gallery, "open in replay"
deep link, Maven pass-simulator result screen. These get mocked in `preview.html` with fake data only.

## 2. IDs / hooks that must survive untouched (grepped from `app.js` and tests)

`#topbar #navigator #filters #fFrom #fTo #fWeekdays #fExcludeThin #fLonHigh #fLonLow #presetSelect
#savePreset #dayTableWrap #dayTable #chartArea #chart #playbar #stepBack #stepFwd #stepHour
#playPause #speed #jumpTime #jumpBtn #clockLabel #accountPanel #acctSummary #ticket #side #orderType
#entryRow #entryInput #riskPct #slInput #tpInput #lotsPreview #openTradeBtn #cancelPendingBtn
#closeTradeBtn #partialCloseBtn #moveBEBtn #pendingInfo #openTradeInfo #journalForm #setupTag
#rulesFollowed #emotion #notes #saveJournalBtn #datePicker #prevDay #nextDay #randomDay #startAt #tf
#blindMode #darkToggle #matchCount`, plus classes `.dayRow .active .spoiler .sessionBox
.dragging-line .badge.green/.amber/.red .muted .footnote`. Label-validate's `.ans .sel-agree
.sel-disagree .zoombtn .active .lbl #bar #progress` and the `downloadAnswers` function name. Any
rename happens in the same commit as every reference, tests still green.

## 3. Three palette directions (final pick happens in `design/preview.html`)

All three share the same semantic-token *names* — only the values differ. None reuse NOVA's
grey-blue. All keep bull/bear green/red untouched by the accent choice (accent never doubles as a
P&L color).

**Direction 1 — "Deep Slate"** (cool, neutral, terminal-desk feel):
dark bg `#0B0D10` / panel `#14171C` / border `#262B33` / text `#E6E9ED` / muted `#8A93A0` /
accent `#3DA9FC`. light bg `#F7F8FA` / panel `#FFFFFF` / border `#DFE3E8` / text `#10141A` /
muted `#6B7280`.

**Direction 2 — "Warm Ink"** (warm charcoal, amber/gold accent — closest to the existing gold already
used in the report and label-validate page, so picking this is the smallest visual jump):
dark bg `#12100D` / panel `#1B1815` / border `#2E2A24` / text `#ECE7DE` / muted `#9C9284` /
accent `#D9A441`. light bg `#FAF7F2` / panel `#FFFFFF` / border `#E6DFD2` / text `#201B12`.

**Direction 3 — "Graphite Violet"** (cool graphite, restrained violet accent, most distinct from
anything already in the codebase):
dark bg `#0E0E13` / panel `#17161E` / border `#2A2833` / text `#E7E5EE` / muted `#8D8A9C` /
accent `#8C7CF0`. light bg `#F6F5FA` / panel `#FFFFFF` / border `#E1DFEA` / text `#17151F`.

Shared semantic tokens (all directions): `--bull #1FAE7A` (filled) / `--bear #E24B63` (hollow —
survives deuteranopia/protanopia by shape, not just hue; a colour-blind-safe candle mode swaps
fill/hollow for a blue/orange pair), `--profit`/`--loss` = same as bull/bear, `--warn #D9A441`,
`--breach #E24B63` at full saturation + a diagonal-hatch pattern (never colour alone), `--pending
#7C8CA6`, `--sl #E24B63`, `--tp #1FAE7A`, `--be #7C8CA6`, news impact low/med/high = muted → warn →
breach. Session colors (subtle fills, never hide a wick): Asia `#8C7CF0`@8%, London `#3DA9FC`@8%,
NY AM `#1FAE7A`@8%, Lunch `#7C8CA6`@8%, NY PM `#E88A3D`@8%, Silver Bullet windows (all three) `#D9A441`
point-markers, not fills (too narrow to shade without hiding bars).

## 4. Type

One vendored variable sans (UI text) + one vendored tabular monospace/lining-numerals face (prices,
times, table numbers) — both OFL, dropped in `nylab/replay/static/vendor/fonts/` with their license
file, no CDN. `font-variant-numeric: tabular-nums` wherever numbers line up in a column. Scale: 11 /
12 / 13 / 15 / 18 / 24px, line-height 1.45 body / 1.2 headings. Prices always 5 decimals, pips 1
decimal, every time value carries a literal "NY" suffix or column header — never bare.

## 5. Spacing, radii, elevation

Spacing scale: 4 / 8 / 12 / 16 / 24 / 32px. Radii: 6px (buttons/inputs), 10px (cards/panels), 16px
(sheets/modals). Elevation is glass+shadow, chrome only: panels get a 1px border + very subtle
`backdrop-filter: blur()` and a soft shadow; the chart canvas and every data table stay flat/opaque,
100% contrast, never blurred or tinted — a candle wick must never sit under glass.

## 6. Components (shared vocabulary across all 3 surfaces)

Topbar, nav rail / drawer, glass sheet (mobile bottom sheet, slide-over drawer), card, data table with
sticky first column, order ticket, verdict badge (6 words: `noise` `not proven` `promising` `candidate`
`survives-oos` `negative` — only `survives-oos` gets celebratory styling), limit meter (calm → amber
50% → red 75% → breach, breach = colour + hatch + icon, never colour alone), toast, info-icon
tooltip (tap-friendly, not hover-only), zoom/tab button group (label-validate's existing `.zoombtn`
pattern, generalized), spoiler mask (blind mode / hide-outcome), icon set: one inline-SVG stroke
family, no emoji anywhere in the UI.

## 7. Motion

150–350ms, spring-ish ease (`cubic-bezier(0.22, 1, 0.36, 1)` as the base curve), transform/opacity
only. Sheets/drawers slide + slight overshoot; scale+shadow for depth, no bounce. Revealed bars: no
animation beyond an optional ≤100ms fade, switched off above 2 bars/s. No tweening of price/candles/
count-up numbers, ever. Meaningful-only triggers: day change, trade open/close (ticket→chart line),
limit crossing (one calm pulse), breach (once, unmistakable, never flashing/looping).
`prefers-reduced-motion` respected + an explicit in-app toggle, both checked before any transition
fires.

## 8. Breakpoints

<600 phones (chart-first, sticky playbar, bottom-sheet tabs for nav/account/ticket/journal, day table
becomes cards) · 600–1023 tablets/unfolded foldables (chart full width, nav/account as glass sheets)
· 1024–1439 (chart + one side column, nav becomes a drawer) · ≥1440 (3-column with resizable
splitters, extra space to the chart) · ≥2560 (optional 4th column). Foldable segments via
`horizontal-viewport-segments`/`vertical-viewport-segments` media features, clean single-screen
fallback where unsupported. `dvh` not `vh`; `env(safe-area-inset-*)` respected; touch targets ≥44px;
SL/TP drag hit-area enlarged for touch; report/review pages stay one ~75ch column on phones with
wide tables scrolling inside their own container (sticky first column) plus a light, glass-free print
stylesheet.

## 9. Do / don't

**Do:** drive chart colors (lightweight-charts options, matplotlib style) from the same CSS custom
properties the chrome uses — one palette, read in both places. Keep every verdict word's badge
visually distinct even in greyscale/print. Show blind mode and hidden outcomes as an unmistakable
masked state, not just "the number is missing." Give every stat an info icon with a plain-English
sentence, tap-accessible.

**Don't:** blur or tint anything over candles or table numbers. Let motion imply a number changed
before the real value is shown. Use color as the only signal for breach/limit/verdict. Add anything
that reads as "Live" or a broker logo. Ship a CDN font or script — offline stays offline.
