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

### Cycles & Signals Tab
Event-based analysis of where Henry Hub sits in its swing cycle and whether positioning data supports a direction. No fixed-horizon returns are used.

- **Swing cycle**: confirmed troughs and peaks (20% reversal on roll-adjusted prices), with the level that would confirm the next turn. NG has run about 1.6 major cycles a year since 2006 (about 2.5 at a 15% threshold).
- **Swing map**: every completed rally and decline by size and duration, with the swing in progress highlighted.
- **When turns happen**: troughs and peaks by calendar month.
- **Fund positioning around turns**: event study of the Managed Money COT index and 4-week flow, 12 weeks either side of each turn.
- **Which way moves resolve**: share of weeks where price rose X% before falling X% (first passage), by month and under today's conditions, with overlap-adjusted intervals.
- **Signal scorecard**: every positioning signal judged as a turning-point detector (hit rate vs base rate, lift, turns caught).
- **What the evidence says now**: a generated summary at the top of the tab, including when the data does not support a directional call.
- **Date Inspector**: pick any date to see what price did afterwards, what the positioning data showed using only reports published by then (CFTC releases Tuesday positions on Friday), which signals were active, and whether the same calendar date behaved the same way in other years (tested against the drift-adjusted base rate).
- **Signal scorecard with out-of-sample test**: every signal shows its lift before and after 2018. Four cross-group combination signals were found by testing 1,104 single and paired conditions across all trader groups (selected on 2009–2017, kept only if they held on 2018+): speculators crowded long and selling, producers heavily short while speculators buy, a Managed Money surge while Other Reportables sell (peaks), and small traders crowded short (troughs).

Key findings from the data: Managed Money is a coincident trend follower (weekly flows track same-week price, r about +0.4, and do not lead it). Managed Money crowded short has NOT marked troughs in either period. Single-group signals are weak, but cross-group combinations hold out of sample (lift roughly 1.8-2.1x on NYMEX, 2018+). Several older single-group signals faded after 2018 and are labelled as such. Early September is the only calendar window with a statistically robust recurring move (up in 15 of 19 years).

### Ideas adopted from Ilia Bouchouev's research (CMU Commodities Quant Lab)
Each idea was tested on 20 years of natural gas data before being adopted; ideas that did not hold up were left out.
- **Hedging pressure via swap dealers.** Producers hedge mostly over the counter with their banks, so producer hedging reaches futures through the swap-dealer category. Signal: *Hedgers selling into strength* (swap dealers + producers cut net position by more than 1% of open interest over 2 weeks while price rises) has marked tops at about 1.3–1.6x chance both before and since 2018. The mirror case (hedgers buying dips) showed no edge and is not used.
- **Trend-following vs discretionary decomposition** (after Bouchouev, Sun & Fattouh, OIES 2026): Managed Money dollars split into the CTA-model component and everything else, plus the trend-follower share of fund trading (rolling 52-week R²). CTA & Flows tab.
- **Who trades against whom:** weekly flow correlations between trader groups and with price (his Table 1, for natural gas). Multi-Trader tab.
- **Not adopted:** treating Managed Money and Other Reportables separately did not improve the top signals in natural gas (the combined version held up better out of sample). Curve-shape, options-skew and swap-repository hedging indicators need data this pipeline does not collect.

### CTA & Flows Tab
Dollar-sized positioning plus a daily trend-follower (CTA) model for Henry Hub.

- **Managed Money Net Length ($bn) vs Price**: CFTC contracts × contract size (MMBtu, parsed from CFTC `contract_units`) × front-month price. Trader selectable (MM, Total Spec, Other, Swap, PMPU). Composites are sized component by component, because NYMEX NG is 10,000 MMBtu while ICE Henry Hub contracts are 2,500 MMBtu. Basis contracts are excluded because they settle on a differential.
- **PMPU Gross Longs / Shorts ($bn) vs Price**: commercial hedger gross exposure in dollars.
- **CTA Momentum Thresholds (%)**: distance of the roll-adjusted front month from its 20 / 60 / 250-session moving average. Crossing zero flips that horizon.
- **1m Conditional Projections ($bn)**: simulated CTA net length (realized), then 21 sessions forward under Up Big / Up Small / Flat / Down Small / Down Big paths (±2σ / ±1σ / 0 of one-month realized vol).
- **Signal Flip Levels** and a **Scenario Flow Table**, plus a CTA strip on the Overview tab.
- The dollar scale is the OLS slope of weekly CFTC Managed Money $ on model exposure (156w). The fit quality (r) is shown on the page. The page polls for new data every 10 minutes while open.

### Interactive Controls
- **Per-chart range**: every time-series chart has its own 1Y / 3Y / 5Y / 10Y / All selector (Multi-Trader also has a set-all control)
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
│       ├── update_cftc.yml       # weekly COT pipeline (Fri / Sat / Mon / Tue retries) + CTA re-fit
│       └── update_cta_model.yml  # daily CTA model refresh after NYMEX settlement
├── data/
│   ├── cftc_processed.json     # Auto-generated COT payload
│   └── cta_model.json          # Auto-generated daily CTA model (~100 KB)
├── scripts/
│   ├── update_cftc_data.py     # Data pipeline: fetch → staleness check → process → write
│   ├── update_cta_model.py     # CTA trend model: NG=F daily → thresholds, $ position, projections
│   └── run_quantitative_parity_audit.py  # Parity, schema, headless-UI and CTA integrity audit
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

### CTA model pipeline
`scripts/update_cta_model.py` runs every weekday at 21:20 UTC (after NG settlement) and again right after each new COT report. It fetches 10 years of Yahoo `NG=F` daily closes and zeroes the return on each roll day (the session after NYMEX last trade), so seasonal roll gaps do not register as trend. It then computes the thresholds, the vol-targeted position and the scenario paths, re-fits the dollar scale to CFTC Managed Money, and commits `data/cta_model.json` only when something changed. Both workflows share one concurrency group and rebase before pushing, so they never race. Offline: `python scripts/update_cta_model.py --prices-csv prices.csv` (columns `date,close`).

---

## Signals & Metrics Glossary

| Metric | Description |
|--------|-------------|
| **Z-Score** | Standard deviations from full historical mean. ±1.5 = historically extended; ±2 = rare extreme |
| **COT Index** | Percentile rank within prior 3-year range. ≥80% = crowded long; ≤20% = crowded short |
| **Extension Score** | −3 (crowded short) to +3 (crowded long) from the MM Z-score and 3-year COT index. Describes how stretched positioning is, not direction |
| **Momentum Score** | 0–100 flow momentum vs trailing 13-week volatility. >80 = outsized repositioning |
| **OI Regime** | Market structure: Accumulation (OI↑+Price↑), Distribution (OI↑+Price↓), Short Covering (OI↓+Price↑), Long Liquidation (OI↓+Price↓) |
| **Lead/Lag** | Rank cross-correlation of weekly flow with weekly price change at lags −8 to +8 weeks, with a band adjusted for multiple testing |

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

## Covered Instruments

Markets are matched by CFTC contract code, so history survives CFTC's 2022 market renaming. The pipeline log also prints every reporting natural gas market ranked by open interest (`meta.coverage`), so newly liquid contracts are easy to spot.

| Group | Contracts |
|-------|-----------|
| Composites (NYMEX-equivalent) | HH Prompt Core (NYMEX + ICE LD1 + ICE PEN + EUR options), HH Clean Outright (all Henry Hub futures and swaps, no options) |
| Prompt Benchmarks | Nat Gas NYME, ICE LD1, ICE PEN, EUR-style options |
| Henry Hub Cleared Swaps | CME Last Day, CME Penultimate, CME NN, CME NP, ICE HH Index |
| Regional Basis | Waha, HSC, NGPL TXOK, Dominion South, TETCO M2, Transco Z6 NY, REX Zone 3, Chicago, CIG Rockies, NWP Rockies, SoCal Border, AECO |

Composites are expressed in **NYMEX-equivalent contracts** (10,000 MMBtu): ICE and CME look-alike contracts are 2,500 MMBtu and are scaled by 0.25 before summing, and composites are only defined on dates where every component reports.

-------|-----------|
| NYME Futures | Nat Gas NYME (Henry Hub benchmark), Nat Gas LD1, NAT GAS ICE PEN |
| Henry Hub Variants | Henry Hub NYME Swap, HH Last Day Fin, HH Penultimate Fin, HH Penultimate Nat Gas, HH Index ICE, HH Basis ICE |
| Regional Basis | NG LD1 Texok (Texoma/Oklahoma vs Henry Hub) |

---

*For informational and open-source research purposes only. Does not constitute financial advice.*
