#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CFTC Natural Gas Positioning Data Pipeline
Fetches CFTC COT data + NG price data, computes derived metrics, writes cftc_processed.json
"""
import io
import json
import math
import sys
import time
from datetime import datetime, timezone

# Force stdout to UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import requests

# ─── Configuration ─────────────────────────────────────────────────────────────

CFTC_URL = (
    "https://publicreporting.cftc.gov/resource/72hh-3qpy.csv"
    "?commodity_name=NATURAL%20GAS"
    "&$limit=20000"
    "&$order=report_date_as_yyyy_mm_dd%20DESC"
)

PRICE_URL = (
    "https://raw.githubusercontent.com/yieldchaser/nat-gas-data-pipeline"
    "/main/data/nat_gas_continuous.csv"
)

OUTPUT_PATH = "data/cftc_processed.json"

INSTRUMENTS = {
    "nat_gas_nyme":      "NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE",
    "nat_gas_ld1":       "NAT GAS ICE LD1 - ICE FUTURES ENERGY DIV",
    "nat_gas_ice_pen":   "NAT GAS ICE PEN - ICE FUTURES ENERGY DIV",
    "henry_hub_nyme":    "HENRY HUB - NEW YORK MERCANTILE EXCHANGE",
    "hh_last_day":       "HENRY HUB LAST DAY FIN - NEW YORK MERCANTILE EXCHANGE",
    "hh_penult_fin":     "HENRY HUB PENULTIMATE FIN - NEW YORK MERCANTILE EXCHANGE",
    "hh_penult_nat_gas": "HENRY HUB PENULTIMATE NAT GAS - NEW YORK MERCANTILE EXCHANGE",
    "hh_index_ice":      "HENRY HUB INDEX - ICE FUTURES ENERGY DIV",
    "hh_basis_ice":      "HENRY HUB BASIS - ICE FUTURES ENERGY DIV",
}

INSTRUMENT_LABELS = {
    "nat_gas_nyme":      "Nat Gas NYME",
    "nat_gas_ld1":       "Nat Gas LD1",
    "nat_gas_ice_pen":   "NAT GAS ICE PEN",
    "henry_hub_nyme":    "Henry Hub NYME",
    "hh_last_day":       "HH Last Day Fin",
    "hh_penult_fin":     "HH Penultimate Fin",
    "hh_penult_nat_gas": "HH Penultimate Nat Gas",
    "hh_index_ice":      "HH Index ICE",
    "hh_basis_ice":      "HH Basis ICE",
}

# NOTE: exact CFTC column names — double underscore in swap short, no _all in producers
TRADER_COLUMNS = {
    "managed_money": {
        "long":  "m_money_positions_long_all",
        "short": "m_money_positions_short_all",
    },
    "swap_dealers": {
        "long":  "swap_positions_long_all",
        "short": "swap__positions_short_all",   # double underscore — this is the actual CFTC name
    },
    "producers": {
        "long":  "prod_merc_positions_long",    # no _all suffix
        "short": "prod_merc_positions_short",   # no _all suffix
    },
}

WITHDRAWAL_MONTHS = {11, 12, 1, 2, 3}
MIN_ZSCORE_OBS = 20

# ─── Helpers ───────────────────────────────────────────────────────────────────

def sanitise(obj):
    """Recursively replace NaN/Inf with None so json.dumps never fails."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 4)
    if isinstance(obj, (np.floating, np.float32, np.float64)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if isinstance(obj, (np.integer, np.int32, np.int64)):
        return int(obj)
    if isinstance(obj, dict):
        return {k: sanitise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitise(v) for v in obj]
    if isinstance(obj, (pd.NaT.__class__,)):
        return None
    return obj


def fetch_with_retry(url, label, timeout=60, retries=3, accept_csv=True):
    """Fetch a URL with retry logic and exponential backoff."""
    headers = {"Accept": "text/csv"} if accept_csv else {}
    for attempt in range(1, retries + 1):
        try:
            print(f"  [{label}] Attempt {attempt}/{retries}: {url[:80]}...")
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            print(f"  [{label}] OK ({len(r.content):,} bytes)")
            return r.text
        except Exception as exc:
            print(f"  [{label}] Error: {exc}")
            if attempt < retries:
                sleep_secs = 2 ** attempt
                print(f"  [{label}] Retrying in {sleep_secs}s…")
                time.sleep(sleep_secs)
    raise RuntimeError(f"All {retries} attempts failed for {label}")


# ─── Phase 1.1 / 1.2 — Fetch and validate CFTC data ───────────────────────────

def fetch_cftc() -> pd.DataFrame:
    print("\n[Phase 1.1] Fetching CFTC data…")
    raw = fetch_with_retry(CFTC_URL, "CFTC")

    from io import StringIO
    df = pd.read_csv(StringIO(raw), low_memory=False)
    print(f"  Rows: {len(df):,}  Cols: {len(df.columns)}")

    # Validation
    assert len(df) > 500, f"Row count too low ({len(df)}); API may have returned an error page"
    assert "market_and_exchange_names" in df.columns, "Missing column: market_and_exchange_names"
    assert "report_date_as_yyyy_mm_dd" in df.columns, "Missing column: report_date_as_yyyy_mm_dd"

    # Parse dates
    df["report_date_as_yyyy_mm_dd"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])

    # Filter combined rows only (avoid double-counting futonly vs combined)
    if "futonly_or_combined" in df.columns:
        unique_vals = df["futonly_or_combined"].unique().tolist()
        print(f"  futonly_or_combined unique values: {unique_vals}")
        # Try 'C' first (combined), then 'c', then 'Combined', then skip if nothing matches
        for combined_val in ["C", "c", "Combined", "combined"]:
            filtered = df[df["futonly_or_combined"] == combined_val]
            if len(filtered) > 0:
                df = filtered.copy()
                print(f"  After futonly_or_combined=='{combined_val}' filter: {len(df):,} rows")
                break
        else:
            # Check if it only has one value — if so, use all rows
            if len(unique_vals) == 1:
                print(f"  Only one futonly_or_combined value: using all rows")
            else:
                print(f"  WARNING: Could not match futonly_or_combined — using all rows")

    print("[Phase 1.1] CFTC data OK\n")
    return df


# ─── Phase 1.4 — Fetch price data ──────────────────────────────────────────────

def fetch_prices() -> pd.Series:
    print("[Phase 1.4] Fetching NG price data…")
    raw = fetch_with_retry(PRICE_URL, "Prices")

    from io import StringIO
    df = pd.read_csv(StringIO(raw))
    print(f"  Price rows: {len(df):,}  Cols: {list(df.columns)}")

    # Normalise column names
    df.columns = [c.strip() for c in df.columns]
    date_col = next((c for c in df.columns if c.lower() == "date"), None)
    close_col = next((c for c in df.columns if c.lower() in {"close", "price"}), None)

    assert date_col and close_col, f"Expected Date and Close columns, got: {list(df.columns)}"

    df[date_col] = pd.to_datetime(df[date_col], format="%d-%m-%Y", dayfirst=True)
    df = df.rename(columns={date_col: "date", close_col: "price"})
    df = df[["date", "price"]].dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Forward-fill any price gaps
    df["price"] = pd.to_numeric(df["price"], errors="coerce").ffill()

    price = df.set_index("date")["price"]
    print(f"  Price range: {price.index.min().date()} to {price.index.max().date()}")
    print("[Phase 1.4] Price data OK\n")
    return price


# ─── Phase 1.5 — Date alignment via merge_asof ─────────────────────────────────

def align_prices(cftc_df: pd.DataFrame, price_series: pd.Series) -> pd.DataFrame:
    """Join CFTC weekly dates to the nearest past price date."""
    price_df = price_series.reset_index().rename(columns={"date": "price_date"})
    price_df = price_df.sort_values("price_date")

    cftc_dates = cftc_df[["report_date_as_yyyy_mm_dd"]].drop_duplicates().sort_values(
        "report_date_as_yyyy_mm_dd"
    )

    merged = pd.merge_asof(
        cftc_dates,
        price_df,
        left_on="report_date_as_yyyy_mm_dd",
        right_on="price_date",
        direction="backward",
    )

    null_pct = merged["price"].isna().mean()
    if null_pct > 0.05:
        print(f"  WARNING: {null_pct:.1%} of CFTC dates have no matching price")

    return merged.set_index("report_date_as_yyyy_mm_dd")[["price", "price_date"]]


# ─── Phase 1.6 — Derived metrics ───────────────────────────────────────────────

def compute_zscore_expanding(series: pd.Series) -> pd.Series:
    """Expanding z-score matching Excel STDEV.P with minimum 20 observations."""
    mean = series.expanding().mean()
    std = series.expanding().std(ddof=0)
    z = (series - mean) / std
    # NaN when fewer than MIN_ZSCORE_OBS observations
    count = series.expanding().count()
    z[count < MIN_ZSCORE_OBS] = np.nan
    return z


def compute_pct_rank_expanding(series: pd.Series) -> pd.Series:
    """Expanding percentile rank (0–1)."""
    ranks = pd.Series(index=series.index, dtype=float)
    for i in range(len(series)):
        subset = series.iloc[: i + 1].dropna()
        if len(subset) < 2:
            ranks.iloc[i] = np.nan
        else:
            ranks.iloc[i] = (subset < series.iloc[i]).sum() / (len(subset) - 1)
    return ranks


def compute_rolled_corr(net: pd.Series, price: pd.Series, window=20) -> pd.Series:
    return net.rolling(window).corr(price)


def process_instrument(inst_key: str, inst_df: pd.DataFrame, price_map: pd.DataFrame) -> dict:
    """Compute all metrics for one instrument and return a dict ready for JSON."""
    inst_df = inst_df.sort_values("report_date_as_yyyy_mm_dd").reset_index(drop=True)

    dates_raw = inst_df["report_date_as_yyyy_mm_dd"]
    dates_str = dates_raw.dt.strftime("%Y-%m-%d").tolist()

    # Open interest
    oi_col = "open_interest_all"
    oi = pd.to_numeric(inst_df[oi_col], errors="coerce") if oi_col in inst_df.columns else pd.Series(np.nan, index=inst_df.index)

    # Price alignment
    prices_aligned = dates_raw.map(price_map.get("price") if isinstance(price_map, dict) else price_map["price"])

    # Merge prices in
    merged = inst_df.copy()
    merged = merged.join(price_map, on="report_date_as_yyyy_mm_dd")
    price_series = pd.to_numeric(merged["price"], errors="coerce")

    # Season
    season = ["Withdrawal" if m in WITHDRAWAL_MONTHS else "Injection"
              for m in dates_raw.dt.month]

    # Price pct change
    price_pct_change = price_series.pct_change()

    result = {
        "label":         INSTRUMENT_LABELS[inst_key],
        "dates":         dates_str,
        "price":         price_series.tolist(),
        "open_interest": oi.tolist(),
        "season":        season,
    }

    for trader, cols in TRADER_COLUMNS.items():
        lc, sc = cols["long"], cols["short"]
        if lc not in inst_df.columns or sc not in inst_df.columns:
            print(f"    WARNING: missing columns {lc}/{sc} for {trader} in {inst_key}")
            result[trader] = {
                "long": [], "short": [], "net": [],
                "pct_of_oi": [], "z_score": [], "pct_rank": [],
                "rolling_corr": [],
            }
            if trader == "managed_money":
                result[trader]["edge"] = []
            continue

        long_s  = pd.to_numeric(inst_df[lc], errors="coerce")
        short_s = pd.to_numeric(inst_df[sc], errors="coerce")
        net     = long_s - short_s

        with np.errstate(divide="ignore", invalid="ignore"):
            pct_oi = np.where(oi > 0, (long_s + short_s) / oi, np.nan)

        z_score = compute_zscore_expanding(net)

        # Percentile rank (vectorised approximation for speed)
        def fast_pct_rank(s):
            ranks = pd.Series(np.nan, index=s.index)
            arr = s.values
            for i in range(len(arr)):
                subset = arr[: i + 1]
                valid  = subset[~np.isnan(subset)]
                if len(valid) < 2:
                    continue
                ranks.iloc[i] = (valid[:-1] < valid[-1]).sum() / (len(valid) - 1)
            return ranks

        pct_rank = fast_pct_rank(net)
        rolling_corr = compute_rolled_corr(net, price_series)

        trader_dict = {
            "long":         long_s.tolist(),
            "short":        short_s.tolist(),
            "net":          net.tolist(),
            "pct_of_oi":    pct_oi.tolist(),
            "z_score":      z_score.tolist(),
            "pct_rank":     pct_rank.tolist(),
            "rolling_corr": rolling_corr.tolist(),
        }

        if trader == "managed_money":
            edge = (z_score - z_score.shift(1)) - (price_pct_change * 5)
            trader_dict["edge"] = edge.tolist()

        result[trader] = trader_dict

    return result


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("CFTC Natural Gas Positioning Data Pipeline")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    warnings = []

    # Fetch
    cftc_df  = fetch_cftc()
    price_s  = fetch_prices()

    # Build price alignment map (date → price)
    price_df_sorted = price_s.reset_index().rename(columns={"date": "price_date"}).sort_values("price_date")
    cftc_dates_sorted = pd.DataFrame(
        {"report_date_as_yyyy_mm_dd": cftc_df["report_date_as_yyyy_mm_dd"].drop_duplicates().sort_values().values}
    )
    price_aligned = pd.merge_asof(
        cftc_dates_sorted,
        price_df_sorted,
        left_on="report_date_as_yyyy_mm_dd",
        right_on="price_date",
        direction="backward",
    ).set_index("report_date_as_yyyy_mm_dd")

    # Process each instrument
    instruments_out = {}
    all_dates = []

    for inst_key, market_name in INSTRUMENTS.items():
        print(f"[Instrument] {inst_key}: filtering…")
        mask = cftc_df["market_and_exchange_names"].str.strip() == market_name
        inst_df = cftc_df[mask].copy()

        if len(inst_df) == 0:
            warn = f"WARNING: No rows found for {inst_key} ({market_name})"
            print(f"  {warn}")
            warnings.append(warn)
            continue

        print(f"  Rows: {len(inst_df):,}")
        inst_result = process_instrument(inst_key, inst_df, price_aligned)
        instruments_out[inst_key] = inst_result

        if inst_key == "nat_gas_nyme":
            all_dates = inst_result["dates"]

    # Integrity check
    assert "nat_gas_nyme" in instruments_out, "nat_gas_nyme missing from output"
    assert len(instruments_out["nat_gas_nyme"]["dates"]) > 200, \
        f"nat_gas_nyme has only {len(instruments_out['nat_gas_nyme']['dates'])} entries"

    # Determine latest report date
    latest_date = max(
        max(v["dates"]) for v in instruments_out.values() if v.get("dates")
    )

    output = {
        "meta": {
            "last_updated":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latest_report_date": latest_date,
            "warnings":           warnings,
            "price_source":       "yieldchaser/nat-gas-data-pipeline",
        },
        "instruments": instruments_out,
    }

    # Sanitise — remove all NaN/Inf
    print("\n[Sanitise] Cleaning NaN/Inf values…")
    output = sanitise(output)

    # Write output
    import os
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))

    size_mb = os.path.getsize(OUTPUT_PATH) / 1_048_576
    print(f"\n[Done] Written to {OUTPUT_PATH} ({size_mb:.2f} MB)")
    print(f"  Instruments: {list(instruments_out.keys())}")
    print(f"  Latest report date: {latest_date}")
    print(f"  Warnings: {warnings or 'none'}")

    # Final NaN check
    with open(OUTPUT_PATH, "r") as f:
        content = f.read()
    if "NaN" in content or "Infinity" in content:
        print("ERROR: NaN or Infinity found in output JSON — sanitise() failed!")
        sys.exit(1)
    else:
        print("  NaN/Infinity check: PASSED")

    print("\n=== PHASE 1 COMPLETE ===")


if __name__ == "__main__":
    main()
