# CFTC Dashboard — Bug Fixes + Enhancements Prompt

## Context

The base dashboard at `https://yieldchaser.github.io/CFTC-Reports-/` is
live and working. This prompt covers four confirmed bugs to fix first,
followed by a set of enhancements that make the system genuinely
world-class. Build and verify each section before moving to the next.

---

## Part 1 — Bug Fixes (fix all four before touching enhancements)

### Bug 1 — Heatmap renders as a thin vertical strip

**Symptom**: The 9×52 positioning heatmap shows only a ~40px wide
column of coloured cells on the left edge. All 52 weeks collapse into
one column. Only "Nat Gas NYME" has a row label.

**Root cause**: The CSS grid or canvas is not computing its horizontal
width. The cells exist but have zero or near-zero width.

**Fix**:
- If using CSS grid: ensure the heatmap container has `width: 100%` and
  `overflow-x: auto`. Set cells explicitly:
  `grid-template-columns: 120px repeat(52, 1fr)` where 120px is the
  row label column.
- If using `<canvas>`: ensure the canvas element width is set from
  `canvas.offsetWidth` (reading the layout width) not `canvas.width`
  (which defaults to 300px). Set `canvas.width = canvas.offsetWidth`
  before drawing.
- All 9 instrument rows must have labels on the left.
- Verify: heatmap fills the full container width, all 9 rows visible,
  52 columns visible, hover tooltip shows instrument + date + z-score.

### Bug 2 — NAT GAS ICE PEN signal card shows NEUTRAL incorrectly

**Symptom**: NAT GAS ICE PEN has z-score = -1.50 and percentile = 6th
but the signal card reads NEUTRAL instead of MM EXTENDED SHORT.

**Root cause**: Boundary condition. The signal logic uses strict `<`
and `>` operators so z = -1.50 fails `z < -1.5` by a floating point
hair.

**Fix**: Change all signal threshold comparisons from strict to
inclusive:
```javascript
// WRONG
z_score < -1.5  →  z_score <= -1.5
z_score > +1.5  →  z_score >= +1.5
pct_rank < 0.20 →  pct_rank <= 0.20
pct_rank > 0.80 →  pct_rank >= 0.80
```
Also add a secondary check for the divergence signal: flag it when
`abs(mm_z) >= 1.0` (inclusive).

Verify: NAT GAS ICE PEN card shows MM EXTENDED SHORT with red border
after fix.

### Bug 3 — Three-Trader View Y-axis scale crush

**Symptom**: On instruments like Nat Gas LD1 and Henry Hub NYME,
Producers positions (2–4 million contracts) are orders of magnitude
larger than MM (tens of thousands). All three lines share one Y-axis,
making MM and Swap completely unreadable — flat lines near zero.

**Fix**: Add a toggle button on each Three-Trader chart:
`[Raw Contracts] [% of Open Interest]`

- **Raw Contracts mode** (current): Use independent Y-axis per trader.
  Chart.js supports multiple Y-axes — assign MM to `y` axis, Swap to
  `y1` axis (hidden, right side), Producers to `y2` axis (hidden).
  Each line auto-scales independently. Only the MM left axis label is
  shown to avoid clutter.
- **% of OI mode**: Divide each trader's net position by
  `open_interest_all` for that instrument. All three series then occupy
  a -1 to +1 scale (or percentage scale). This is the cleaner view for
  comparison. Make this the default.

The toggle persists across all 9 charts simultaneously — changing it
on one chart changes all nine.

Verify: on Nat Gas LD1, all three lines are readable in both modes.
Toggle switches both modes correctly.

### Bug 4 — Trader dropdown visible on wrong tab

**Symptom**: The "Trader: [Managed Money ▼]" dropdown appears in the
filter bar on the Three-Trader View tab, where it makes no sense
(all three traders are always shown simultaneously).

**Fix**: Hide the Trader dropdown when the Three-Trader View tab is
active. Show it only on the By Instrument tab. Use a simple CSS class
toggle on tab switch:
```javascript
// On tab switch
document.getElementById('trader-filter').style.display =
    activeTab === 'by-instrument' ? 'block' : 'none';
```

Verify: Trader dropdown invisible on Overview and Three-Trader tabs,
visible and functional on By Instrument tab.

---

## Part 2 — Enhancements

Build these in order. Verify each before proceeding.

---

### Enhancement 1 — COT Index (most important analytical addition)

The COT Index is the single most widely-used professional metric for
interpreting CFTC data. It answers: "Where is current positioning
relative to its own history over a defined lookback window?"

**Formula** (for each instrument × trader):
```
COT_Index = (current_net - min_net_over_N_weeks) /
            (max_net_over_N_weeks - min_net_over_N_weeks) × 100
```
Result is 0–100. Above 80 = historically extended long. Below 20 =
historically extended short.

**Lookback options to support**: 26 weeks, 52 weeks, 3 years (156 weeks).
Default: 3 years.

**Add to Python pipeline** (`scripts/update_cftc_data.py`):
Compute COT index for all three traders for all 9 instruments at all
three lookbacks. Add to the JSON under each instrument/trader:
```json
"cot_index": {
    "w26":  [...],
    "w52":  [...],
    "w156": [...]
}
```

**Add to dashboard**:
- In signal cards (Overview tab): add COT Index (3yr) below z-score.
  Show as a gauge/bar: red zone 0-20, grey 20-80, green 80-100.
- In By Instrument tab: add a COT Index chart (line over time) with
  the 80 and 20 threshold lines marked.
- Update signal logic: if `COT_index_3yr > 80` AND `z_score >= 1.5`
  → signal is now `STRONG EXTENDED LONG` (more conviction than just
  z-score alone). Same for short side.

### Enhancement 2 — Seasonal Positioning Overlay

For each instrument, show how current positioning compares to the
historical average for the same week of year.

**Add to Python pipeline**:
For each instrument × trader, compute:
```python
# For each week-of-year (1-52), compute the average net position
# across all years in the dataset
seasonal_avg[week_of_year] = historical_mean_for_that_week
seasonal_std[week_of_year] = historical_std_for_that_week

# For each row, add:
seasonal_deviation = net_position - seasonal_avg[row.week_of_year]
```

Add `seasonal_avg_by_week` (a 52-element array indexed by week number)
and `seasonal_deviation` (per-row time series) to the JSON.

**Add to dashboard** (By Instrument tab):
A new chart below the existing ones:
- Line: current year's net position (bold, coloured)
- Shaded band: historical seasonal average ± 1 std dev (grey band)
- When the current line exits the grey band = positioning is abnormal
  for this time of year.
- Add a year selector to overlay prior years (2022, 2023, 2024, 2025,
  2026) as thinner lines on the same chart.

### Enhancement 3 — Change in Open Interest Analysis

The CFTC data includes `change_in_open_interest_all` and
`change_in_m_money_long_all`, `change_in_m_money_short_all` (and
equivalents for swap/producers). These are the week-over-week changes
as reported by CFTC directly — more accurate than computing your own
difference.

**Add to Python pipeline**:
Extract these change columns for all traders for all instruments:
```python
CHANGE_COLUMNS = {
    "managed_money": {
        "change_long":  "change_in_m_money_long_all",
        "change_short": "change_in_m_money_short_all",
    },
    # (swap and producers have equivalent change_ columns in the CFTC schema)
}
```
Add to JSON under each instrument/trader: `change_long`, `change_short`,
`change_net` (computed: change_long - change_short).

**Add to dashboard**:
- In Weekly Change Summary table: the existing `MM Δwow` column is
  currently computed. Replace it with the CFTC-reported change value
  (more accurate).
- In By Instrument tab: add a "Weekly Flow" bar chart showing
  `change_net` as green/red bars over time. This shows the weekly
  buying/selling flow, not the cumulative position. It is a leading
  indicator vs the net position level.

### Enhancement 4 — Concentration Data

The CFTC data includes trader concentration metrics that very few
dashboards surface:
- `conc_gross_le_4_tdr_long`: % of open interest held by top 4 traders (long)
- `conc_gross_le_4_tdr_short`: % of open interest held by top 4 traders (short)
- `conc_gross_le_8_tdr_long`: top 8 traders long
- `conc_gross_le_8_tdr_short`: top 8 traders short

**Add to Python pipeline**:
Extract these 4 columns for the `nat_gas_nyme` instrument (most liquid,
most meaningful for concentration). Add to JSON under `nat_gas_nyme`:
```json
"concentration": {
    "top4_long":  [...],
    "top4_short": [...],
    "top8_long":  [...],
    "top8_short": [...]
}
```

**Add to dashboard** (Overview tab, new section below heatmap):
A chart titled "Market Concentration — Nat Gas NYME":
- Two lines: Top 4 Long % and Top 4 Short %
- When concentration is rising = fewer, larger players dominating.
  High concentration short = large traders heavily short = potential
  squeeze risk if they need to cover.
- Add a simple annotation: when top4_short > 50% → label "Concentrated
  Short" marker on the chart.

### Enhancement 5 — Multi-Instrument Correlation Matrix

A heatmap showing the 52-week rolling correlation between net positions
across all 9 instruments.

**Add to Python pipeline**:
Compute the correlation matrix: for each pair of instruments, compute
the Pearson correlation of their managed money net positions over the
last 52 weeks. Output a 9×9 symmetric matrix.

```json
"correlation_matrix": {
    "instruments": ["nat_gas_nyme", "nat_gas_ld1", ...],
    "matrix": [[1.0, 0.87, ...], [0.87, 1.0, ...], ...],
    "as_of_date": "2026-03-17"
}
```

**Add to dashboard** (Overview tab, new section):
A 9×9 correlation heatmap (not the z-score heatmap — this is a
separate, smaller matrix). Colour: deep blue = -1, white = 0,
deep green = +1. On hover: show the two instrument names and
correlation value.

Why this is useful: when previously correlated instruments diverge,
it often signals one of them is mispriced. This is a quantitative
signal most retail CFTC dashboards completely miss.

### Enhancement 6 — Improved Signal Logic

The current signal system only uses MM z-score and percentile rank.
Upgrade it to a multi-factor composite score.

**Composite signal score** (compute in Python pipeline, add to JSON):
```python
# For each instrument, compute a score from -3 to +3:
score = 0
if z_score >= 1.5:  score += 1
if z_score >= 2.0:  score += 1
if cot_index_3yr >= 80: score += 1
if z_score <= -1.5: score -= 1
if z_score <= -2.0: score -= 1
if cot_index_3yr <= 20: score -= 1

# Divergence bonus: add 1 point if MM and Producers are on opposite
# extremes (abs z-score > 1.0 each, opposite signs)
if mm_z > 1.0 and prod_z < -1.0: score += 1  # MM bullish, Prod hedging
if mm_z < -1.0 and prod_z > 1.0: score -= 1

# Add to JSON per instrument:
# "composite_score": -3 to +3
```

**Signal labels by score**:
- +3: STRONG BULLISH SETUP
- +2: BULLISH POSITIONING
- +1: MILD BULLISH BIAS
- 0:  NEUTRAL
- -1: MILD BEARISH BIAS
- -2: BEARISH POSITIONING
- -3: STRONG BEARISH SETUP

Update signal cards to show this composite score with a colour gradient
(deep green at +3, deep red at -3) and the score number prominently.

### Enhancement 7 — Data Export

On every chart in the By Instrument tab, add a small download icon
button in the top-right corner of the chart container. Clicking it
downloads the chart's underlying data as a CSV with columns:
Date, Long, Short, Net, Price, Z-Score, COT_Index, Pct_Rank.

Date range respects the current date filter.

Implementation: pure JavaScript, no server needed.
```javascript
function downloadCSV(instrumentKey, traderKey) {
    const inst = CFTC_DATA.instruments[instrumentKey];
    const trader = inst[traderKey];
    const rows = [['Date','Long','Short','Net','Price','Z-Score','COT_Index','Pct_Rank']];
    inst.dates.forEach((d, i) => {
        rows.push([d, trader.long[i], trader.short[i], trader.net[i],
                   inst.price[i], trader.z_score[i],
                   trader.cot_index?.w156?.[i], trader.pct_rank[i]]);
    });
    const csv = rows.map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], {type: 'text/csv'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${instrumentKey}_${traderKey}_cftc.csv`;
    a.click();
}
```

### Enhancement 8 — Historical Extremes Marker

On every Net Position vs Price chart (By Instrument tab), mark the
historical maximum long, historical maximum short, and current value
with annotations:

- A horizontal dashed line at the all-time max long with label
  "ATH Long: +XXX,XXX (YYYY-MM-DD)"
- A horizontal dashed line at the all-time max short with label
  "ATH Short: -XXX,XXX (YYYY-MM-DD)"
- A small triangle marker on the most recent data point

This gives immediate visual context for how extreme current positioning
is in absolute historical terms — complementing the z-score which is
relative.

**Add to Python pipeline**: compute per instrument/trader:
```json
"extremes": {
    "max_long_value": 287432,
    "max_long_date":  "2023-05-09",
    "max_short_value": -198234,
    "max_short_date":  "2022-08-30"
}
```

---

## Part 3 — Final Verification Checklist

After all bugs and enhancements are complete:

- [ ] Heatmap fills full width, all 9 rows labelled, all 52 columns visible
- [ ] NAT GAS ICE PEN shows MM EXTENDED SHORT (not NEUTRAL)
- [ ] Trader dropdown hidden on Three-Trader and Overview tabs
- [ ] Three-Trader charts readable on all 9 instruments in both modes
- [ ] COT Index appears in signal cards and By Instrument tab
- [ ] Composite score -3 to +3 shown on all signal cards
- [ ] Seasonal overlay chart works, year selector functional
- [ ] Weekly Flow (change_net) bars render correctly
- [ ] Concentration chart visible on Overview tab
- [ ] Correlation matrix 9×9 renders on Overview tab
- [ ] CSV export button on each By Instrument chart
- [ ] Historical extremes lines visible on Net Position charts
- [ ] Python pipeline produces updated JSON with all new fields
- [ ] GitHub Actions workflow still passes after pipeline changes
- [ ] No NaN/Infinity in new JSON fields
  (grep -i "nan\|infinity" data/cftc_processed.json → nothing)
- [ ] Page load time still under 3 seconds
