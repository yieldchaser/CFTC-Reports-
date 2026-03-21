#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CFTC Natural Gas Positioning Data Pipeline — Enhanced
Includes: COT Index, seasonal deviation, change columns, concentration,
          correlation matrix, composite score, historical extremes.
"""
import io
import json
import math
import os
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

# NOTE: exact CFTC names — double underscore in swap short, no _all in producers
TRADER_COLUMNS = {
    "managed_money": {
        "long":  "m_money_positions_long_all",
        "short": "m_money_positions_short_all",
        "change_long":  "change_in_m_money_long_all",
        "change_short": "change_in_m_money_short_all",
    },
    "swap_dealers": {
        "long":  "swap_positions_long_all",
        "short": "swap__positions_short_all",   # double underscore — actual CFTC schema
        "change_long":  "change_in_swap_long_all",
        "change_short": "change_in_swap_short_all",
    },
    "producers": {
        "long":  "prod_merc_positions_long",    # no _all suffix
        "short": "prod_merc_positions_short",
        "change_long":  "change_in_prod_merc_long_all",
        "change_short": "change_in_prod_merc_short_all",
    },
}

CONCENTRATION_COLS = {
    "top4_long":  "conc_gross_le_4_tdr_long_all",
    "top4_short": "conc_gross_le_4_tdr_short_all",
    "top8_long":  "conc_gross_le_8_tdr_long_all",
    "top8_short": "conc_gross_le_8_tdr_short_all",
}

WITHDRAWAL_MONTHS = {11, 12, 1, 2, 3}
MIN_ZSCORE_OBS   = 20
COT_LOOKBACKS    = {"w26": 26, "w52": 52, "w156": 156}

# ─── Helpers ───────────────────────────────────────────────────────────────────

def sanitise(obj):
    """Recursively replace NaN/Inf with None; round floats to 4dp."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else round(obj, 4)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 4)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, dict):
        return {k: sanitise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitise(v) for v in obj]
    return obj


def fetch_with_retry(url, label, timeout=60, retries=3):
    headers = {"Accept": "text/csv"}
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
                time.sleep(2 ** attempt)
    raise RuntimeError(f"All {retries} attempts failed for {label}")

# ─── Fetch CFTC ────────────────────────────────────────────────────────────────

def fetch_cftc() -> pd.DataFrame:
    print("\n[Phase 1.1] Fetching CFTC data...")
    raw = fetch_with_retry(CFTC_URL, "CFTC")
    df = pd.read_csv(io.StringIO(raw), low_memory=False)
    print(f"  Rows: {len(df):,}  Cols: {len(df.columns)}")
    assert len(df) > 500
    assert "market_and_exchange_names" in df.columns
    assert "report_date_as_yyyy_mm_dd" in df.columns
    df["report_date_as_yyyy_mm_dd"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
    if "futonly_or_combined" in df.columns:
        unique_vals = df["futonly_or_combined"].unique().tolist()
        print(f"  futonly_or_combined values: {unique_vals}")
        for val in ["C", "c", "Combined", "combined"]:
            filtered = df[df["futonly_or_combined"] == val]
            if len(filtered) > 0:
                df = filtered.copy()
                print(f"  Filtered to '{val}': {len(df):,} rows")
                break
        else:
            print("  Using all rows (single futonly_or_combined value)")
    print("[Phase 1.1] CFTC OK\n")
    return df

# ─── Fetch Prices ──────────────────────────────────────────────────────────────

def fetch_prices() -> pd.Series:
    print("[Phase 1.4] Fetching NG price data...")
    raw = fetch_with_retry(PRICE_URL, "Prices")
    df = pd.read_csv(io.StringIO(raw))
    df.columns = [c.strip() for c in df.columns]
    date_col  = next((c for c in df.columns if c.lower() == "date"), None)
    close_col = next((c for c in df.columns if c.lower() in {"close", "price"}), None)
    assert date_col and close_col
    df[date_col] = pd.to_datetime(df[date_col], format="%d-%m-%Y", dayfirst=True)
    df = df.rename(columns={date_col: "date", close_col: "price"})
    df = df[["date", "price"]].dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").ffill()
    price = df.set_index("date")["price"]
    print(f"  Price range: {price.index.min().date()} to {price.index.max().date()}")
    print("[Phase 1.4] Price OK\n")
    return price

# ─── Derived Metrics ───────────────────────────────────────────────────────────

def expanding_zscore(series: pd.Series, min_obs=MIN_ZSCORE_OBS) -> pd.Series:
    mean = series.expanding().mean()
    std  = series.expanding().std(ddof=0)
    z    = (series - mean) / std
    z[series.expanding().count() < min_obs] = np.nan
    return z


def cot_index(series: pd.Series, window: int) -> pd.Series:
    """Rolling COT Index 0–100."""
    roll_min = series.rolling(window, min_periods=1).min()
    roll_max = series.rolling(window, min_periods=1).max()
    with np.errstate(divide="ignore", invalid="ignore"):
        idx = np.where(roll_max != roll_min,
                       (series - roll_min) / (roll_max - roll_min) * 100,
                       np.nan)
    result = pd.Series(idx, index=series.index)
    result[series.expanding().count() < window] = np.nan
    return result


def fast_pct_rank(s: pd.Series) -> pd.Series:
    ranks = pd.Series(np.nan, index=s.index)
    arr = s.values
    for i in range(len(arr)):
        subset = arr[: i + 1]
        valid  = subset[~np.isnan(subset.astype(float))]
        if len(valid) < 2:
            continue
        ranks.iloc[i] = (valid[:-1] < valid[-1]).sum() / (len(valid) - 1)
    return ranks


def seasonal_stats(net: pd.Series, dates):
    """Return seasonal_avg_by_week (52-element) and seasonal_deviation series.
    dates can be a DatetimeIndex or a Series of datetimes."""
    if hasattr(dates, 'dt'):
        week_of_year = dates.dt.isocalendar().week.values.astype(int)
    else:
        week_of_year = pd.DatetimeIndex(dates).isocalendar().week.values.astype(int)
    avgs, stds = {}, {}
    for w in range(1, 53):
        mask = week_of_year == w
        vals = net.values[mask]
        vals = vals[~np.isnan(vals.astype(float))]
        avgs[w] = float(np.mean(vals)) if len(vals) > 0 else np.nan
        stds[w] = float(np.std(vals, ddof=0)) if len(vals) > 1 else np.nan

    avg_arr = [avgs.get(w, np.nan) for w in range(1, 53)]
    std_arr = [stds.get(w, np.nan) for w in range(1, 53)]
    dev = pd.Series([net.iloc[i] - avgs.get(week_of_year[i], np.nan)
                     for i in range(len(net))], index=net.index)
    return avg_arr, std_arr, dev


def composite_score(mm_z, mm_cot, prod_z):
    """Return integer -3 to +3."""
    if mm_z is None or np.isnan(mm_z):
        return 0
    score = 0
    if mm_z >= 1.5:  score += 1
    if mm_z >= 2.0:  score += 1
    if mm_cot is not None and not np.isnan(mm_cot) and mm_cot >= 80: score += 1
    if mm_z <= -1.5: score -= 1
    if mm_z <= -2.0: score -= 1
    if mm_cot is not None and not np.isnan(mm_cot) and mm_cot <= 20: score -= 1
    if prod_z is not None and not np.isnan(prod_z):
        if mm_z > 1.0 and prod_z < -1.0: score += 1
        if mm_z < -1.0 and prod_z > 1.0: score -= 1
    return int(np.clip(score, -3, 3))

# ─── Process One Instrument ────────────────────────────────────────────────────

def process_instrument(inst_key: str, inst_df: pd.DataFrame, price_aligned: pd.DataFrame) -> dict:
    inst_df = inst_df.sort_values("report_date_as_yyyy_mm_dd").reset_index(drop=True)
    dates_raw = inst_df["report_date_as_yyyy_mm_dd"]
    dates_str = dates_raw.dt.strftime("%Y-%m-%d").tolist()

    oi = pd.to_numeric(inst_df.get("open_interest_all", pd.Series(np.nan, index=inst_df.index)),
                       errors="coerce") if "open_interest_all" in inst_df.columns \
        else pd.Series(np.nan, index=inst_df.index)

    # Merge prices
    merged = inst_df.join(price_aligned, on="report_date_as_yyyy_mm_dd")
    price_series = pd.to_numeric(merged.get("price", pd.Series(np.nan)), errors="coerce")
    price_series.index = inst_df.index
    price_pct_change = price_series.pct_change()

    season = ["Withdrawal" if m in WITHDRAWAL_MONTHS else "Injection"
              for m in dates_raw.dt.month]

    # Concentration (only for nat_gas_nyme)
    concentration = {}
    if inst_key == "nat_gas_nyme":
        for k, col in CONCENTRATION_COLS.items():
            if col in inst_df.columns:
                concentration[k] = pd.to_numeric(inst_df[col], errors="coerce").tolist()

    result = {
        "label":         INSTRUMENT_LABELS[inst_key],
        "dates":         dates_str,
        "price":         price_series.tolist(),
        "open_interest": oi.tolist(),
        "season":        season,
    }
    if concentration:
        result["concentration"] = concentration

    trader_nets = {}  # for correlation matrix and composite score

    for trader, cols in TRADER_COLUMNS.items():
        lc, sc = cols["long"], cols["short"]
        if lc not in inst_df.columns or sc not in inst_df.columns:
            print(f"    WARNING: {lc}/{sc} missing for {trader} in {inst_key}")
            result[trader] = {"long":[],"short":[],"net":[],"pct_of_oi":[],"z_score":[],
                              "pct_rank":[],"rolling_corr":[],"cot_index":{"w26":[],"w52":[],"w156":[]},
                              "change_long":[],"change_short":[],"change_net":[],"seasonal_deviation":[],
                              "extremes":{},"composite_score":[]}
            if trader == "managed_money":
                result[trader]["edge"] = []
                result[trader]["seasonal_avg_by_week"] = []
                result[trader]["seasonal_std_by_week"] = []
            continue

        long_s  = pd.to_numeric(inst_df[lc], errors="coerce")
        short_s = pd.to_numeric(inst_df[sc], errors="coerce")
        net     = long_s - short_s
        trader_nets[trader] = net

        with np.errstate(divide="ignore", invalid="ignore"):
            pct_oi = np.where(oi > 0, (long_s + short_s) / oi, np.nan)

        z_score      = expanding_zscore(net)
        pct_rank_s   = fast_pct_rank(net)
        rolling_corr = net.rolling(20).corr(price_series)

        # COT Index at 3 lookbacks
        cot_indices = {lb: cot_index(net, w).tolist() for lb, w in COT_LOOKBACKS.items()}

        # Change columns
        def get_change(col_key):
            col = cols.get(col_key)
            if col and col in inst_df.columns:
                return pd.to_numeric(inst_df[col], errors="coerce")
            return pd.Series(np.nan, index=inst_df.index)

        change_long  = get_change("change_long")
        change_short = get_change("change_short")
        change_net   = change_long - change_short

        # Seasonal
        avg_by_week, std_by_week, deviation = seasonal_stats(net, dates_raw)

        # Extremes
        valid_net = net.dropna()
        if len(valid_net) > 0:
            max_idx = valid_net.idxmax()
            min_idx = valid_net.idxmin()
            extremes = {
                "max_long_value":  float(valid_net.max()),
                "max_long_date":   dates_raw.iloc[max_idx].strftime("%Y-%m-%d") if max_idx < len(dates_raw) else None,
                "max_short_value": float(valid_net.min()),
                "max_short_date":  dates_raw.iloc[min_idx].strftime("%Y-%m-%d") if min_idx < len(dates_raw) else None,
            }
        else:
            extremes = {}

        # Composite score per row
        mm_z_arr   = z_score.tolist()
        mm_cot_arr = cot_indices["w156"]
        pr_z_arr   = None
        comp_scores = []

        trader_dict = {
            "long":         long_s.tolist(),
            "short":        short_s.tolist(),
            "net":          net.tolist(),
            "pct_of_oi":    pct_oi.tolist(),
            "z_score":      z_score.tolist(),
            "pct_rank":     pct_rank_s.tolist(),
            "rolling_corr": rolling_corr.tolist(),
            "cot_index":    cot_indices,
            "change_long":  change_long.tolist(),
            "change_short": change_short.tolist(),
            "change_net":   change_net.tolist(),
            "seasonal_deviation": deviation.tolist(),
            "extremes":     extremes,
        }

        if trader == "managed_money":
            edge = (z_score - z_score.shift(1)) - (price_pct_change * 5)
            trader_dict["edge"] = edge.tolist()
            trader_dict["seasonal_avg_by_week"] = avg_by_week
            trader_dict["seasonal_std_by_week"] = std_by_week

        result[trader] = trader_dict

    # Composite score uses last values of MM and Producers z-scores
    mm  = result.get("managed_money", {})
    pr  = result.get("producers", {})
    mm_z_list   = mm.get("z_score", [])
    pr_z_list   = pr.get("z_score", [])
    cot_list    = mm.get("cot_index", {}).get("w156", [])
    comp = []
    for i in range(len(dates_str)):
        mz  = mm_z_list[i]  if i < len(mm_z_list)  else None
        pz  = pr_z_list[i]  if i < len(pr_z_list)  else None
        cot = cot_list[i]   if i < len(cot_list)    else None
        comp.append(composite_score(mz, cot, pz))
    result["composite_scores"] = comp

    result["_nets"] = {k: v.tolist() for k, v in trader_nets.items()}
    return result

# ─── Correlation Matrix ────────────────────────────────────────────────────────

def build_correlation_matrix(instruments_out: dict) -> dict:
    keys = [k for k in INSTRUMENTS if k in instruments_out]
    n = len(keys)
    # Align on common dates using last 52 weeks of nat_gas_nyme as anchor
    series_map = {}
    for k in keys:
        inst = instruments_out[k]
        nets = inst.get("managed_money", {}).get("net", [])
        dates = inst.get("dates", [])
        if nets and dates:
            s = pd.Series(nets, index=pd.to_datetime(dates))
            # last 52 weekly obs
            series_map[k] = s.iloc[-52:] if len(s) >= 52 else s

    matrix = []
    for k1 in keys:
        row = []
        for k2 in keys:
            if k1 == k2:
                row.append(1.0)
            elif k1 in series_map and k2 in series_map:
                s1, s2 = series_map[k1].align(series_map[k2], join="inner")
                if len(s1) >= 10:
                    row.append(float(s1.corr(s2)))
                else:
                    row.append(None)
            else:
                row.append(None)
        matrix.append(row)

    # latest date
    as_of = instruments_out.get("nat_gas_nyme", {}).get("dates", [""])[- 1]
    return {"instruments": keys, "matrix": matrix, "as_of_date": as_of}

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("CFTC Natural Gas Positioning Data Pipeline — Enhanced")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    warnings_list = []

    cftc_df = fetch_cftc()
    price_s = fetch_prices()

    # Build price alignment map
    price_df_sorted = price_s.reset_index().rename(columns={"date": "price_date"}).sort_values("price_date")
    cftc_dates_sorted = pd.DataFrame({
        "report_date_as_yyyy_mm_dd": cftc_df["report_date_as_yyyy_mm_dd"].drop_duplicates().sort_values().values
    })
    price_aligned = pd.merge_asof(
        cftc_dates_sorted, price_df_sorted,
        left_on="report_date_as_yyyy_mm_dd", right_on="price_date",
        direction="backward",
    ).set_index("report_date_as_yyyy_mm_dd")

    instruments_out = {}
    for inst_key, market_name in INSTRUMENTS.items():
        print(f"[Instrument] {inst_key}...")
        mask   = cftc_df["market_and_exchange_names"].str.strip() == market_name
        inst_df = cftc_df[mask].copy()
        if len(inst_df) == 0:
            w = f"No rows for {inst_key}"
            print(f"  WARNING: {w}")
            warnings_list.append(w)
            continue
        print(f"  Rows: {len(inst_df):,}")
        inst_result = process_instrument(inst_key, inst_df, price_aligned)
        instruments_out[inst_key] = inst_result

    assert "nat_gas_nyme" in instruments_out
    assert len(instruments_out["nat_gas_nyme"]["dates"]) > 200

    latest_date = max(max(v["dates"]) for v in instruments_out.values() if v.get("dates"))

    # Correlation matrix
    print("\n[Correlation Matrix] Computing...")
    corr_matrix = build_correlation_matrix(instruments_out)

    # Strip internal helper arrays before output
    for v in instruments_out.values():
        v.pop("_nets", None)

    output = {
        "meta": {
            "last_updated":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latest_report_date": latest_date,
            "warnings":           warnings_list,
            "price_source":       "yieldchaser/nat-gas-data-pipeline",
        },
        "instruments":        instruments_out,
        "correlation_matrix": corr_matrix,
    }

    print("\n[Sanitise] Cleaning NaN/Inf...")
    output = sanitise(output)

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))

    size_mb = os.path.getsize(OUTPUT_PATH) / 1_048_576
    print(f"\n[Done] {OUTPUT_PATH} ({size_mb:.2f} MB)")
    print(f"  Instruments: {list(instruments_out.keys())}")
    print(f"  Latest date: {latest_date}")
    print(f"  Warnings: {warnings_list or 'none'}")

    with open(OUTPUT_PATH, "r") as f:
        content = f.read()
    if "NaN" in content or "Infinity" in content:
        print("ERROR: NaN/Infinity in JSON!")
        sys.exit(1)
    print("  NaN/Infinity check: PASSED")
    print("\n=== PIPELINE COMPLETE ===")


if __name__ == "__main__":
    main()
