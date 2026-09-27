# DESIGN_SYSTEM.md — EURUSD Session Research Lab

Visual layer only. Nothing here changes numbers, routes, or the no-leak/read-only logic (CLAUDE.md
rules 1–9 always win over anything in this file). This doc is the audit + token/spec reference;
`design/preview.html` is the single **approved** implementation the token values below are pulled
from — read it, not this doc, for the exact CSS if the two ever drift.

**Status (2026-09): APPROVED, single direction.** `design/preview.html` went through one earlier
round — a first preview Akash rejected — then a full rebuild, which he approved. The three
candidate palettes this doc originally listed in §3 (never shipped anywhere) are gone; §3 now
documents the one system that was actually picked: **"Porcelain" (light, default) / "Espresso"
(dark)**, a neumorphism + glass system (soft same-color-surface shadows for chrome, glass for
overlays, flat/opaque for anything with real data on it — candles, tables, numbers). `nylab/
label_validate.py`'s label-validation review page is the **first real (non-preview) surface**
restyled to this system (2026-09-27); surface A (replay trainer) got its tokens/colors/theme-
toggle restyled the same day (§1 — layout/breakpoints still to do); surface B (research report)
is still its own separate light-only palette, restyled later — same rule each time: read
`design/preview.html`'s current token values at restyle time, don't hand-copy this doc.

## 1. Surfaces audited

**A. Replay trainer** (`nylab/replay/static/{index.html,style.css,app.js}`, served by `server.py`/`api.py`).
**Fully restyled 2026-09-27, all 3 stages.** Stage 1 (tokens/colors): full Porcelain/Espresso token
set + elevation classes (`style.css`), the `.light` body-class toggle replaced by the standard
`data-theme` attribute + `localStorage` `eurusd-theme` pattern (same as surface C), `#darkToggle`'s
id/onchange contract kept exactly (now a CSS-styled switch, not a plain checkbox visually). Chart
colors were hardcoded in THREE places (`style.css` vars, `app.js`'s `initChart`, `app.js`'s
`applyTheme`) — now read live from the CSS via a `cssVar()` helper everywhere (`initChart`,
`applyTheme`, `sessionBoxes()`, `drawLevelLines`, `applySessionMarkers`, `drawPositionLines`), one
source of truth. Two new semantic tokens (`--level-asia`, `--level-weekly`) let the 5 level-line
groups (London/Asia/daily/weekly/session-opens) stay visually distinct while everything else
reuses the core 4 hues. Breach is now styled (`.breach`: bear color + diagonal hatch + an
inline-SVG warning icon, no color-alone signal, no emoji) — previously plain unstyled text.

Stage 2 (responsive, §8): >=1440px keeps the original 3-column grid; 1024-1439px drops to chart +
account panel with the navigator becoming a slide-in drawer (`#navToggle`, `#overlayDim`);
600-1023px drops both side panels to drawers (`#navToggle`+`#acctToggle`); <600px (phone) goes
chart-first in a single stacked column, with `#navigator`/`#accountPanel` sharing one fixed
bottom-sheet slot switched by a small tab bar (`#sheetTabs`/`#tabDays`/`#tabAccount` — new IDs,
nothing existing renamed) rather than a full drag-gesture sheet (that needs real gesture JS, kept
as an ahead-only mock in `design/preview.html` per its own §4 note, not built for the real app in
this pass). The day table becomes cards on phone (CSS `data-label`-driven, new `data-label`
attributes on `renderDayTable()`'s cells, no markup restructuring). All required IDs/classes in
this section re-verified present after every stage's edits.

Stage 3 (remaining §9 polish): tap-accessible info-icon tooltips (`.info-icon`, one shared
floating `.tooltip-pop`, event-delegated so icons added dynamically by `refreshAccountPanel()`
work with no extra wiring) added next to Risk %, the lots preview, and the daily/max drawdown
badges. The blind-mode spoiler row's mask got a diagonal-hatch pattern added on top of its
existing opacity dim, matching the breach treatment's "color + pattern, never color alone" rule.

**Fixed separately, same day (2026-09-27), NOT in a design-system commit**: `renderDayTable()`
used to only replace the Date cell's text with `••••••` in blind mode; the NY/London range
PIP VALUES were never masked, just dimmed, so they were still readable underneath the hatch. That
was a data-exposure gap in the blind-mode LOGIC, not styling, so per the no-mixing rule it was
fixed in its own standalone commit (a narrow slice of ROADMAP 6.2, "hide-outcome columns"; the
rest of 6.2 -- spoiler icons beyond this table, filters/presets in 6.1/6.3 -- is still open).
`renderDayTable()` now masks all three of Date/NY rng/Lon rng behind the same `••••••` when
blind mode is on.

States: empty (no day loaded), loading (day list fetch), day loaded/no trade, pending order, open
trade, trade closed, blind mode, spoiler day-table rows (`.spoiler`, hatched), breach (styled),
dragging SL/TP line (`.dragging-line`), drawer open/closed, bottom-sheet tab active.

**B. Research report** (`nylab/report/html.py` + `charts.py` + `sessions_section.py`). Single inline
`<style>` block, light-only, fixed max-width 980px column, no dark mode. Charts are matplotlib PNGs
baked in at generation time (`charts.py:fig_b64`) — a dark-mode report needs a second PNG rendered
with a dark matplotlib style, not CSS filters (filters would distort data colors). Verdict words
today: `survives-oos`/`candidate`/`noise`/`not proven` (informal, inline text, no consistent badge)
plus the new `negative` word Phase 5.7 will add. Descriptive vs tested sections aren't visually
distinguished at all right now — section 3 (tested) and sections 5–9 (descriptive, `DESIGN_BANNER`
text only) look identical.

**C. Label-validation review page** (`nylab/label_validate.py`'s `_HTML_TEMPLATE`). **Restyled
2026-09-27** to the approved Porcelain/Espresso system (§3) — light default, dark toggle via the
same `localStorage`-backed pattern as `design/preview.html`, `elev-raised`/`elev-inset` shadow pairs
on the header/day cards/zoom buttons/Agree-Disagree buttons/bottom bar/note inputs, bull/bear candle
colors from `--bull`/`--bear` instead of the old gold accent. Single fixed-width column, zoom
buttons, glossary `<details>`, and Agree/Disagree buttons (`.ans`, `.sel-agree`, `.sel-disagree`)
kept their exact class names throughout the restyle — `render_html()`'s JS and `label_validate.
score()` both still read them. Two functional additions landed in the same round (ROADMAP 5.6,
curated near-threshold sampling): the per-row numeric feature values (range_rel/er/close_loc, or the
day-level equivalent) shown as muted text under each label, and dashed PDH/PDL reference lines drawn
on the full-day chart for day_type calls.

**D. Built 2026-09-27 (Phase 6, ROADMAP 6.1-6.7)**: stats tab, challenge mode, review-mode
overlay, news markers with a reveal state, spoiler icons/badge, advanced DSL filter, session-
character/news/raid/ADR filters, and preset save/load/delete are all real, working features in
`static/index.html`/`app.js`/`style.css` now -- not mockups. They followed the existing
Porcelain/Espresso token system rather than introducing new colors; no new commit is needed for
their visual language, only the frozen-hooks list update in section 2 below.

**Still ahead-only previews** (not built yet): trade gallery, "open in replay" deep link, Maven
pass-simulator result screen. These remain mocked in `preview.html` with fake data only.

## 2. IDs / hooks that must survive untouched (grepped from `app.js` and tests)

`#topbar #navigator #filters #fFrom #fTo #fWeekdays #fExcludeThin #fLonHigh #fLonLow #presetSelect
#savePreset #dayTableWrap #dayTable #chartArea #chart #playbar #stepBack #stepFwd #stepHour
#playPause #speed #jumpTime #jumpBtn #clockLabel #accountPanel #acctSummary #ticket #side #orderType
#entryRow #entryInput #riskPct #slInput #tpInput #lotsPreview #openTradeBtn #cancelPendingBtn
#closeTradeBtn #partialCloseBtn #moveBEBtn #pendingInfo #openTradeInfo #journalForm #setupTag
#rulesFollowed #emotion #notes #saveJournalBtn #datePicker #prevDay #nextDay #randomDay #startAt #tf
#blindMode #darkToggle #matchCount`, plus classes `.dayRow .active .spoiler .sessionBox
.dragging-line .badge.green/.amber/.red .muted .footnote`. Label-validate's `.ans .sel-agree
.sel-disagree .zoombtn .active .lbl #bar #progress` and the `downloadAnswers` function name.

**Added 2026-09-27 (responsive drawer pass)**: `#overlayDim #navToggle #acctToggle #sheetTabs
#tabDays #tabAccount #layout`, plus classes `.drawerBtn .sheetActive`.

**Added 2026-09-27 (Phase 6, ROADMAP 6.1-6.7)**: `#statsToggle #statsPanel #statsBody #statsClose
#challengeBanner #challengeStatus #challengeNextDay #challengeStop #startChallenge #deletePreset
#fHideOutcome #fAdrMin #fAdrMax #fDsl #fDslApply #fDslError #spoilerBadge #newsStrip #reviewBtn
#reviewPanel`, plus classes `.filterGroup .charFilterRow .charSelect .fNews .fRaid .newsChip
.pending .surprise-up .surprise-down .iconBtn`. `.charSelect` carries `data-sid="lon"/"asia"/
"nyam_kz"` (not an id -- don't mistake it for a frozen id when grepping). Any
rename happens in the same commit as every reference, tests still green.

## 3. The approved system — "Porcelain" (light, default) / "Espresso" (dark)

Neumorphism + glass: chrome (header, cards, buttons, inputs) uses same-color surfaces with a paired
light/dark box-shadow to read as raised or inset relief, never a hard border; overlays (sheets,
drawers) get `backdrop-filter` glass; the chart canvas and every data table stay flat/opaque, 100%
contrast, never blurred or tinted. Values below are the real tokens from `design/preview.html`
(`:root` = Porcelain, `:root[data-theme="dark"]` = Espresso, with a `prefers-color-scheme` media
block mirroring Espresso for a first visit with no stored preference) — copy from there if this ever
goes stale, not from this table.

**Porcelain (light, default):** base `#F0EDE8` / shadow-dark `rgba(163,150,133,.45)` / shadow-light
`#FFFFFF` / text-1 `#2B2822` / text-2 `#6B6459` / text-3 `#968F82` / accent `#0EA5A0` / amber
`#E39B2F` / bull `#0F9D76` / bear `#E5484D` / glass-fill `rgba(240,237,232,.55)` / glass-border
`rgba(255,255,255,.6)`.

**Espresso (dark):** base `#1E1B18` / shadow-dark `#12100E` / shadow-light `rgba(255,255,255,.045)`
/ text-1 `#EFE9E1` / text-2 `#A79E92` / text-3 `#746B60` / accent `#2DD4BF` / amber `#F5B04C` / bull
`#22C39A` / bear `#FF6369` / glass-fill `rgba(30,27,24,.45)` / glass-border `rgba(255,255,255,.09)`.

Bull/bear stay each theme's own green/red (never doubled as the accent color, never reused for
anything but P&L/candle direction). `--profit`/`--loss` = same as bull/bear. Amber is the shared
warn/impact color (`--warn`, news-impact medium, the "Warm Ink" gold this system replaces
everywhere it appeared). `--breach` = bear at full saturation + a diagonal-hatch pattern (never
colour alone). Session colors (subtle fills, never hide a wick): reuse the theme's own accent/amber/
bull/bear at low opacity (~6-8%) per session rather than a fixed hex list, so they stay in sync with
whichever theme is active — label-validate's session shading already does this (`--amber-rgb` at
.07/.35 alpha).

**Elevation classes** (from `design/preview.html`, reused verbatim by every restyled surface):
`.elev-flat` (background only, no shadow), `.elev-raised` (`8px 8px 18px var(--shadow-dark), -8px
-8px 18px var(--shadow-light)`), `.elev-raised-soft` (same pattern, half the offset/blur — smaller
components), `.elev-inset` (the same shadow pair, `inset`), `.press:active` (inset shadow + `scale
(0.98)`, ~80ms linear — the tactile "pressed" state for any clickable raised/soft element). Radii:
`--radius-card: 18px`, `--radius-pill: 999px` (buttons/chips/badges), `--radius-island: 26px` (top-
level panels). Motion: `--ease-glide: cubic-bezier(0.22, 1, 0.36, 1)`, `--t-fast: 140ms`, `--t-med:
320ms` — background/color/box-shadow transitions only, `prefers-reduced-motion` respected.

**Theme toggle:** a small circular sun/moon icon button (`#themeBtn`/`#themeIcon` in preview.html,
adapted per-surface), `localStorage` key `eurusd-theme` (`'light'`/`'dark'`, wrapped in try/catch so
a private window or blocked storage degrades to system preference instead of throwing), read once on
load via `data-theme` on `<html>`; `prefers-color-scheme` only decides the very first visit, before
anything is stored.

## 4. Type

One vendored variable sans (UI text) + one vendored tabular monospace/lining-numerals face (prices,
times, table numbers) — both OFL, dropped in `nylab/replay/static/vendor/fonts/` with their license
file, no CDN. `font-variant-numeric: tabular-nums` wherever numbers line up in a column. Scale: 11 /
12 / 13 / 15 / 18 / 24px, line-height 1.45 body / 1.2 headings. Prices always 5 decimals, pips 1
decimal, every time value carries a literal "NY" suffix or column header — never bare.

## 5. Spacing, radii, elevation

Spacing scale: 4 / 8 / 12 / 16 / 24 / 32px. Radii and elevation are the approved system's own (§3:
`--radius-card`/`--radius-pill`/`--radius-island`, `.elev-raised`/`.elev-raised-soft`/`.elev-inset`)
— this section previously listed its own placeholder numbers (6/10/16px, plain border+blur) written
before a direction was picked; superseded by §3, kept only as a pointer so nothing here contradicts
it. The chart canvas and every data table stay flat/opaque, 100% contrast, never blurred or tinted —
a candle wick must never sit under glass.

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
