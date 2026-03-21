# index.html Build Strategy — Chunked Assembly

## The Problem
The full index.html with all bug fixes and enhancements is too large to
write in a single tool call. Do NOT attempt to write the entire file at
once. Do NOT use a Python "generator script" — that just moves the same
problem one level up.

## The Solution — 7 Discrete Chunk Files, Then Concatenate

Write the file as 7 separate chunk files, each small enough to complete
in one tool call. Then concatenate them into the final index.html.

---

## Step 0 — Create the build directory

```bash
mkdir -p build_chunks
```

---

## Chunk 1 — HTML head + CSS  →  `build_chunks/chunk1_head_css.html`

Contains:
- `<!DOCTYPE html>` through end of `</style>` tag
- All CSS variables, layout, nav tabs, filter bar styles
- Signal card styles (including composite score colour gradient)
- Heatmap grid styles (CRITICAL: include `.heatmap-container` with
  `display: grid; grid-template-columns: 120px repeat(52, 1fr);
  width: 100%; overflow-x: auto;` — this fixes Bug 1)
- Table styles, chart container styles, percentile bar styles
- Responsive breakpoints

Write this chunk. Verify it ends with `</style>` and nothing else.

---

## Chunk 2 — HTML body structure  →  `build_chunks/chunk2_body_structure.html`

Contains:
- Opening `<body>` tag
- Header bar (logo, title, LATEST REPORT + LAST UPDATED fields)
- Nav tabs (Overview / By Instrument / Three-Trader View)
- Filter bar (date dropdown + trader dropdown — trader dropdown has
  `id="trader-filter"` so it can be hidden on non-By-Instrument tabs)
- All three tab `<div>` containers with their `id` attributes and
  placeholder `<div>` elements for each section:
  - Overview: `#signal-cards-container`, `#heatmap-container`,
    `#correlation-matrix-container`, `#concentration-chart-container`,
    `#weekly-table-container`
  - By Instrument: `#instrument-pills`, `#net-pos-chart-container`,
    `#scatter-chart-container`, `#correlation-chart-container`,
    `#percentile-bars-container`, `#seasonal-chart-container`,
    `#flow-chart-container`, `#extremes-chart-container`
  - Three-Trader: `#three-trader-grid` (9 chart containers, 2-column
    grid layout), `#normalise-toggle` button
- CDN script tags (Chart.js only — no other libraries needed):
  `<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>`

Write this chunk. Verify it ends with the last closing `</div>` before
the `<script>` section.

---

## Chunk 3 — JS: data loading + core utilities
→  `build_chunks/chunk3_js_data_utils.html`

Contains opening `<script>` tag and:

**Data loading**:
```javascript
let CFTC_DATA = null;
let filterFromDate = null;
let activeInstrument = 'nat_gas_nyme';
let activeTrader = 'managed_money';
let normaliseByOI = true;  // default: % of OI mode for Three-Trader
const ALL_CHARTS = [];

async function loadData() { ... }  // with cache-busting ?v=Date.now()
```

**Constants**:
```javascript
const INSTRUMENT_KEYS = [...];    // 9 keys in order
const INSTRUMENT_LABELS = {...};  // key → display name
const TRADER_KEYS = ['managed_money', 'swap_dealers', 'producers'];
const TRADER_LABELS = {...};
const TRADER_COLOURS = {
    managed_money: '#3b82f6',  // blue
    swap_dealers:  '#f59e0b',  // amber
    producers:     '#22c55e',  // green
};
```

**Utility functions**:
- `applyDateFilter(dates, ...arrays)` — returns sliced arrays from
  filterFromDate onwards
- `sanitiseArray(arr)` — replaces null with NaN for Chart.js (Chart.js
  uses NaN as gap, not null — convert nulls at render time not in Python)
- `formatNumber(n)` — locale string with sign
- `getSignalLabel(score)` and `getSignalColour(score)` — composite score
  -3 to +3 → label and CSS colour
- `getSignalBorder(score)` — returns CSS border-color string

**Tab switching**:
```javascript
function switchTab(tabName) {
    // Show/hide tab content divs
    // Show/hide trader-filter based on tabName === 'by-instrument'
    // Re-render visible charts
}
```
CRITICAL: trader-filter display logic goes here — fixes Bug 4.

Does NOT contain any chart rendering functions yet.
Ends with `// === END CHUNK 3 ===` comment (do not close script tag).

---

## Chunk 4 — JS: Overview tab renderers
→  `build_chunks/chunk4_js_overview.html`

Contains (no opening/closing script tags — this is continuation):

**`renderSignalCards()`**:
- Reads latest data point for each of 9 instruments
- Computes composite score (-3 to +3) using the 6-factor logic
- Renders 9 cards with: MM Net + Δwow, Z-Score + percentile rank,
  Swap Net, Prod Net, COT Index (3yr) bar, Price + Δ%, Season,
  composite signal label and colour
- SIGNAL BOUNDARY FIX (Bug 2): use `>=` and `<=` not `>` and `<`
  for all threshold comparisons

**`renderHeatmap()`**:
- Reads last 52 weeks of z_score for managed_money for all 9 instruments
- Builds CSS grid (not canvas) — one div per cell
- Cell background: `hsl(${h}, 70%, 40%)` where h interpolates
  red (0°) at z≤-2 → white (0° sat 0%) at z=0 → green (120°) at z≥+2
- Row labels: instrument display names
- Column headers: dates (rotated 45°)
- On hover: show tooltip with instrument + date + z-score
- On click: switch to By Instrument tab for that instrument
- HEATMAP FIX (Bug 1): container must use CSS grid not canvas,
  with explicit `grid-template-columns: 120px repeat(52, 1fr)`

**`renderCorrelationMatrix()`**:
- Reads `CFTC_DATA.correlation_matrix`
- 9×9 CSS grid, same colour scheme as heatmap
- Diagonal cells = 1.0 (always deep green)
- Hover tooltip: "Instrument A vs Instrument B: 0.87"

**`renderConcentrationChart()`**:
- Reads `nat_gas_nyme.concentration` arrays
- Chart.js line chart: top4_long and top4_short over time
- Horizontal annotation at 50% for "Concentrated" threshold
- Apply date filter

**`renderWeeklyTable()`**:
- Sortable table, all 9 instruments
- Uses CFTC-reported change values (change_net) not computed difference
- Colour-code delta columns

Ends with `// === END CHUNK 4 ===` comment.

---

## Chunk 5 — JS: By Instrument tab renderers
→  `build_chunks/chunk5_js_by_instrument.html`

Contains (continuation):

**`renderInstrumentPills()`** — pill selector for 9 instruments

**`renderNetPosChart(instrumentKey, traderKey)`**:
- Dual-axis Chart.js bar+line chart (exact Excel replica)
- Bars: green when net > 0, red when net < 0 (per-bar colour array)
- Price line on secondary Y-axis (white dashed)
- Historical extremes lines (Bug fix Enhancement 8):
  horizontal annotations at max_long and max_short values
- Apply date filter

**`renderScatterChart(instrumentKey, traderKey)`**:
- Scatter: X = long positions, Y = price
- Point colours: Withdrawal = #60a5fa (blue), Injection = #fb923c (orange)
- Apply date filter

**`renderCorrelationChart(instrumentKey)`**:
- 20-week rolling correlation line chart
- Reference line at 0
- Background shading: green when >0.4, red when <-0.4 (regime bands)
- Apply date filter

**`renderPercentileBars(instrumentKey)`**:
- Three horizontal bars: MM, Swap, Producers
- Current percentile rank value
- Background zones: 0-20% red, 80-100% green, middle grey
- COT Index (3yr) also shown as secondary bar below each

**`renderSeasonalChart(instrumentKey, traderKey)`**:
- Current year's net position vs historical seasonal average ± 1 std dev band
- Year overlay selector (2022–2026 checkboxes)

**`renderFlowChart(instrumentKey, traderKey)`**:
- Weekly change_net as green/red bars
- Apply date filter

Ends with `// === END CHUNK 5 ===` comment.

---

## Chunk 6 — JS: Three-Trader View + shared crosshair
→  `build_chunks/chunk6_js_three_trader.html`

Contains (continuation):

**`renderThreeTraderGrid()`**:
- 9 charts in 2-column CSS grid
- Each chart: MM (blue), Swap (amber), Producers (green) lines + Price (dashed white)
- SCALE FIX (Bug 3): when `normaliseByOI === true`, divide each
  trader's net by open_interest_all before plotting. Y-axis label
  changes to "% of OI". When false, use independent Y-axes per trader:
  ```javascript
  scales: {
      y:  { position: 'left',   display: true  },  // MM
      y1: { position: 'right',  display: false },  // Swap (hidden axis)
      y2: { position: 'right',  display: false },  // Producers (hidden axis)
  }
  ```
- Toggle button `#normalise-toggle` switches mode, calls
  `renderThreeTraderGrid()` again

**Synced crosshair plugin**:
```javascript
const syncCrosshairPlugin = {
    id: 'syncCrosshair',
    afterDraw(chart, args, options) {
        if (chart._activeCrosshairX == null) return;
        const ctx = chart.ctx;
        const x = chart._activeCrosshairX;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(x, chart.chartArea.top);
        ctx.lineTo(x, chart.chartArea.bottom);
        ctx.strokeStyle = 'rgba(255,255,255,0.3)';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.restore();
    }
};
Chart.register(syncCrosshairPlugin);
```

On `onHover` in any chart options:
```javascript
onHover: (event, elements, chart) => {
    const x = event.x;
    ALL_CHARTS.forEach(c => {
        c._activeCrosshairX = x;
        c.update('none');
    });
}
```

**`downloadCSV(instrumentKey, traderKey)`** — CSV export function

Ends with `// === END CHUNK 6 ===` comment.

---

## Chunk 7 — JS: init + event wiring + closing tags
→  `build_chunks/chunk7_js_init.html`

Contains (continuation):

**`initDashboard()`** — called after data loads:
```javascript
function initDashboard() {
    populateDateFilter();
    renderSignalCards();
    renderHeatmap();
    renderCorrelationMatrix();
    renderConcentrationChart();
    renderWeeklyTable();
    renderInstrumentPills();
    renderAllByInstrument();   // renders active instrument charts
    renderThreeTraderGrid();
    switchTab('overview');     // start on overview
}
```

**Event listeners**:
- Date filter `change` → re-render all charts in active tab
- Trader filter `change` → re-render By Instrument charts
- Instrument pills `click` → update activeInstrument, re-render
- Normalise toggle `click` → flip normaliseByOI, re-render three-trader
- Tab nav `click` → call switchTab()

**`window.addEventListener('DOMContentLoaded', loadData)`**

Closing `</script>` tag and `</body></html>`.

---

## Step 8 — Concatenate all chunks

After all 7 chunks are written and individually verified (no syntax
errors, balanced tags), concatenate:

```bash
cat build_chunks/chunk1_head_css.html \
    build_chunks/chunk2_body_structure.html \
    build_chunks/chunk3_js_data_utils.html \
    build_chunks/chunk4_js_overview.html \
    build_chunks/chunk5_js_by_instrument.html \
    build_chunks/chunk6_js_three_trader.html \
    build_chunks/chunk7_js_init.html \
    > index.html
```

---

## Step 9 — Verify the assembled file

Run these checks before considering the build complete:

```bash
# 1. File exists and is substantial
wc -c index.html
# Expected: > 80,000 bytes

# 2. No unclosed script tags
python3 -c "
content = open('index.html').read()
opens  = content.count('<script')
closes = content.count('</script>')
print(f'script tags: {opens} open, {closes} close')
assert opens == closes, 'MISMATCHED SCRIPT TAGS'
print('OK')
"

# 3. No unclosed div tags
python3 -c "
content = open('index.html').read()
opens  = content.count('<div')
closes = content.count('</div>')
print(f'div tags: {opens} open, {closes} close')
# Allow small difference due to self-closing or template divs
assert abs(opens - closes) < 5, f'MISMATCHED DIV TAGS: {opens} vs {closes}'
print('OK')
"

# 4. Critical CSS present (heatmap fix)
grep -c 'grid-template-columns.*repeat(52' index.html
# Expected: 1 or more

# 5. Critical JS present (bug fixes)
grep -c 'trader-filter' index.html     # Bug 4 fix
grep -c 'normaliseByOI' index.html     # Bug 3 fix
grep -c 'cot_index' index.html         # Enhancement 1
grep -c 'composite_score\|getSignalLabel' index.html  # Enhancement 6
# All should return > 0

# 6. No placeholder TODO comments left
grep -i 'TODO\|FIXME\|placeholder\|coming soon' index.html | wc -l
# Expected: 0
```

If any check fails, identify which chunk is responsible and rewrite
that chunk only — do not rewrite the entire file.

---

## Chunk Writing Rules

1. Write one chunk per tool call — do not combine chunks
2. Each chunk must be syntactically valid on its own (valid HTML or
   valid JS continuation — clearly comment where it starts/ends)
3. If a chunk is still too large, split it further (e.g. chunk5a,
   chunk5b) — never try to compress or abbreviate the code
4. After writing each chunk, immediately verify it was written correctly
   by reading back the last 20 lines
5. Do not proceed to the next chunk until the current one is verified
