# CFTC Natural Gas Positioning Dashboard 📊

A professional-grade terminal for visualizing and analyzing Commitment of Traders (COT) data across US Natural Gas markets. Built as a single-page application, it transforms raw weekly CFTC reports into institutional-grade visual analytics — no backend, no build step, no dependencies beyond a browser.

[**Launch the Live Dashboard →**](https://yieldchaser.github.io/CFTC-Reports-/)

---

## Features

### Overview Tab
The command center across 10 correlated instruments.

- **Top Signals Banner** — algorithmic highlight of the highest composite-score instruments this week
- **Signal Cards** — per-instrument summary cards showing MM net, Z-score, COT index, OI regime, and score, grouped by contract family with collapsible groups
- **Z-Score Heatmap** — extreme positioning across a selectable lookback (13w / 26w / 52w / All), togglable across all 5 trader categories
- **Correlation Matrix** — live 10×10 Pearson correlation matrix across instruments, selectable over 13w / 26w / 52w / 3yr windows
- **Open Interest Leaderboard** — ranked by this week's OI, 4-week change %, or 52-week high %
- **Weekly Change Table** — sortable table of all key metrics: MM net / delta / Z, COT index, score, momentum, Swap net, price, OI regime

### By Instrument Tab
Click any instrument pill (or signal card) to load 8 forensic sub-charts:

- **Net Position vs. Price** — bar/line overlay with ATH long/short annotations and momentum arrows
- **Price vs. Net Long Scatter** — season-coded (Withdrawal / Injection) clustering view
- **20-Week Rolling Correlation** — identifies trending (>0.4) and mean-reversion (<−0.4) regimes
- **Weekly Flow** — week-over-week net position change, signed and color-coded
- **COT Index** — 3-year percentile index (0 = min, 100 = max) with selectable 26w / 52w / 3yr lookback
- **Seasonal Overlay** — current year vs. 5-year historical avg ± 1σ, with per-year toggles
- **Lead/Lag Analysis** — rolling correlation at +1 to +4 week lags to detect positioning lead on price
- **Smart vs. Dumb Money** — MM net vs. Non-Reportable (retail) net overlaid
- **Percentile Rank Bars** — all 5 traders, current-week pct rank + COT index in a single visual

### Multi-Trader View Tab
All 10 instruments side-by-side with MM, Swap, Producers, and Other Reportables on one chart each.

- Toggle between **% of Open Interest** (normalized, single Y-axis) and **Raw (independent axes)**
- Price overlaid as a secondary axis on every chart

### Interactive Controls
- **Date range** — dropdown presets (1y / 2y / 3y / 5y / all) + drag slider for precise start date
- **Trader filter** — per-instrument tab filter (MM / Swap / Prod / Other / Retail)
- **Zoom + pan** — mouse-wheel zoom and horizontal pan on every chart; Reset button per chart
- **Crosshair** — per-chart vertical crosshair on hover; activates on exactly one chart at a time
- **Tooltips** — data-aware, context-sensitive: date, net, long, short, Z-score, COT index, price, regime
- **Instrument search** — fuzzy-filter instrument pills by name
- **Keyboard navigation** — Arrow keys / 1–9 to cycle instruments in the By Instrument tab
- **CSV export** — download current instrument + trader as CSV

---

## Project Structure

```
CFTC-Reports/
├── .github/
│   └── workflows/
│       └── update_cftc.yml     # Runs every Friday after CFTC release (21:30 UTC)
├── data/
│   └── cftc_processed.json     # Auto-generated data payload (~1.7 MB)
├── scripts/
│   └── update_cftc_data.py     # Data pipeline: fetch → process → write JSON
├── index.html                  # Entire dashboard UI (Vanilla JS + Chart.js, ~92 KB)
├── favicon.png
├── .nojekyll                   # Required for GitHub Pages to serve correctly
└── README.md
```

---

## Data Pipeline

`scripts/update_cftc_data.py` runs automatically every Friday at 21:30 UTC via GitHub Actions, immediately after the CFTC report is published.

1. **Fetch** — pulls the public COT disaggregated futures data from `publicreporting.cftc.gov`
2. **Filter** — selects the 10 Natural Gas instrument codes by CFTC market name
3. **Compute** — calculates for each trader category: net position, weekly change, Z-scores (52w/3yr), percentile rank, COT index, 20-week rolling correlation, lagged correlations (1–4w), seasonal aggregates
4. **Output** — writes `data/cftc_processed.json` with pre-computed arrays; GitHub Actions commits and pushes, which triggers GitHub Pages re-deployment

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