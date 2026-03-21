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
    # Core 9 (original)
    "nat_gas_nyme":        "NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE",
    "nat_gas_ld1":         "NAT GAS ICE LD1 - ICE FUTURES ENERGY DIV",
    "nat_gas_ice_pen":     "NAT GAS ICE PEN - ICE FUTURES ENERGY DIV",
    "henry_hub_nyme":      "HENRY HUB - NEW YORK MERCANTILE EXCHANGE",
    "hh_last_day":         "HENRY HUB LAST DAY FIN - NEW YORK MERCANTILE EXCHANGE",
    "hh_penult_fin":       "HENRY HUB PENULTIMATE FIN - NEW YORK MERCANTILE EXCHANGE",
    "hh_penult_nat_gas":   "HENRY HUB PENULTIMATE NAT GAS - NEW YORK MERCANTILE EXCHANGE",
    "hh_index_ice":        "HENRY HUB INDEX - ICE FUTURES ENERGY DIV",
    "hh_basis_ice":        "HENRY HUB BASIS - ICE FUTURES ENERGY DIV",
    # New instruments from discovery (>= 50 rows)
    "hh_tailgate_basis":   "HENRY HUB - TAILGATE LOUISIANA (BASIS) - ICE FUTURES ENERGY DIV",
    "hh_tailgate_index":   "HENRY HUB - TAILGATE LOUISIANA (INDEX) - ICE FUTURES ENERGY DIV",
    "nat_gas_legacy":      "NATURAL GAS - NEW YORK MERCANTILE EXCHANGE",
    "nat_gas_ld1_fixed":   "NATURAL GAS HENRY LD1 FIXED - ICE FUTURES ENERGY DIV",
    "nat_gas_pen_ice":     "NATURAL GAS PENULTIMATE ICE - ICE FUTURES ENERGY DIV",
    "nat_gas_midcon":      "NATURAL GAS PIPELINE-MID-CONTINENT POOL PIN (BASIS) - ICE FUTURES ENERGY DIV",
    "nat_gas_texok":       "NATURAL GAS PIPELINE-TEXOK (BASIS) - ICE FUTURES ENERGY DIV",
    "nat_gas_ventura":     "NORTHERN NATURAL GAS - VENTURA (BASIS) - ICE FUTURES ENERGY DIV",
    "nat_gas_ld1_texok":   "NAT GAS LD1 for GDD -TEXOK - ICE FUTURES ENERGY DIV",
    "hh_penult_nasdaq":    "HHUB NAT GAS PENULT FINL-10000 - NASDAQ FUTURES",
}
INSTRUMENT_LABELS = {
    "nat_gas_nyme":        "Nat Gas NYME",
    "nat_gas_ld1":         "Nat Gas LD1",
    "nat_gas_ice_pen":     "NAT GAS ICE PEN",
    "henry_hub_nyme":      "Henry Hub NYME",
    "hh_last_day":         "HH Last Day Fin",
    "hh_penult_fin":       "HH Penultimate Fin",
    "hh_penult_nat_gas":   "HH Penultimate Nat Gas",
    "hh_index_ice":        "HH Index ICE",
    "hh_basis_ice":        "HH Basis ICE",
    "hh_tailgate_basis":   "HH Tailgate Basis",
    "hh_tailgate_index":   "HH Tailgate Index",
    "nat_gas_legacy":      "Nat Gas Legacy",
    "nat_gas_ld1_fixed":   "NG LD1 Fixed ICE",
    "nat_gas_pen_ice":     "NG Penult ICE",
    "nat_gas_midcon":      "NG Midcon Basis",
    "nat_gas_texok":       "NG Texok Basis",
    "nat_gas_ventura":     "NG Ventura Basis",
    "nat_gas_ld1_texok":   "NG LD1 Texok",
    "hh_penult_nasdaq":    "HH Penult Nasdaq",
}

# NOTE: exact CFTC column names
TRADER_COLUMNS = {
    "managed_money": {
        "long":         "m_money_positions_long_all",
        "short":        "m_money_positions_short_all",
        "spread":       "m_money_positions_spread_all",
        "change_long":  "change_in_m_money_long_all",
        "change_short": "change_in_m_money_short_all",
    },
    "swap_dealers": {
        "long":         "swap_positions_long_all",
        "short":        "swap__positions_short_all",   # double underscore
        "change_long":  "change_in_swap_long_all",
        "change_short": "change_in_swap_short_all",
    },
    "producers": {
        "long":         "prod_merc_positions_long",    # no _all suffix
        "short":        "prod_merc_positions_short",
        "change_long":  "change_in_prod_merc_long_all",
        "change_short": "change_in_prod_merc_short_all",
    },
    "other_reportables": {
        "long":         "other_rept_positions_long",    # no _all suffix
        "short":        "other_rept_positions_short",
        "change_long":  "change_in_other_rept_long_all",
        "change_short": "change_in_other_rept_short_all",
    },
    "non_reportables": {
        "long":         "nonrept_positions_long_all",
        "short":        "nonrept_positions_short_all",
        "change_long":  None,
        "change_short": None,
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
    """Rolling COT Index strictly 0-100. Requires full window; NaN before that."""
    roll_min = series.rolling(window, min_periods=window).min()
    roll_max = series.rolling(window, min_periods=window).max()
    denom = roll_max - roll_min
    idx = np.where(
        denom == 0,
        50.0,
        (series - roll_min) / denom * 100
    )
    idx = np.clip(idx, 0.0, 100.0)
    result = pd.Series(idx, index=series.index)
    result[denom.isna()] = np.nan
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


def composite_score(mm_z, mm_cot, prod_z, nonrept_z=None):
    """Return integer -3 to +3 with non-reportable contrarian logic."""
    if mm_z is None or (isinstance(mm_z, float) and np.isnan(mm_z)):
        return 0
    score = 0
    if mm_z >= 1.5:  score += 1
    if mm_z >= 2.0:  score += 1
    if mm_cot is not None and not (isinstance(mm_cot, float) and np.isnan(mm_cot)) and mm_cot >= 80: score += 1
    if mm_z <= -1.5: score -= 1
    if mm_z <= -2.0: score -= 1
    if mm_cot is not None and not (isinstance(mm_cot, float) and np.isnan(mm_cot)) and mm_cot <= 20: score -= 1
    if prod_z is not None and not (isinstance(prod_z, float) and np.isnan(prod_z)):
        if mm_z > 1.0 and prod_z < -1.0: score += 1
        if mm_z < -1.0 and prod_z > 1.0: score -= 1
    # Non-reportable contrarian signal (F3)
    if nonrept_z is not None and not (isinstance(nonrept_z, float) and np.isnan(nonrept_z)):
        if nonrept_z > 1.5 and mm_z < 0:  score -= 1
        if nonrept_z < -1.5 and mm_z > 0: score += 1
    return int(np.clip(score, -3, 3))


def oi_regime(oi_roc: float, price_roc: float) -> str:
    """F4: Four-state OI regime."""
    if   oi_roc >  3 and price_roc >  0: return "Accumulation"
    elif oi_roc >  3 and price_roc <= 0: return "Distribution"
    elif oi_roc < -3 and price_roc <= 0: return "Long Liquidation"
    elif oi_roc < -3 and price_roc >  0: return "Short Covering"
    return "Neutral"


def momentum_score(change_net: pd.Series) -> pd.Series:
    """F5: Positioning momentum 0-100."""
    with np.errstate(divide='ignore', invalid='ignore'):
        raw = change_net.abs() / change_net.rolling(13).std()
    score = raw.expanding().rank(pct=True) * 100
    return pd.Series(np.clip(score.values, 0, 100), index=change_net.index)


def lagged_corr(net: pd.Series, price: pd.Series, lags=(1, 2, 3, 4), window=20) -> dict:
    """F6: Rolling correlation of net position with future price changes."""
    result = {}
    pct_chg = price.pct_change()
    for lag in lags:
        future = pct_chg.shift(-lag)
        result[f'lag_{lag}w'] = net.rolling(window).corr(future).tolist()
    return result

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

    # OI regime (F4)
    oi_roc_4w = oi.pct_change(4) * 100
    price_roc_4w = price_series.pct_change(4) * 100
    oi_regimes = [
        oi_regime(
            float(oi_roc_4w.iloc[i]) if not pd.isna(oi_roc_4w.iloc[i]) else 0,
            float(price_roc_4w.iloc[i]) if not pd.isna(price_roc_4w.iloc[i]) else 0
        ) if not (pd.isna(oi_roc_4w.iloc[i]) or pd.isna(price_roc_4w.iloc[i])) else "Neutral"
        for i in range(len(oi_roc_4w))
    ]

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
        "oi_roc_4w":     oi_roc_4w.tolist(),
        "oi_regime":     oi_regimes,
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

        # Momentum score (F5)
        mom_score = momentum_score(change_net)

        # Lagged correlation (F6, only for managed_money to keep JSON lean)
        lagged_c = lagged_corr(net, price_series) if trader == "managed_money" else {}

        # MM Spread (F2)
        spread_arr = []
        spread_pct_arr = []
        if trader == "managed_money":
            spread_col = cols.get("spread")
            if spread_col and spread_col in inst_df.columns:
                sp = pd.to_numeric(inst_df[spread_col], errors="coerce")
                spread_arr = sp.tolist()
                with np.errstate(divide='ignore', invalid='ignore'):
                    spread_pct_arr = np.where(oi > 0, sp / oi * 100, np.nan).tolist()

        trader_dict = {
            "long":             long_s.tolist(),
            "short":            short_s.tolist(),
            "net":              net.tolist(),
            "pct_of_oi":        pct_oi.tolist(),
            "z_score":          z_score.tolist(),
            "pct_rank":         pct_rank_s.tolist(),
            "rolling_corr":     rolling_corr.tolist(),
            "cot_index":        cot_indices,
            "change_long":      change_long.tolist(),
            "change_short":     change_short.tolist(),
            "change_net":       change_net.tolist(),
            "momentum_score":   mom_score.tolist(),
            "seasonal_deviation": deviation.tolist(),
            "extremes":         extremes,
        }
        if lagged_c:
            trader_dict["lagged_corr"] = lagged_c
        if spread_arr:
            trader_dict["spread"]     = spread_arr
            trader_dict["spread_pct"] = spread_pct_arr

        if trader == "managed_money":
            edge = (z_score - z_score.shift(1)) - (price_pct_change * 5)
            trader_dict["edge"] = edge.tolist()
            trader_dict["seasonal_avg_by_week"] = avg_by_week
            trader_dict["seasonal_std_by_week"] = std_by_week

        result[trader] = trader_dict

    # Composite score uses MM, Producers, Non-Reportables z-scores
    mm  = result.get("managed_money", {})
    pr  = result.get("producers", {})
    nr  = result.get("non_reportables", {})
    mm_z_list   = mm.get("z_score", []) if isinstance(mm, dict) else []
    pr_z_list   = pr.get("z_score", []) if isinstance(pr, dict) else []
    nr_z_list   = nr.get("z_score", []) if isinstance(nr, dict) else []
    cot_list    = (mm.get("cot_index", {}) or {}).get("w156", []) if isinstance(mm, dict) else []
    comp = []
    for i in range(len(dates_str)):
        mz  = mm_z_list[i]  if i < len(mm_z_list)  else None
        pz  = pr_z_list[i]  if i < len(pr_z_list)  else None
        nz  = nr_z_list[i]  if i < len(nr_z_list)  else None
        ct  = cot_list[i]   if i < len(cot_list)    else None
        comp.append(composite_score(mz, ct, pz, nz))
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
