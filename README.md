# Blue Pulse — COT Positioning Intelligence

A professional-grade terminal for visualizing and analyzing Commitment of Traders (COT) data across US Natural Gas markets. Built as a single-page application, it transforms raw weekly CFTC reports into institutional-grade visual analytics — no backend, no build step, no dependencies beyond a browser.

[**Launch the Live Dashboard →**](https://yieldchaser.github.io/CFTC-Reports-/)

---

## Features

### Overview Tab
Command center across all 10 instruments.

- **Top Signals Banner** — algorithmic highlight of the highest composite-score instruments this week
- **Signal Cards** — per-instrument cards showing MM net (with WoW delta), Z-score + percentile bar, COT 3yr index + bar, Swap/Prod/Other/Retail nets with deltas, OI total + 4wk ROC, MM Edge divergence metric, OI regime, and composite signal label — grouped by contract family with collapsible sections
- **Z-Score Heatmap** — extreme positioning across a selectable lookback (13w / 26w / 52w / All), togglable across all 5 trader categories
- **Correlation Matrix** — live 10×10 Pearson correlation matrix across instruments, selectable over 13w / 26w / 52w / 3yr windows, with high-correlation glow on cells |r| > 0.7
- **Open Interest Leaderboard** — ranked by this week's OI with rank numbers, 4-week change %, and 52-week high %
- **Weekly Change Table** — sortable table: MM net / delta / Z / COT index, composite score, momentum, Swap net / delta, Prod net, Other net, Retail net, price / WoW%, OI 4wk%, OI regime

### By Instrument Tab
Click any instrument pill or signal card to load a full forensic view.

**Stat strip** — single-line summary: Signal, MM Net (Δ), Z-Score, COT 3yr, Momentum, Price (WoW%), OI Regime, Season, MM Edge

**8 sub-charts:**
- **Net Position vs Price** — bar/line overlay with ATH long/short annotations and momentum arrows
- **Price vs Net Long Scatter** — season-coded (Withdrawal / Injection) clustering
- **20-Week Rolling Correlation** — trending (>0.4) and mean-reversion (<−0.4) regime identification, Y-axis labeled
- **Weekly Flow** — week-over-week net change, signed and color-coded
- **COT Index** — 3-year percentile (0 = min, 100 = max) with selectable 26w / 52w / 3yr lookback; secondary 26w line when 3yr selected
- **Seasonal Overlay** — current year vs 5-year historical avg ± 1σ, with per-year toggles; Y-axis labeled
- **Lead/Lag Analysis** — rolling correlation at +1 to +4 week lags to detect positioning lead on price; zero-line reference, Y-axis labeled
- **Smart vs Dumb Money** — MM net vs Non-Reportable (retail) net overlaid

**Percentile Rank Bars** — all 5 traders: current-week net, delta arrow, Z-score, momentum, pct-rank bar

### Multi-Trader View Tab
All 10 instruments side-by-side with MM, Swap, Producers, and Other Reportables on one chart each.

- **Sort toggle** — Signal Strength (default: |composite score| descending) or A–Z alphabetical
- **Scale toggle** — % of Open Interest (normalized, single Y-axis) or Raw (independent axes)
- **Per-card header** — composite score badge, MM % of OI, Swap % of OI, OI regime
- Price overlaid as a secondary axis on every chart

### Interactive Controls
- **Date range** — dropdown presets (1y / 2y / 3y / 5y / all) + drag slider for precise start date
- **Trader filter** — per-instrument tab filter (MM / Swap / Prod / Other / Retail)
- **Zoom + pan** — mouse-wheel zoom and horizontal pan on every chart; Reset button per chart
- **Tooltips** — hover-only, context-sensitive tooltips on every metric, chart, button, and label; plain-text institutional descriptions
- **Instrument search** — fuzzy-filter instrument pills by name
- **Keyboard navigation** — Arrow keys / 1–9 to cycle instruments; pill elements have `:focus-visible` ring
- **CSV export** — download current instrument + trader as CSV

---

## Project Structure

```
CFTC-Reports-/
├── .github/
│   └── workflows/
│       └── update_cftc.yml     # 3-window retry schedule (Fri / Sat / Mon)
├── data/
│   └── cftc_processed.json     # Auto-generated data payload (~1.7 MB)
├── scripts/
│   └── update_cftc_data.py     # Data pipeline: fetch → staleness check → process → write
├── index.html                  # Entire dashboard UI (Vanilla JS + Chart.js)
├── favicon.svg                 # Custom SVG bar-chart favicon
├── favicon.png
├── .nojekyll                   # Required for GitHub Pages to serve correctly
└── README.md
```

---

## Data Pipeline

`scripts/update_cftc_data.py` runs automatically via GitHub Actions on a resilient 3-window schedule to handle CFTC publication delays and holidays.

**Schedule:**
| Window | Time (UTC) | Purpose |
|--------|------------|---------|
| Primary | Friday 21:30 | Normal — CFTC releases ~21:00 UTC |
| Retry 1 | Saturday 03:30 | Catches late Friday releases |
| Retry 2 | Monday 15:30 | Catches multi-day holiday delays |

**Staleness check:** On startup the script compares the incoming CFTC data's latest date against `meta.latest_report_date` in the existing JSON. If CFTC hasn't published new data yet, it exits immediately (sets `new_data=false`) and the commit step is skipped — no false commits on retry runs.

**Processing steps:**
1. **Fetch** — pulls public COT disaggregated futures data from `publicreporting.cftc.gov`
2. **Filter** — selects the 10 Natural Gas instrument codes by CFTC market name
3. **Compute** — for each of 5 trader categories: net position, weekly change, Z-scores, percentile rank, COT index (26w/52w/3yr), 20-week rolling correlation, lagged correlations (1–4w), momentum score, seasonal avg/std by week, edge metric (positioning momentum divergence), OI regime classification, historical extremes
4. **Composite score** — −3 to +3 signal from Z-score + COT index + confirming factors (regime, momentum)
5. **Correlation matrix** — 10×10 Pearson correlation across all instruments
6. **Output** — writes `data/cftc_processed.json`; GitHub Actions commits and pushes → GitHub Pages re-deploys automatically

---

## Signals & Metrics Glossary

| Metric | Description |
|--------|-------------|
| **Z-Score** | Standard deviations from full historical mean. ±1.5 = historically extended; ±2 = rare extreme |
| **COT Index** | Percentile rank within prior 3-year range. ≥80% = crowded long; ≤20% = crowded short |
| **Composite Score** | −3 to +3 algorithmic signal combining Z, COT index, OI regime, and momentum |
| **Momentum Score** | 0–100 flow momentum vs trailing 13-week volatility. >80 = outsized repositioning |
| **MM Edge** | Weekly Z-score change minus price return signal — positive = MM repositioning faster than price implies (potential lead); negative = divergence/exhaustion |
| **OI Regime** | Market structure: Accumulation (OI↑+Price↑), Distribution (OI↑+Price↓), Short Covering (OI↓+Price↑), Long Liquidation (OI↓+Price↓) |
| **Lead/Lag** | Rolling correlation at 1–4w lags — detects whether MM positioning leads or follows price |

---

## Local Development

No Node.js, no bundler, no build step needed.

```bash
# 1. Clone
git clone https://github.com/yieldchaser/CFTC-Reports-.git
cd CFTC-Reports-

# 2. (Optional) Refresh data locally
pip install requests pandas numpy
python scripts/update_cftc_data.py

# 3. Serve (required for CORS — can't open index.html directly as file://)
python -m http.server 8000
# then open http://localhost:8000
```

> **Note:** Opening `index.html` directly as a `file://` URL will fail to load the JSON due to browser CORS restrictions. Use any local HTTP server.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| UI | Vanilla HTML + CSS + JavaScript (no framework) |
| Charts | [Chart.js 4.4](https://www.chartjs.org/) |
| Zoom/Pan | [chartjs-plugin-zoom 2.0](https://www.chartjs.org/chartjs-plugin-zoom/) + Hammer.js |
| Annotations | [chartjs-plugin-annotation 3.0](https://www.chartjs.org/chartjs-plugin-annotation/) |
| Data | Python 3.11 · requests · pandas · numpy |
| CI/CD | GitHub Actions → GitHub Pages |
| Hosting | GitHub Pages (static, free) |

---

## Covered Instruments (10 Contracts)

| Group | Contracts |
|-------|-----------|
| NYME Futures | Nat Gas NYME (Henry Hub benchmark), Nat Gas LD1, NAT GAS ICE PEN |
| Henry Hub Variants | Henry Hub NYME Swap, HH Last Day Fin, HH Penultimate Fin, HH Penultimate Nat Gas, HH Index ICE, HH Basis ICE |
| Regional Basis | NG LD1 Texok (Texoma/Oklahoma vs Henry Hub) |

---

*For informational and open-source research purposes only. Does not constitute financial advice.*
