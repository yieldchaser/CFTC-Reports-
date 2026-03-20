# CFTC Natural Gas Positioning Dashboard — Agent Build Prompt

## Context & Goal

You are building a professional-grade, fully automated CFTC positioning
monitoring dashboard for natural gas futures. It will live on GitHub Pages
inside the existing repo `yieldchaser/CFTC-Reports-`, as a new file
`index.html` (and supporting assets), sitting alongside the existing
Weather Desk pages already deployed there.

The dashboard replicates and significantly improves upon three existing
Excel workbooks:
- `Nat_Gas_CFTC_-_Managed_Money.xlsm`
- `Nat_Gas_CFTC_-_Swap_Dealers.xlsm`
- `Nat_Gas_CFTC_-_Producers.xlsm`

All three workbooks share identical structure. The only difference is
which CFTC position column is tracked per workbook.

---

## Build Philosophy

Build in strict phases. Do not proceed to the next phase until the current
phase is verified working. At the end of each phase, print a clear
PHASE COMPLETE checkpoint with exactly what was verified. If something
does not match expected output, fix it before continuing — do not paper
over it with a workaround and move on.

---

## Architecture Overview

```
Data Sources
├── CFTC Public API  →  https://publicreporting.cftc.gov/resource/72hh-3qpy.csv
│     (one fetch, all three trader categories in same row)
└── NG Price CSV     →  https://raw.githubusercontent.com/yieldchaser/
                        nat-gas-data-pipeline/main/data/nat_gas_continuous.csv

GitHub Actions (weekly, every Friday 16:00 ET)
└── scripts/update_cftc_data.py
      ├── Fetches CFTC API
      ├── Fetches price CSV
      ├── Computes all derived columns
      └── Writes  data/cftc_processed.json

GitHub Pages
└── index.html  →  fetches data/cftc_processed.json  →  renders all charts
```

The HTML page is fully static. It reads one pre-built JSON file. There are
no API calls from the browser. This is critical — the CFTC API does not
allow CORS from browser requests.

---

## Phase 1 — Python Data Pipeline

### File: `scripts/update_cftc_data.py`

#### 1.1  Fetch CFTC data

Fetch this exact URL (same as Excel Power Query):
```
https://publicreporting.cftc.gov/resource/72hh-3qpy.csv
  ?commodity_name=NATURAL%20GAS
  &$limit=20000
  &$order=report_date_as_yyyy_mm_dd%20DESC
```

Use `requests` with a 60-second timeout and retry logic (3 attempts,
exponential backoff). If all retries fail, exit with a non-zero code so
the GitHub Action shows a failure — do not silently produce empty data.

After loading into a pandas DataFrame, immediately verify:
- Row count is > 500 (if not, the API likely returned an error page)
- Column `market_and_exchange_names` exists
- Column `report_date_as_yyyy_mm_dd` exists

If any check fails, raise an exception with a descriptive message.

#### 1.2  The 9 instruments and their exact market name filters

This is critical — these strings must match exactly, character for
character, including capitalisation and spacing:

```python
INSTRUMENTS = {
    "nat_gas_nyme":          "NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE",
    "nat_gas_ld1":           "NAT GAS ICE LD1 - ICE FUTURES ENERGY DIV",
    "nat_gas_ice_pen":       "NAT GAS ICE PEN - ICE FUTURES ENERGY DIV",
    "henry_hub_nyme":        "HENRY HUB - NEW YORK MERCANTILE EXCHANGE",
    "hh_last_day":           "HENRY HUB LAST DAY FIN - NEW YORK MERCANTILE EXCHANGE",
    "hh_penult_fin":         "HENRY HUB PENULTIMATE FIN - NEW YORK MERCANTILE EXCHANGE",
    "hh_penult_nat_gas":     "HENRY HUB PENULTIMATE NAT GAS - NEW YORK MERCANTILE EXCHANGE",
    "hh_index_ice":          "HENRY HUB INDEX - ICE FUTURES ENERGY DIV",
    "hh_basis_ice":          "HENRY HUB BASIS - ICE FUTURES ENERGY DIV",
}
```

For each instrument, filter the main DataFrame to rows matching that
market name. After filtering, verify the filtered DataFrame is non-empty.
If any instrument returns zero rows, log a warning but continue — do not
crash. Include the instrument key in a `warnings` list that gets written
into the output JSON.

#### 1.3  The three trader category columns

**WARNING — exact column names matter. These are the actual CFTC schema names:**

```python
TRADER_COLUMNS = {
    "managed_money": {
        "long":  "m_money_positions_long_all",
        "short": "m_money_positions_short_all",
    },
    "swap_dealers": {
        "long":  "swap_positions_long_all",
        "short": "swap__positions_short_all",   # NOTE: double underscore — this is correct
    },
    "producers": {
        "long":  "prod_merc_positions_long",    # NOTE: no _all suffix — this is correct
        "short": "prod_merc_positions_short",   # NOTE: no _all suffix — this is correct
    },
}
```

Also extract `open_interest_all` for every instrument.

#### 1.4  Fetch NG=F price data

Fetch:
```
https://raw.githubusercontent.com/yieldchaser/nat-gas-data-pipeline/main/data/nat_gas_continuous.csv
```

Expected columns: `Date`, `Close`

Parse `Date` column. The CSV uses `DD-MM-YYYY` format — parse accordingly.
Sort ascending by date. Forward-fill any missing price values (do not
leave NaN in price — a missing price day should carry the previous day's
close).

#### 1.5  Date alignment

CFTC data is weekly, released every Tuesday (covering the prior week).
The price data is daily. To align them:

- Parse `report_date_as_yyyy_mm_dd` as a date
- For each CFTC row date, find the closest available price date that is
  <= the CFTC report date using `pd.merge_asof` (merge on nearest past
  date). This is the correct approach — do not use a simple VLOOKUP-style
  exact match, as there will be date gaps.

After merging, verify that no more than 5% of rows have a null price.
If more than 5% are null, log a warning in the output JSON.

#### 1.6  Derived columns — compute for each instrument × trader

For each instrument and each trader category, compute:

```python
# Core
net_position = long - short
pct_of_oi    = (long + short) / open_interest_all  # handle div-by-zero → None

# Z-score of net_position (rolling, using all history up to that row)
# Minimum 20 observations required — return None if fewer rows available
# Use population std dev (ddof=0), matching Excel's STDEV.P
z_score = (net_position - expanding_mean) / expanding_std

# Price-derived (computed once, shared across all traders)
price_pct_change = price.pct_change()   # week-over-week

# Seasonality flag
season = "Withdrawal" if month in [11, 12, 1, 2, 3] else "Injection"

# Rolling 20-week correlation: price vs net_position
# Return None if fewer than 20 observations
rolling_corr = net_position.rolling(20).corr(price)

# Edge signal (from Managed Money workbook col L)
# Only compute for managed_money trader category
edge = (z_score - z_score.shift(1)) - (price_pct_change * 5)

# Historical percentile rank of net_position vs all history to that date
# Use expanding window: what percentile is today's value vs all prior values
pct_rank = net_position.expanding().rank(pct=True)
```

#### 1.7  NaN / Infinity handling — CRITICAL

Before writing to JSON, replace ALL of the following with `None`
(which serialises to JSON `null`):
- `float('nan')`
- `float('inf')`
- `float('-inf')`
- `numpy.nan`
- `pandas.NaT`

**Do this as an explicit pass over the entire output dictionary before
`json.dumps`. Do not rely on pandas' `.fillna()` alone — check
recursively.** This was the root cause of blank charts in the existing
Weather Desk wind chart bug. Use this helper:

```python
import math

def sanitise(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitise(v) for v in obj]
    return obj
```

Apply `sanitise()` to the entire output dict before serialising.

#### 1.8  Output JSON structure

Write to `data/cftc_processed.json`. Structure:

```json
{
  "meta": {
    "last_updated": "2026-03-21T16:00:00Z",
    "latest_report_date": "2026-03-18",
    "warnings": [],
    "price_source": "yieldchaser/nat-gas-data-pipeline"
  },
  "instruments": {
    "nat_gas_nyme": {
      "label": "Nat Gas NYME",
      "dates": ["2024-01-02", "2024-01-09", ...],
      "price": [2.51, 2.63, ...],
      "open_interest": [123456, ...],
      "season": ["Injection", "Injection", ...],
      "managed_money": {
        "long":       [...],
        "short":      [...],
        "net":        [...],
        "pct_of_oi":  [...],
        "z_score":    [...],
        "pct_rank":   [...],
        "edge":       [...],
        "rolling_corr": [...]
      },
      "swap_dealers": {
        "long": [...], "short": [...], "net": [...],
        "pct_of_oi": [...], "z_score": [...], "pct_rank": [...],
        "rolling_corr": [...]
      },
      "producers": {
        "long": [...], "short": [...], "net": [...],
        "pct_of_oi": [...], "z_score": [...], "pct_rank": [...],
        "rolling_corr": [...]
      }
    },
    ... (repeat for all 9 instruments)
  }
}
```

All arrays within an instrument must be the same length and in the same
date order (ascending). Verify this before writing.

#### 1.9  Phase 1 verification checklist

Run the script locally and confirm:
- [ ] JSON file is produced without errors
- [ ] All 9 instrument keys are present
- [ ] `nat_gas_nyme` has > 200 date entries
- [ ] No `NaN` or `Infinity` strings appear anywhere in the JSON
  (run: `grep -i "nan\|infinity" data/cftc_processed.json` — must return nothing)
- [ ] `latest_report_date` in meta matches the most recent CFTC release
- [ ] `warnings` list is empty (all 9 instruments found data)
- [ ] Spot-check: for `nat_gas_nyme`, managed_money net on the latest date
  matches what you see in the Excel workbook for that same date

**PHASE 1 COMPLETE — do not proceed until all 9 checks pass.**

---

## Phase 2 — GitHub Actions Workflow

### File: `.github/workflows/update_cftc.yml`

```yaml
name: Update CFTC Data

on:
  schedule:
    - cron: '30 21 * * 5'   # Every Friday 21:30 UTC = ~17:30 ET (after CFTC release)
  workflow_dispatch:          # Allow manual trigger from Actions tab

jobs:
  update:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests pandas numpy

      - name: Run CFTC pipeline
        run: python scripts/update_cftc_data.py

      - name: Verify output exists and is non-empty
        run: |
          test -f data/cftc_processed.json
          test $(wc -c < data/cftc_processed.json) -gt 100000

      - name: Commit and push
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/cftc_processed.json
          git diff --staged --quiet || git commit -m "chore: update CFTC data $(date -u +%Y-%m-%d)"
          git push
```

#### Phase 2 verification:
- [ ] Workflow file is valid YAML (run `yamllint` or paste into GitHub
  Actions editor to check syntax)
- [ ] Manually trigger the workflow from the Actions tab
- [ ] Confirm it completes without error
- [ ] Confirm `data/cftc_processed.json` is updated in the repo

**PHASE 2 COMPLETE — do not proceed until workflow runs successfully.**

---

## Phase 3 — HTML Dashboard Shell

### File: `index.html`

Build the page shell first — no charts yet. Get the structure, navigation,
and data loading working.

#### 3.1  Page structure

```
┌─────────────────────────────────────────┐
│  Header: "CFTC Natural Gas Positioning" │
│  Nav tabs: [Overview] [By Instrument]   │
│            [Three-Trader View]          │
├─────────────────────────────────────────┤
│  CURRENT WEEK PANEL (top of page)       │
│  Latest report date | Last updated      │
│  Signal cards: one per instrument       │
│  showing z-score + percentile rank      │
├─────────────────────────────────────────┤
│  DATE FILTER                            │
│  "Show data from: [dropdown]"           │
│  Matches the Excel date filter exactly  │
├─────────────────────────────────────────┤
│  Chart panels (populated in Phase 4+)   │
└─────────────────────────────────────────┘
```

Match the visual style of the existing Weather Desk pages in this repo
(dark theme, same font, same nav style). The CFTC page must feel like it
belongs to the same dashboard suite.

#### 3.2  Data loading

```javascript
let CFTC_DATA = null;

async function loadData() {
    const resp = await fetch('data/cftc_processed.json');
    if (!resp.ok) throw new Error(`Failed to load data: ${resp.status}`);
    CFTC_DATA = await resp.json();

    // Verify expected structure
    const required = ['meta', 'instruments'];
    for (const key of required) {
        if (!CFTC_DATA[key]) throw new Error(`Missing key: ${key}`);
    }

    document.getElementById('last-updated').textContent =
        new Date(CFTC_DATA.meta.last_updated).toLocaleString();
    document.getElementById('latest-report').textContent =
        CFTC_DATA.meta.latest_report_date;

    if (CFTC_DATA.meta.warnings?.length > 0) {
        console.warn('Pipeline warnings:', CFTC_DATA.meta.warnings);
    }

    populateDateFilter();
    renderCurrentWeekPanel();
    // Charts rendered in Phase 4
}

window.addEventListener('DOMContentLoaded', loadData);
```

#### 3.3  Date filter

Populate a `<select>` with all unique dates from `nat_gas_nyme` (the most
complete series). Default to the earliest date (show all data). When the
user changes the selection, re-render all charts using only data from
that date onwards — exactly matching the Excel behaviour.

Store the selected cutoff date in a variable `filterFromDate`. Pass it
to every chart rendering function.

#### 3.4  Instrument labels (display names)

```javascript
const INSTRUMENT_LABELS = {
    nat_gas_nyme:      "Nat Gas NYME",
    nat_gas_ld1:       "Nat Gas LD1",
    nat_gas_ice_pen:   "NAT GAS ICE PEN",
    henry_hub_nyme:    "Henry Hub NYME",
    hh_last_day:       "HH Last Day Fin",
    hh_penult_fin:     "HH Penultimate Fin",
    hh_penult_nat_gas: "HH Penultimate Nat Gas",
    hh_index_ice:      "HH Index ICE",
    hh_basis_ice:      "HH Basis ICE",
};
```

#### Phase 3 verification:
- [ ] Page loads without console errors
- [ ] `last-updated` and `latest-report` fields populate correctly
- [ ] Date filter dropdown populates with correct dates
- [ ] Changing the date filter does not throw an error (charts not yet built)
- [ ] Page matches visual style of existing Weather Desk pages

**PHASE 3 COMPLETE — do not proceed until page loads cleanly.**

---

## Phase 4 — Core Charts (Exact Excel Replicas)

Use **Chart.js** (load from CDN). For each chart, apply the date filter
before passing data to Chart.js.

#### Helper function (use for every chart):

```javascript
function applyDateFilter(dates, ...arrays) {
    const cutoff = new Date(filterFromDate);
    const idx = dates.findIndex(d => new Date(d) >= cutoff);
    const start = idx === -1 ? 0 : idx;
    return {
        dates: dates.slice(start),
        arrays: arrays.map(a => a.slice(start)),
    };
}
```

#### 4.1  Chart type A — Net Position vs Price

One per instrument × one per trader category = 27 charts total, but
build Managed Money first for all 9 instruments, then replicate for
Swap Dealers and Producers.

- Dual Y-axis: left = net position (bar/area), right = price (line)
- Net position bars: green when positive, red when negative
- Price line: white/light colour
- Tooltip: on hover, show date + net position + price + z-score + percentile rank
- This replicates the Excel "Net Position vs Price" chart exactly

#### 4.2  Chart type B — Price vs Net Long

Scatter chart: X = net long (long positions only), Y = price.
Colour-code points by season (Withdrawal = blue, Injection = orange).
On hover: date + net long + price.

This replicates the Excel "Price vs Net Long" chart.

#### 4.3  Synced crosshair across charts

When the user hovers over any chart, draw a vertical line at that date
position on every other chart simultaneously. Implement using Chart.js
plugin pattern:

```javascript
const syncPlugin = {
    id: 'syncCrosshair',
    afterDraw(chart) { /* draw vertical line at activeIndex */ }
};
```

Register all charts in a global array `ALL_CHARTS`. On `onHover` in any
chart, call `chart.update()` on all others.

#### Phase 4 verification:
- [ ] All 27 Net Position vs Price charts render for all 9 instruments
- [ ] All 27 Price vs Net Long charts render
- [ ] Dual axis scales are correct (net position on left, price on right)
- [ ] Date filter correctly trims chart data when changed
- [ ] Crosshair syncs across all visible charts
- [ ] Hover tooltips show all four fields
- [ ] Spot-check: Net position values on the latest date match Excel

**PHASE 4 COMPLETE — do not proceed until all charts render and verify.**

---

## Phase 5 — New Features (Not Possible in Excel)

Build these one at a time. Verify each before adding the next.

#### 5.1  Three-Trader Overlay Chart

For each of the 9 instruments, one chart with three lines:
- Managed Money net position (blue line)
- Swap Dealers net position (orange line)
- Producers net position (green line)

All three on the same Y-axis. Price on secondary Y-axis.

This is the single most valuable chart in the entire dashboard — it shows
at a glance who is adding, who is reducing, and who is opposing. Build
this for all 9 instruments.

Verify: all three lines appear, legend is correct, tooltip shows all
three values + price on hover.

#### 5.2  Positioning Heatmap

A matrix: rows = 9 instruments, columns = last 52 weeks.
Cell colour = z-score of managed money net position.
Colour scale: deep red (z < -2) → white (z = 0) → deep green (z > +2).

Use HTML `<canvas>` or a CSS grid — do not use a charting library for
this, render it directly for performance.

On hover: show instrument + date + z-score + raw net position.
On click: jump to that instrument's chart section.

Verify: 9 × 52 grid renders, colours map correctly to z-score values,
most recent week is rightmost column.

#### 5.3  Current Week Signal Panel

At the top of the page, a card for each of the 9 instruments showing
the most recent week's data:

```
┌─ Nat Gas NYME ──────────────────────┐
│  MM Net: +87,432     ▲ +12,341 wow  │
│  Z-Score: +1.84      📊 89th pctile  │
│  Swap Net: -45,210                  │
│  Prod Net: -23,100                  │
│  Price: $2.84        ▲ +3.2% wow    │
│  Season: Injection                  │
│  [SIGNAL: MM EXTENDED LONG]         │
└─────────────────────────────────────┘
```

Signal logic:
- `MM EXTENDED LONG`:  z_score > +1.5 and pct_rank > 0.80
- `MM EXTENDED SHORT`: z_score < -1.5 and pct_rank < 0.20
- `MM vs PROD DIVERGENCE`: mm_net > 0 and prod_net < 0 and both
  abs(z_scores) > 1.0 (historically highest-signal configuration)
- `NEUTRAL`: everything else

Cards are colour-coded: green border for bullish signal, red for bearish,
yellow for divergence, grey for neutral.

Verify: all 9 cards render, signal labels are correct for latest week,
week-over-week arrows point correct direction.

#### 5.4  Weekly Change Table

A sortable table below the signal cards:

| Instrument | MM Net | MM Δ wow | MM Z | Swap Net | Swap Δ | Prod Net | Prod Δ | Price | Price Δ |
|---|---|---|---|---|---|---|---|---|---|

Colour-code the Δ columns: green = increasing long, red = decreasing.
Click any column header to sort. Default sort: largest absolute MM change first.

Verify: table renders all 9 rows, sort works on all columns, values
match the signal cards.

#### 5.5  Rolling Correlation Chart

For each instrument, a chart showing the 20-week rolling correlation
between price and managed money net position over time.

Add a horizontal reference line at 0.
Add a shaded band: when correlation > +0.4 = "Trending regime" (green shade),
when correlation < -0.4 = "Mean-reverting regime" (red shade).

This surfaces the regime indicator that was buried in the Excel `M` column.

Verify: correlation values are between -1 and +1, regime shading appears
correctly, null values at the start (< 20 weeks) are handled gracefully.

#### 5.6  Historical Percentile Panel

For the currently selected instrument (add a selector), show a bar chart
of percentile ranks for all three trader categories:
- X-axis: 0% to 100%
- Three horizontal bars: MM, Swap Dealers, Producers
- Current value marked with a line
- Background zones: 0-20% (red, historically short), 80-100% (green, historically long)

Verify: bars display correctly, zones are correctly shaded, values
update when the instrument selector changes.

---

## Phase 6 — Polish & Deployment

#### 6.1  Navigation

Three-tab navigation at the top:
- **Overview**: Current week panel + heatmap + weekly change table
- **By Instrument**: All charts for one instrument at a time
  (instrument selector dropdown)
- **Three-Trader View**: Three-trader overlay charts for all 9 instruments

Switching tabs must not reload data — just show/hide sections.

#### 6.2  Performance

The JSON file will be ~2-5 MB. Apply these optimisations:
- Round all floats to 4 decimal places in the Python script before
  writing JSON — this alone cuts file size by ~40%
- On the HTML side, render only the charts in the currently active tab
- Lazy-render charts not in the viewport (use IntersectionObserver)

#### 6.3  Mobile responsiveness

All charts must be readable on a phone (minimum 375px width).
Chart.js handles this natively — ensure `responsive: true` and
`maintainAspectRatio: false` are set on all charts with explicit
container heights.

#### 6.4  Error states

Every data-dependent UI element must have an error state:
- If `data/cftc_processed.json` fails to load: show a banner
  "Data unavailable — pipeline may be running. Last successful update: [date]"
- If an individual chart's data array is empty after date filtering:
  show "No data for selected date range" inside the chart container

#### 6.5  GitHub Pages deployment

GitHub Pages is already configured on this repo — deploying from the
`main` branch at `/ (root)`. No setup needed.

Simply ensure `index.html` is committed to the root of the `main` branch.
The live URL will be: `https://yieldchaser.github.io/CFTC-Reports-/`

Recommended: add a `.nojekyll` file to the repo root to prevent Jekyll
processing interference with plain HTML files.

navigation.

#### Phase 6 verification:
- [ ] All three tabs work without page reload
- [ ] Charts in inactive tabs do not render until tab is activated
- [ ] Page loads in < 3 seconds on a standard connection
- [ ] Mobile layout is usable at 375px width
- [ ] Error banner appears when JSON fetch fails (test by temporarily
  renaming the file)
- [ ] Live GitHub Pages URL loads correctly
- [ ] Navigation link from Weather Desk to CFTC page works

**PHASE 6 COMPLETE — dashboard is live.**

---

## Known Gotchas — Read Before Starting

These are issues discovered during deep analysis of the source Excel
files. Handle each one explicitly:

1. **Double underscore**: `swap__positions_short_all` has TWO underscores
   between `swap_` and `positions`. This is the actual CFTC schema name,
   not a typo. If you use a single underscore you will get a KeyError.

2. **No `_all` suffix on Producers**: `prod_merc_positions_long` and
   `prod_merc_positions_short` do not end in `_all`. All other position
   columns do. Hardcode these names, do not try to derive them.

3. **CFTC API returns JSON not CSV when headers are wrong**: Always pass
   `Accept: text/csv` header, or append `.csv` to the URL as used in
   the Power Query. The URL with `.csv` extension is safer.

4. **Date format in price CSV**: The `nat_gas_continuous.csv` uses
   `DD-MM-YYYY` format, not ISO format. Use `pd.to_datetime(df['Date'],
   format='%d-%m-%Y')`. Do not rely on pandas auto-detection.

5. **CFTC `futonly_or_combined` column**: The CFTC data has both
   futures-only and combined rows for each market. The Excel files use
   combined (`futonly_or_combined == 'C'`). Add a filter for this to
   avoid double-counting.
   Add to each instrument filter:
   ```python
   df[df['futonly_or_combined'] == 'C']
   ```

6. **Z-score minimum observations**: Do not compute z-score when fewer
   than 20 observations are available. Output `null`. The Excel formula
   used `IF(COUNT(G3:G$5000) > 20, ...)` — match this exactly.

7. **NaN in JSON breaks Chart.js**: Chart.js treats `null` as a gap
   (renders nothing for that point) but throws an error on `NaN`.
   Ensure the sanitise() function is applied. This bug caused the blank
   wind chart issue in the existing Weather Desk.

8. **GitHub Pages cache**: After deploying, the JSON file may be cached.
   Add a cache-busting query param to the fetch:
   ```javascript
   fetch(`data/cftc_processed.json?v=${Date.now()}`)
   ```
   Or configure the GitHub Pages workflow to set cache-control headers.

9. **CFTC API rate limiting**: The API is public but can throttle rapid
   repeated requests during development. Add a small sleep between
   retries and do not run the script more than once per minute during
   testing.

10. **Instrument date ranges differ**: Not all 9 instruments have data
    going back equally far. The Henry Hub basis and ICE instruments have
    shorter history than NYME. The heatmap and all multi-instrument views
    must handle jagged date ranges gracefully — do not assume all
    instruments share the same date array.

---

## Final Deliverables Checklist

- [ ] `scripts/update_cftc_data.py` — fully working, handles all 9 instruments
- [ ] `data/cftc_processed.json` — present in repo, < 6 MB, no NaN/Infinity
- [ ] `.github/workflows/update_cftc.yml` — runs every Friday, verified once manually
- [ ] `index.html` — all Phase 4 + Phase 5 features working
- [ ] Live at `https://yieldchaser.github.io/CFTC-Reports-/`
- [ ] Manual trigger of GitHub Action produces updated JSON with correct latest date
