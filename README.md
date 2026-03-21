# CFTC Natural Gas Positioning Dashboard 📊

A definitive, professional-grade terminal for visualizing and analyzing Commitment of Traders (COT) data for US Natural Gas markets. Built as a blazing-fast Single Page Application (SPA), this dashboard transforms raw weekly CFTC reports into actionable, institutional-grade visual analytics.

[**Launch the Live Dashboard**](https://yieldchaser.github.io/CFTC-Reports-/)

---

## 🌟 Comprehensive Feature Set

### 1. The Overview Hub
The command center for macroeconomic positioning logic across 10 correlated instruments.
*   **Conviction Signal Banner:** Algorithmic banner highlighting standard-deviation shocks and extreme accumulations based on a custom `Composite Score`.
*   **Open Interest Leaderboard:** Real-time ranking of the most actively traded variants, normalized by absolute size, 4-week change percentage, or 52-week highs.
*   **Z-Score Heatmap:** Instant visualization of extreme positioning stretching back across a 3-year lookback period. Toggle between 5 trader categories on the fly.
*   **Correlation Matrix:** Active 10x10 matrix identifying dynamic lead/lag relationship breakdowns between the various ICE, NYME, and Regional basis markets.
*   **Weekly Change Summary:** Highly sortable core metrics reporting net flows, standard deviations, and Open Interest Regimes (e.g., Short Covering, Long Liquidation).
*   **Data Freshness Constraints:** Red/Yellow/Green dot indicators warn users if external API feeds are lagging beyond typical reporting intervals.

### 2. The Instrument Drill-Down
Click any dataset to instantly generate 8 specialized forensic sub-charts.
*   **Net Position vs. Price:** Overlaid historical time-series highlighting divergence between fundamental pricing and speculative positioning.
*   **Price vs. Net Long Scatter:** Seasonally color-coded (Withdrawal vs. Injection) scatter plot revealing clustering behavior regimes.
*   **20-Week Rolling Correlation:** Highlights periods of trending relationships (>0.4) versus mean-reversion anomalies (<-0.4).
*   **Weekly Flow Momentum:** Pinpoints exact weeks featuring top-quartile aggressive speculative accumulation or dumping (annotated with ▲ / ▼).
*   **COT Index Bounds:** 3-year historical percentile ranking mechanism (0 = Min, 100 = Max) demonstrating terminal exhaustion points.
*   **Seasonal Overlays:** Evaluates current positioning explicitly against the 5-year historical average and ±1 standard deviation bounds.
*   **Lead/Lag Analysis:** Determines if Managed Money positioning is actively leading price action by 1 to 4 weeks.
*   **Smart vs. Dumb Money:** Directly contrasts Managed Money accumulation against Non-Reportable (retail) exposure.

### 3. The Multi-Trader Matrix
A synchronized global grid allowing macro comparison across the entire instrument ecosystem.
*   Tracks Managed Money, Swap Dealers, Producers, and Other Reportables identically.
*   Features **Normalization Toggles**: instantly switch between raw contract thresholds and "Percentage of Total Open Interest" scaling to accurately compare micro-contracts alongside Henry Hub benchmarks.

### 4. Interactive & Performance Architecture
Optimized to handle 10,000+ localized data points at 60 FPS without DOM blocking.
*   **Synchronized Crosshairs:** Hovering over any time-series perfectly tracks axes via a globally synced `requestAnimationFrame` throttled pointer.
*   **Deep Zoom Analytics:** Fully scrollable Hammer.js viewport zooming and horizontal panning with persistent "Reset Zoom" anchors.
*   **Custom Rich Tooltips:** Bypasses canvas clipping issues by projecting rich external HTML overlays loaded with exact values, prices, regime statuses, and context.
*   **Dynamic Date Slider:** Dual-handle boundary sliders instantly filter multi-year scopes without data reloading.
*   **Zero Memory Leaks:** Employs advanced `safeCreateChart` GC wrapping, Tab Teardown handlers, and async request queues to aggressively eliminate stray `Chart.instances` and prevent browser crashes over long sessions.

---

## 🛠 Project Architecture & Data Pipeline

The frontend is a completely static, serverless Vanilla JS + HTML asset hosted via GitHub Pages, while the backend relies on a deterministic Python data pipeline integrated via GitHub Actions.

```text
├── .github/workflows/    # CD: Automatic Friday data updates via GH Actions
├── data/                 # Processed JSON storage ingested natively by frontend UI
├── scripts/              # Python data pipeline
│   └── update_cftc_data.py # The quantitative normalization engine
├── index.html            # Main SPA Dashboard (Vanilla JS + Chart.js)
├── favicon.png           # Custom dashboard branding
└── README.md
```

### The Data Engine (`scripts/update_cftc_data.py`)
Deployed automatically every Friday at 21:30 UTC directly following the CFTC bulletin drop.
1.  **Ingestion:** Scrapes the public endpoint `publicreporting.cftc.gov`.
2.  **Harmonization:** Joins arbitrary CFTC format nomenclature (NYME vs ICE) with contiguous Henry Hub continuous pricing metrics imported from secondary historical datasets.
3.  **Quantitative Analysis:** Constructs and computes standard deviation baselines (52w/3yr), COT Indices, 20-week rolling correlations, and percentile extremes entirely offline.
4.  **Payload Output:** Minifies arrays and dictionaries into `cftc_processed.json`, heavily reducing client-side computation latency.

---

## 🚀 Deployment & Local Development

No Node.js or heavy bundlers are required for frontend development. The entire UI is packed cleanly inside `index.html`.

### Local Setup
1. Clone the repository natively.
2. (Optional) Rebuild the data pipeline:
   ```bash
   pip install requests pandas numpy
   python scripts/update_cftc_data.py
   ```
3. Use any live server extension or double-click `index.html` in an arbitrary modern browser.

### GitHub Pages
Data automation and deployment rely completely on Git architecture. No external DB hosts are necessary. The pipeline overwrites the JSON array payload, and GitHub Actions effortlessly pushes the resulting commit back to the `main` branch, triggering GitHub Pages propagation.

---

## 📊 Covered Instruments (10 Contracts)
*   **Core Hubs:** Nat Gas NYME (Henry Hub), Nat Gas LD1, NAT GAS ICE PEN.
*   **Financial Variants:** Henry Hub NYME Swap, HH Last Day Fin, HH Penultimate Fin/Nat Gas.
*   **Basis & Index:** HH Index ICE, HH Basis ICE, NG LD1 Texok (Regional).

---

*Disclaimer: This specific dashboard framework, pipeline layout, and quantitative representation schema are for informational / open source research purposes only and do not constitute direct financial advisement.*