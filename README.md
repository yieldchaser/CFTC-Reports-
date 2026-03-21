# CFTC Natural Gas Positioning Dashboard

A professional-grade terminal for visualizing CFTC Commitment of Traders (COT) data for US Natural Gas markets. This dashboard provides deep analytical insights into the positioning of Managed Money, Swap Dealers, Producers, and Other Reportables.

[**View the Live Dashboard**](https://yieldchaser.github.io/CFTC-Reports-/)

---

## 📈 Key Features

### 1. Interactive Visual Analytics
- **Multi-Chart Syncing:** Crosshair cursor syncs time axes across all visible charts for precise period analysis.
- **Drill-Down Zoom:** Scroll-wheel zoom on X-axes to inspect local variance or high-volatility events.
- **Rich Context Tooltips:** Hover over any data point to see Z-scores, COT Indices, Percentile Ranks, and Price regimes in a formatting-rich overlay.

### 2. Advanced Market Metrics
- **Z-Score Heatmap:** Instant visualization of extreme positioning across 10 different Natural Gas benchmarks (NYME, ICE, Regional Basis).
- **Instrument Correlation Matrix:** Real-time 10x10 correlation matrix (13w to 3yr periods) identifying lead/lag relationships between contracts.
- **Positioning Momentum:** Proprietary "Momentum Arrows" (▲/▼) identify weeks where Managed Money aggressively shifted their exposure.
- **Seasonal Overlays:** Current positioning vs. 5-year historical ranges and averages, categorized by Withdrawal and Injection seasons.

### 3. Open Interest Leaderboard & Signal Dashboard
- **OI Ranking:** Live rankings of instruments by absolute Open Interest or 52-week High percentage.
- **Signal Cards:** Color-coded cards summarizing the "Market Regime" (e.g., Short Covering, Accumulation) with freshness indicators.
- **Market Composition:** Breakdown of Smart vs. Dumb money (Managed Money vs. Non-Reportable) with divergence highlighting.

---

## 🛠 Project Structure

```text
├── .github/workflows/    # CD: Automatic Friday data updates via GH Actions
├── data/                 # Processed JSON storage for the frontend
├── scripts/              # Python data pipeline
│   └── update_cftc_data.py
├── index.html            # Main SPA dashboard (Vanilla JS + Chart.js)
└── README.md
```

### Data Pipeline (`scripts/update_cftc_data.py`)
The pipeline runs every Friday at 21:30 UTC following the official CFTC release. It performs:
1.  **Data Ingestion:** Fetches the latest `.csv` from `publicreporting.cftc.gov`.
2.  **Normalization:** Harmonizes different instrument reporting formats (NYME vs. ICE).
3.  **Analytics:** Calculates Z-scores (52w/3yr), COT Indices, 20-week rolling correlations, and seasonal deviations.
4.  **JSON Export:** Outputs a structured `cftc_processed.json` optimized for frontend performance.

---

## 🚀 Deployment & Local Development

### Prerequisites
- Python 3.10+
- `pandas`, `numpy`, `requests`

### Local Setup
1. Clone the repository.
2. Run the pipeline to generate data:
   ```bash
   python scripts/update_cftc_data.py
   ```
3. Open `index.html` in any modern browser.

### GitHub Pages
The dashboard is automatically deployed via GitHub Pages from the `main` branch. Data updates are handled by the GitHub Actions workflow defined in `.github/workflows/update_cftc.yml`.

---

## 📊 Covered Instruments (10)
- **Core Hubs:** Nat Gas NYME (Henry Hub), Nat Gas LD1, NAT GAS ICE PEN.
- **Financial Variants:** Henry Hub NYME Swap, HH Last Day Fin, HH Penultimate Fin/Nat Gas.
- **Basis & Index:** HH Index ICE, HH Basis ICE, NG LD1 Texok (Regional).

---

*Disclaimer: This dashboard is for informational purposes only and does not constitute financial advice.*