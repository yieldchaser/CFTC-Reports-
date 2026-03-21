# CFTC Dashboard — Round 3 Master Build Prompt

## CRITICAL READING INSTRUCTIONS

Read this entire prompt before writing a single line of code.
This prompt has three parts:

- Part 1: What to fix and build (the spec)
- Part 2: How to build it without hitting token limits (the strategy)
- Part 3: The exact execution order

Acknowledge all three parts before starting. Do not begin execution
until you have confirmed understanding of the full prompt.

---

# PART 1 — SPEC: WHAT TO FIX AND BUILD

---

## Section A — 5 Bugs to Fix First

Fix all five bugs before touching any new feature. Do not proceed to
features until the bug fix verification checklist passes.

---

### Bug 1 — Character encoding corruption (fix this first, it affects everything)

Every heading, nav label, and subtitle on the page is garbled:
- Nav tabs show: `δΎ"< Overview`, `δΎ"" By Instrument`
- Subtitle: `Commitment of Traders Ā· 9 Instruments`
- Section titles: `Positioning Heatmap â€" MM Z-Score`

**Root cause**: `<meta charset="UTF-8">` is missing or not the first
tag in `<head>`.

**Fix**:
1. Make `<meta charset="UTF-8">` the absolute first tag inside `<head>`
2. Replace all emoji in tab labels with plain text or HTML entities
3. Replace all em dashes with `&mdash;`
4. Replace all middle dots with `&middot;`

**Verify**: Zero garbled characters anywhere on the page after reload.

---

### Bug 2 — Market Concentration chart is completely blank

The Top-4 Trader Concentration chart on the Overview tab shows a legend
but no lines — the chart area is entirely black/empty.

**Fix**:
1. In Python pipeline, print: `df['conc_gross_le_4_tdr_long'].describe()`
   to verify the column has non-null data
2. In JS, add console.log to check if the concentration arrays in JSON
   are populated before the chart renders
3. If data exists but chart doesn't render: fix the Chart.js
   initialisation for that chart (likely a dataset key mismatch)
4. If data is all null: add a fallback message "Concentration data
   unavailable" instead of blank black box

**Verify**: Chart shows two visible lines (blue Top-4 Long, red
Top-4 Short) over time.

---

### Bug 3 — COT Index goes below 0% and above 100%

The COT Index chart Y-axis shows -5% at the bottom and the line
briefly exceeds 100%. This is mathematically impossible for a 0–100
index.

**Fix in Python pipeline** — replace the COT index function with:
```python
def cot_index(series, window):
    rolling_min = series.rolling(window, min_periods=window).min()
    rolling_max = series.rolling(window, min_periods=window).max()
    denom = rolling_max - rolling_min
    index = np.where(
        denom == 0,
        50.0,
        (series - rolling_min) / denom * 100
    )
    index = np.clip(index, 0, 100)
    result = pd.Series(index, index=series.index)
    result[denom.isna()] = np.nan
    return result
```

**Fix in JS**: Set explicit `min: 0, max: 100` on the COT Index
chart Y-axis options.

**Verify**: COT line stays strictly between 0 and 100. Short-history
instruments show null gaps at the start, not 0.

---

### Bug 4 — Percentile bars unlabelled and wrong trader name

Each trader in the Historical Percentile Rank panel shows two bars
with no sub-labels distinguishing them. "Managed" should be "MM".

**Fix**:
- Add sub-labels "Pct Rank" and "COT Index" under each trader's bars
- Rename "Managed" → "MM" to match terminology everywhere else
- Show the COT Index percentage value on the right side of its bar
  (currently only pct rank shows a number)

**Verify**: All bars clearly labelled, values visible for both bars
per trader, "MM / Swap / Producers" naming consistent.

---

### Bug 5 — Signal cards grid leaves large empty gaps

9 cards render as 7 + 2, leaving 5 empty card-sized blank spaces in
the grid. Last card in the first row is visually truncated.

**Fix** — replace the signal cards container CSS with:
```css
.signal-cards-container {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
}
```

**Verify**: All 9 cards fill available width evenly, no gaps, no
truncation.

---

### Bug Fix Verification Checklist

Do not start features until all pass:
- [ ] Zero garbled characters on page (encoding)
- [ ] Concentration chart shows two visible lines
- [ ] COT chart Y-axis strictly 0–100
- [ ] Percentile bars labelled, "MM" not "Managed"
- [ ] 9 cards fill width, no empty gaps

---

## Section B — Instrument Expansion

### Step 1: Run discovery query first

Add this temporary print to the Python pipeline and run it once:

```python
all_markets = df['market_and_exchange_names'].unique()
ng_markets = sorted([m for m in all_markets
                     if 'NAT GAS' in m or 'HENRY HUB' in m
                     or 'NATURAL GAS' in m])
print(f"Available NG markets ({len(ng_markets)}):")
for m in ng_markets:
    count = len(df[df['market_and_exchange_names'] == m])
    print(f"  {count:4d} rows  {m}")
```

Report the full output. Then add every instrument with >= 50 rows
to the `INSTRUMENTS` dict. Update the dashboard header subtitle
dynamically from the JSON meta count — do not hardcode "9 Instruments".

---

## Section C — 8 New Features

Build these only after all bugs are fixed and instrument discovery
is complete. Build one at a time — do not start the next until the
current one is verified.

---

### Feature 1 — Other Reportables as 4th Trader Category

Add to Python pipeline `TRADER_COLUMNS`:
```python
'other_reportables': {
    "long":  "other_rept_positions_long",
    "short": "other_rept_positions_short",
}
```
Compute same derived columns as other traders: net, z_score,
pct_of_oi, pct_rank, cot_index (all three lookbacks), change_long,
change_short, change_net, rolling_corr, extremes.

Add to dashboard:
- Signal cards: "Other Net" row below Prod Net
- Weekly Change table: Other Net + Other Δ columns
- Three-Trader View becomes Four-Trader View: add purple line
- Percentile bars: 4th bar for Other Reportables
- Rename "Three-Trader View" tab → "Multi-Trader View"
- Update header subtitle to "4 Trader Categories"

---

### Feature 2 — MM Spread Positions

Extract `m_money_positions_spread` from CFTC data. Compute:
```python
spread_pct_oi = spread / open_interest_all * 100
spread_change = spread.diff()
```
Add to JSON under managed_money: `spread`, `spread_pct_oi`.

Add to dashboard:
- Signal cards: small "Spread: X,XXX" line
- By Instrument Net Position chart: dotted third line for spread on
  secondary axis
- When spread_pct_oi > 15% and rising: annotate "↑ Spread Activity"

---

### Feature 3 — Non-Reportable (Small Speculator) Tracking

Add to Python pipeline:
```python
'non_reportables': {
    "long":  "nonrept_positions_long_all",
    "short": "nonrept_positions_short_all",
}
```
Compute: net, z_score, pct_rank, cot_index.

Add to composite signal score (contrarian logic):
```python
if nonrept_z > 1.5 and mm_z < 0:   score -= 1
if nonrept_z < -1.5 and mm_z > 0:  score += 1
```

Add to dashboard:
- Signal cards: "Retail Net" row
- New chart in By Instrument: "Smart vs Dumb Money" — MM net (blue)
  vs Non-Reportable net (red dashed) on same chart
- Add to Weekly Change table as Retail Net + Retail Δ columns

---

### Feature 4 — Open Interest Regime Analysis

Add to Python pipeline:
```python
oi_roc_4w = open_interest.pct_change(4) * 100
price_roc_4w = price.pct_change(4) * 100

def oi_regime(oi_roc, price_roc):
    if oi_roc > 3  and price_roc > 0:  return "Accumulation"
    if oi_roc > 3  and price_roc < 0:  return "Distribution"
    if oi_roc < -3 and price_roc < 0:  return "Long Liquidation"
    if oi_roc < -3 and price_roc > 0:  return "Short Covering"
    return "Neutral"
```
Add to JSON per instrument: `oi_roc_4w`, `oi_regime` (array of strings).

Add to dashboard:
- Signal cards: colour-coded OI regime badge below Season field
  (green=Accumulation, red=Distribution, orange=Liquidation/Covering)
- By Instrument: OI as a normalised overlay line on the Net Position
  chart (right axis, light grey)

---

### Feature 5 — Positioning Momentum Score

Add to Python pipeline:
```python
momentum_raw = abs(change_net) / change_net.rolling(13).std()
momentum_score = momentum_raw.expanding().rank(pct=True) * 100
```
Clip to 0–100. Add to JSON per instrument/trader: `momentum_score`.

Add to dashboard:
- Weekly Change table: "Momentum" column with colour-coded badge
  (>80 = bright highlight, <20 = grey)
- Default table sort: by MM momentum_score descending
- Signal cards: if momentum > 80 this week, add "HIGH ACTIVITY" text
  badge in the card header

---

### Feature 6 — Price Lagged Correlation

Add to Python pipeline:
```python
for lag in [1, 2, 3, 4]:
    future_price_change = price.pct_change().shift(-lag)
    lagged_corr_series = net_position.rolling(20).corr(future_price_change)
    # store as lagged_corr.lag_1w, lag_2w, lag_3w, lag_4w
```
Add to JSON under managed_money per instrument: `lagged_corr` dict.

Add to dashboard (By Instrument, new chart below seasonal overlay):
Title: "Positioning Lead/Lag Analysis"
Four lines: 1w, 2w, 3w, 4w leads. Y-axis: -1 to +1.
Add a text label showing current dominant lag:
"Positioning leads price by ~Xw" when lag_Xw has highest abs value.

---

### Feature 7 — Report Freshness Display

Add to dashboard JS (no pipeline change needed):
```javascript
const reportDate = new Date(CFTC_DATA.meta.latest_report_date);
const daysSince = (new Date() - reportDate) / 86400000;
const lastUpdated = new Date(CFTC_DATA.meta.last_updated);
const daysSinceUpdate = (new Date() - lastUpdated) / 86400000;

if (daysSince > 14 || daysSinceUpdate > 8) {
    showStalenessBanner(
        `Data may be stale — last report: ${meta.latest_report_date}
         (${Math.round(daysSince)} days ago)`
    );
}
```
Banner: yellow background, shown just below the header bar.
Also add "Report date: YYYY-MM-DD" as a small text line in each
signal card below the Season field.

---

### Feature 8 — UX Polish (build all together as one small task)

8a. Heatmap trader toggle: add `[MM] [Swap] [Prod] [Other]` buttons
    above heatmap. Re-render cells using selected trader's z_score.

8b. Heatmap time range: add `[13w] [26w] [52w] [All]` selector.

8c. Correlation matrix time period: add `[13w] [26w] [52w] [3yr]`
    selector. Recompute JS-side from the time series data.

8d. Chart titles show current values: e.g. "Net Position vs Price —
    Net: -44,628 | Price: $3.03" (read from latest data point).

8e. Keyboard nav in By Instrument: `←`/`→` arrows cycle instruments,
    `1`–`9` keys jump directly to each.

---

# PART 2 — STRATEGY: HOW TO BUILD WITHOUT HANGING

## The token limit problem

Every time the agent tries to write the complete index.html in one
response it hits the token limit and produces a truncated, broken file.
The solution is to never write the full file in a single response.

## The solution: pipeline files first, then HTML in chunks

### Phase A — Python pipeline changes (do these first)

The Python file `scripts/update_cftc_data.py` is a single file that
can be edited in sections using str_replace tool calls. It does NOT
need chunking because each change is a targeted edit.

Do pipeline changes in this order:
1. Run instrument discovery query — print output, confirm instruments
2. Fix COT Index function (Bug 3)
3. Add Other Reportables trader columns (Feature 1)
4. Add Non-Reportables trader columns (Feature 3)
5. Add MM Spread extraction (Feature 2)
6. Add OI regime calculation (Feature 4)
7. Add Momentum score calculation (Feature 5)
8. Add Lagged correlation calculation (Feature 6)
9. Add new instruments from discovery output to INSTRUMENTS dict
10. Run the pipeline: `python scripts/update_cftc_data.py`
11. Verify output:
    - `grep -c "nan\|Infinity" data/cftc_processed.json` → 0
    - All new fields present in JSON
    - File size grown but still under 8 MB

Do NOT touch index.html until the pipeline passes verification.

### Phase B — HTML in 7 chunks

Write index.html as 7 separate chunk files, then concatenate.
Each chunk is one tool call. Do not combine chunks.

```
build_chunks/
  chunk1_head_css.html         ← <!DOCTYPE> through </style>
  chunk2_body_structure.html   ← <body> through all container divs
  chunk3_js_data_utils.html    ← <script> + data loading + constants + utilities
  chunk4_js_overview.html      ← renderSignalCards, renderHeatmap,
                                  renderCorrelationMatrix,
                                  renderConcentrationChart,
                                  renderWeeklyTable
  chunk5_js_by_instrument.html ← renderInstrumentPills, renderNetPosChart,
                                  renderScatterChart, renderCorrelationChart,
                                  renderPercentileBars, renderSeasonalChart,
                                  renderFlowChart, renderLaggedCorrChart,
                                  renderSmartDumbChart
  chunk6_js_multitrader.html   ← renderMultiTraderGrid, syncCrosshair plugin,
                                  downloadCSV, renderOIRegime
  chunk7_js_init.html          ← initDashboard, all event listeners,
                                  staleness banner, keyboard nav,
                                  </script></body></html>
```

After all 7 chunks are written, concatenate:
```bash
cat build_chunks/chunk1_head_css.html \
    build_chunks/chunk2_body_structure.html \
    build_chunks/chunk3_js_data_utils.html \
    build_chunks/chunk4_js_overview.html \
    build_chunks/chunk5_js_by_instrument.html \
    build_chunks/chunk6_js_multitrader.html \
    build_chunks/chunk7_js_init.html \
    > index.html
```

### Chunk writing rules

1. One chunk per tool call — never combine two chunks
2. After writing each chunk, immediately read back the last 20 lines
   to verify it was saved correctly
3. If a chunk is still too large: split it (chunk5a, chunk5b) —
   never abbreviate or stub out code
4. Do not close the `<script>` tag until chunk7
5. Each chunk must end with a `// === END CHUNK N ===` comment so
   the boundary is clear

### Post-concatenation verification

Run all of these. If any fails, identify which chunk to fix:

```bash
# 1. File is substantial
wc -c index.html
# Expected: > 120,000 bytes

# 2. Balanced script tags
python3 -c "
c = open('index.html').read()
o, cl = c.count('<script'), c.count('</script>')
print(f'script: {o} open, {cl} close')
assert o == cl, 'MISMATCH'
print('OK')
"

# 3. Balanced div tags
python3 -c "
c = open('index.html').read()
o, cl = c.count('<div'), c.count('</div>')
print(f'div: {o} open, {cl} close')
assert abs(o - cl) < 5
print('OK')
"

# 4. Encoding fix present
grep -c 'charset=\"UTF-8\"' index.html
# Expected: 1

# 5. Bug fixes present
grep -c 'auto-fill' index.html               # Bug 5 grid fix
grep -c 'nonrept\|non_reportables' index.html  # Feature 3
grep -c 'momentum_score' index.html            # Feature 5
grep -c 'lagged_corr' index.html               # Feature 6
grep -c 'oi_regime' index.html                 # Feature 4
grep -c 'staleness\|stale' index.html          # Feature 7
# All expected: > 0

# 6. No garbled characters
python3 -c "
import re
c = open('index.html').read()
garbled = re.findall(r'[δΎ]|Ā·|â€"', c)
print(f'Garbled chars found: {len(garbled)}')
assert len(garbled) == 0, f'GARBLED: {garbled[:5]}'
print('OK')
"

# 7. No TODO stubs
grep -i 'todo\|fixme\|coming soon\|placeholder' index.html | wc -l
# Expected: 0
```

---

# PART 3 — EXECUTION ORDER

Follow this sequence exactly. Do not skip steps.

## Step 1 — Acknowledge
Read the full prompt. Reply with:
- List of 5 bugs understood
- List of 8 features understood
- Confirmation of chunked build strategy understood
Do not write any code in this step.

## Step 2 — Pipeline: discovery
Run the instrument discovery query. Print full output.
Decide which instruments to add based on row counts.

## Step 3 — Pipeline: bug fixes
Fix Bug 3 (COT index) in the Python file using str_replace.
Run pipeline. Verify JSON. Check COT values are 0–100.

## Step 4 — Pipeline: new trader categories
Add Other Reportables, Non-Reportables, MM Spread, OI Regime,
Momentum, Lagged Correlation to the pipeline.
Run pipeline. Verify all new fields exist in JSON.
Run: `grep -c "nan\|Infinity" data/cftc_processed.json` → must be 0.

## Step 5 — HTML: Chunk 1 (head + CSS)
Write `build_chunks/chunk1_head_css.html`.
Include the Bug 5 grid fix (`auto-fill`) and encoding meta tag.
Read back last 20 lines to verify.

## Step 6 — HTML: Chunk 2 (body structure)
Write `build_chunks/chunk2_body_structure.html`.
All container divs for all new features must have placeholder divs.
Read back last 20 lines to verify.

## Step 7 — HTML: Chunk 3 (JS data + utils)
Write `build_chunks/chunk3_js_data_utils.html`.
Include updated TRADER_KEYS with other_reportables and non_reportables.
Include updated INSTRUMENT_LABELS with any new instruments.
Read back last 20 lines to verify.

## Step 8 — HTML: Chunk 4 (Overview JS)
Write `build_chunks/chunk4_js_overview.html`.
Include Bug 5 grid fix in renderSignalCards.
Include Bug 2 fix (concentration chart error handling).
Include Bug 4 fix (percentile bar labels, "MM" naming).
Read back last 20 lines to verify.

## Step 9 — HTML: Chunk 5 (By Instrument JS)
Write `build_chunks/chunk5_js_by_instrument.html`.
All existing charts plus new: lagged corr, smart/dumb money.
If too large, split into chunk5a and chunk5b.
Read back last 20 lines to verify.

## Step 10 — HTML: Chunk 6 (Multi-Trader JS)
Write `build_chunks/chunk6_js_multitrader.html`.
Four-trader grid (not three), OI regime, CSV export.
Read back last 20 lines to verify.

## Step 11 — HTML: Chunk 7 (init + event wiring)
Write `build_chunks/chunk7_js_init.html`.
Staleness banner, keyboard nav, all event listeners, closing tags.
Read back last 20 lines to verify.

## Step 12 — Concatenate
Run the cat command. Verify file size > 120KB.

## Step 13 — Run all verification checks
Run every check from Part 2. Fix any failures by rewriting only
the responsible chunk and re-concatenating. Do not rewrite all chunks.

## Step 14 — Commit
```bash
git add data/cftc_processed.json index.html
git commit -m "feat: round 3 — 5 bug fixes, 4 traders, 8 new features"
git push
```

## Step 15 — Confirm live
Verify `https://yieldchaser.github.io/CFTC-Reports-/` loads correctly.
Confirm zero garbled characters. Confirm concentration chart visible.
Confirm COT index within 0–100. Confirm 4 trader categories present.
