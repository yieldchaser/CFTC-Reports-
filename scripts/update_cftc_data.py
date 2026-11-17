#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CFTC Natural Gas Positioning Data Pipeline — Enhanced & Audited Master Plan
Includes:
  - Disaggregated Futures & Options Combined (kh3c-gbw2)
  - Disaggregated Futures Only (72hh-3qpy) for linear Net Option Delta calculation
  - Pure NYMEX European Options (02365U)
  - Pruned dead contracts & upgraded regional basis powerhouses
  - Synthetic Composites: comp_hh_prompt & comp_hh_clean
  - Total Speculative positioning (Managed Money + Other Reportables)
  - Inter-benchmark correlation matrix (excluding regional basis)
  - CLI --force argument
"""
import argparse
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

# ─── GitHub Actions helpers ────────────────────────────────────────────────────

def _set_gha_output(name: str, value: str):
    """Write a step output for GitHub Actions (GITHUB_OUTPUT env file)."""
    gha_output = os.environ.get("GITHUB_OUTPUT")
    if gha_output:
        with open(gha_output, "a") as f:
            f.write(f"{name}={value}\n")
    else:
        print(f"[GHA] {name}={value}")

# ─── Configuration ─────────────────────────────────────────────────────────────

CFTC_COMBINED_URL = (
    "https://publicreporting.cftc.gov/resource/kh3c-gbw2.csv"
    "?commodity_name=NATURAL%20GAS"
    "&$order=report_date_as_yyyy_mm_dd%20DESC,cftc_contract_market_code%20ASC"
)
CFTC_FUTURES_URL = (
    "https://publicreporting.cftc.gov/resource/72hh-3qpy.csv"
    "?commodity_name=NATURAL%20GAS"
    "&$order=report_date_as_yyyy_mm_dd%20DESC,cftc_contract_market_code%20ASC"
)
OUTPUT_PATH = "data/cftc_processed.json"

# Tracked markets: key -> (CFTC contract market code, current market name).
# Rows are matched by CODE. CFTC renamed every energy market in Feb 2022
# (e.g. "NATURAL GAS - NEW YORK MERCANTILE EXCHANGE" -> "NAT GAS NYME - ..."),
# so matching by name silently dropped all pre-2022 history. The name is only
# a fallback should a code ever be reassigned.
INSTRUMENT_SPECS = {
    # Prompt benchmarks
    "nat_gas_nyme":     ("023651", "NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE"),
    "nat_gas_ld1":      ("023391", "NAT GAS ICE LD1 - ICE FUTURES ENERGY DIV"),
    "nat_gas_ice_pen":  ("023392", "NAT GAS ICE PEN - ICE FUTURES ENERGY DIV"),
    "opt_eur_nyme":     ("02365U", "EUR STYLE NATURAL GAS OPTIONS - NEW YORK MERCANTILE EXCHANGE"),
    # Henry Hub cleared swaps
    "hh_last_day":      ("023A55", "HENRY HUB LAST DAY FIN - NEW YORK MERCANTILE EXCHANGE"),
    "hh_penult_fin":    ("023A56", "HENRY HUB PENULTIMATE FIN - NEW YORK MERCANTILE EXCHANGE"),
    "hh_nymex_nn":      ("03565B", "HENRY HUB - NEW YORK MERCANTILE EXCHANGE"),
    "hh_penult_ng":     ("03565C", "HENRY HUB PENULTIMATE NAT GAS - NEW YORK MERCANTILE EXCHANGE"),
    "hh_index_ice":     ("0233AH", "HENRY HUB INDEX - ICE FUTURES ENERGY DIV"),
    # Regional basis (ICE, differential to Henry Hub)
    "waha_basis":       ("023399", "WAHA FIN BASIS - ICE FUTURES ENERGY DIV"),
    "hsc_basis":        ("023398", "HSC FIN BASIS - ICE FUTURES ENERGY DIV"),
    "ngpl_txok_basis":  ("0233B1", "NGPL TXOK BASIS - ICE FUTURES ENERGY DIV"),
    "dominion_basis":   ("0233A3", "DOMINION - SOUTH POINT (BASIS) - ICE FUTURES ENERGY DIV"),
    "tetco_m2_basis":   ("0233DR", "TETCO M2 Basis (Receipts) - ICE FUTURES ENERGY DIV"),
    "transco_z6_basis": ("0233CU", "TRANSCO ZONE 6 BASIS - ICE FUTURES ENERGY DIV"),
    "rex_z3_basis":     ("0233EB", "REX ZONE 3 BASIS - ICE FUTURES ENERGY DIV"),
    "chicago_basis":    ("023397", "CHICAGO FIN BASIS - ICE FUTURES ENERGY DIV"),
    "cig_rockies_basis":("02339U", "CIG ROCKIES BASIS - ICE FUTURES ENERGY DIV"),
    "nwp_rockies_basis":("023395", "NWP ROCKIES FIN BASIS - ICE FUTURES ENERGY DIV"),
    "socal_basis":      ("023393", "SOCAL BORDER FIN BASIS - ICE FUTURES ENERGY DIV"),
    "aeco_basis":       ("023396", "AECO FIN BASIS - ICE FUTURES ENERGY DIV"),
}
INSTRUMENTS = {k: v[1] for k, v in INSTRUMENT_SPECS.items()}
INSTRUMENT_CODES = {k: v[0] for k, v in INSTRUMENT_SPECS.items()}

# Henry Hub-priced contracts (everything that is not a regional basis differential)
BENCHMARK_KEYS = [
    "nat_gas_nyme", "nat_gas_ld1", "nat_gas_ice_pen", "opt_eur_nyme",
    "hh_last_day", "hh_penult_fin", "hh_nymex_nn", "hh_penult_ng", "hh_index_ice",
]

INSTRUMENT_LABELS = {
    # Core Benchmarks & Cleared Swaps
    "nat_gas_nyme":        "Nat Gas NYME",
    "nat_gas_ld1":         "Nat Gas LD1",
    "nat_gas_ice_pen":     "NAT GAS ICE PEN",
    "hh_last_day":         "HH Last Day Fin",
    "hh_penult_fin":       "HH Penultimate Fin",
    "hh_index_ice":        "HH Index ICE",
    "hh_nymex_nn":         "HH NYMEX Swap (NN)",
    "hh_penult_ng":        "HH Penultimate NG",
    "opt_eur_nyme":        "EUR Options NYME",
    # Regional basis
    "waha_basis":          "Waha Basis",
    "hsc_basis":           "HSC Basis",
    "dominion_basis":      "Dominion South Basis",
    "aeco_basis":          "AECO Basis",
    "chicago_basis":       "Chicago Basis",
    "ngpl_txok_basis":     "NGPL TXOK Basis",
    "tetco_m2_basis":      "TETCO M2 Basis",
    "transco_z6_basis":    "Transco Z6 NY Basis",
    "rex_z3_basis":        "REX Zone 3 Basis",
    "cig_rockies_basis":   "CIG Rockies Basis",
    "nwp_rockies_basis":   "NWP Rockies Basis",
    "socal_basis":         "SoCal Border Basis",
    # Synthetic Composites
    "comp_hh_prompt":      "HH Prompt Core Composite",
    "comp_hh_clean":       "HH Clean Outright Curve",
}

# CFTC column names
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
        "short":        "swap__positions_short_all",   # double underscore in CFTC data
        "change_long":  "change_in_swap_long_all",
        "change_short": "change_in_swap_short_all",
    },
    "producers": {
        "long":         "prod_merc_positions_long",
        "short":        "prod_merc_positions_short",
        "change_long":  "change_in_prod_merc_long_all",
        "change_short": "change_in_prod_merc_short_all",
    },
    "other_reportables": {
        "long":         "other_rept_positions_long",
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

# Contract size (MMBtu per contract). The live value is parsed from the CFTC
# `contract_units` field on every run (see parse_contract_size); this table is
# only a fallback if CFTC ever omits or reformats that field. Needed because
# NYMEX NG is 10,000 MMBtu while most ICE Henry Hub contracts are 2,500 MMBtu,
# so raw contract counts are not comparable across venues.
CONTRACT_SIZE_FALLBACK = {
    "nat_gas_nyme": 10000, "nat_gas_ld1": 2500, "nat_gas_ice_pen": 2500,
    "hh_last_day": 10000, "hh_penult_fin": 10000, "hh_index_ice": 2500,
    "hh_nymex_nn": 2500, "hh_penult_ng": 2500, "opt_eur_nyme": 10000,
    "waha_basis": 2500, "hsc_basis": 2500, "dominion_basis": 2500,
    "aeco_basis": 2500, "chicago_basis": 2500, "ngpl_txok_basis": 2500,
    "tetco_m2_basis": 2500, "transco_z6_basis": 2500, "rex_z3_basis": 2500,
    "cig_rockies_basis": 2500, "nwp_rockies_basis": 2500, "socal_basis": 2500,
}
NYMEX_EQ_MMBTU = 10000   # composites are expressed in NYMEX-equivalent contracts

COMPOSITE_COMPONENTS = {
    "comp_hh_prompt": ["nat_gas_nyme", "nat_gas_ld1", "nat_gas_ice_pen", "opt_eur_nyme"],
    "comp_hh_clean":  ["nat_gas_nyme", "nat_gas_ld1", "nat_gas_ice_pen", "hh_last_day", "hh_penult_fin",
                       "hh_nymex_nn", "hh_penult_ng", "hh_index_ice"],
}

WITHDRAWAL_MONTHS = {11, 12, 1, 2, 3}
MIN_ZSCORE_OBS   = 20
COT_LOOKBACKS    = {"w26": 26, "w52": 52, "w156": 156}

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _num(v: float):
    """3 decimals is beyond display precision for every field; whole numbers
    (contract counts) are written as ints. Keeps the 20-year payload light."""
    if math.isnan(v) or math.isinf(v):
        return None
    if v.is_integer() and abs(v) < 1e15:
        return int(v)
    return round(v, 3)


def sanitise(obj):
    """Recursively replace NaN/Inf with None; compact floats (see _num)."""
    if isinstance(obj, float):
        return _num(obj)
    if isinstance(obj, (np.floating,)):
        return _num(float(obj))
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, dict):
        return {k: sanitise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitise(v) for v in obj]
    return obj


def parse_contract_size(units):
    """Extract MMBtu per contract from a CFTC `contract_units` string,
    e.g. "(CONTRACTS OF 10,000 MMBTU'S)" -> 10000. Returns None if unparseable."""
    if not isinstance(units, str):
        return None
    import re
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*MM\s*BTU", units.upper())
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(v) if v > 0 else None


def market_mask(df: pd.DataFrame, inst_key: str) -> pd.Series:
    """Rows for a tracked market: by CFTC contract code, name as fallback."""
    code = INSTRUMENT_CODES.get(inst_key)
    if code and "cftc_contract_market_code" in df.columns:
        m = df["cftc_contract_market_code"].astype(str).str.strip() == code
        if m.any():
            return m
    return df["market_and_exchange_names"].astype(str).str.strip() == INSTRUMENTS[inst_key]


def fetch_with_retry(url, label, timeout=60, retries=3, headers=None):
    if headers is None:
        headers = {
            "Accept": "text/csv",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
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

def _fetch_socrata_paginated(base_url: str, label: str, page_size: int = 50000, max_pages: int = 10) -> pd.DataFrame:
    """Fetch all pages from a Socrata CSV endpoint cleanly without losing rows above $limit."""
    chunks = []
    offset = 0
    for page in range(1, max_pages + 1):
        url = f"{base_url}&$limit={page_size}&$offset={offset}"
        page_label = label if page == 1 else f"{label} p{page}"
        raw = fetch_with_retry(url, page_label)
        chunk = pd.read_csv(io.StringIO(raw), low_memory=False)
        chunks.append(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]


def fetch_cftc_combined() -> pd.DataFrame:
    print("\n[Phase 1.1] Fetching CFTC Disaggregated Futures & Options Combined (kh3c-gbw2)...")
    df = _fetch_socrata_paginated(CFTC_COMBINED_URL, "CFTC Combined")
    print(f"  Rows: {len(df):,}  Cols: {len(df.columns)}")
    assert len(df) > 500
    assert "market_and_exchange_names" in df.columns
    assert "report_date_as_yyyy_mm_dd" in df.columns
    df["report_date_as_yyyy_mm_dd"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"]).astype("datetime64[ns]")
    
    # Ensure 02365U is present
    has_opt = (df["cftc_contract_market_code"].str.strip() == "02365U").any() if "cftc_contract_market_code" in df.columns else False
    if not has_opt:
        print("  Notice: 02365U not found in primary query. Fetching specifically...")
        opt_url = "https://publicreporting.cftc.gov/resource/kh3c-gbw2.csv?cftc_contract_market_code=02365U&$limit=10000"
        raw_opt = fetch_with_retry(opt_url, "CFTC 02365U")
        df_opt = pd.read_csv(io.StringIO(raw_opt), low_memory=False)
        df_opt["report_date_as_yyyy_mm_dd"] = pd.to_datetime(df_opt["report_date_as_yyyy_mm_dd"]).astype("datetime64[ns]")
        df = pd.concat([df, df_opt], ignore_index=True)
        print(f"  Merged 02365U rows: {len(df_opt):,}")

    print("[Phase 1.1] CFTC Combined OK\n")
    return df


def fetch_cftc_futures_only() -> pd.DataFrame:
    print("\n[Phase 1.2] Fetching CFTC Disaggregated Futures Only (72hh-3qpy)...")
    df = _fetch_socrata_paginated(CFTC_FUTURES_URL, "CFTC Futures Only")
    print(f"  Rows: {len(df):,}  Cols: {len(df.columns)}")
    assert len(df) > 500
    assert "market_and_exchange_names" in df.columns
    assert "report_date_as_yyyy_mm_dd" in df.columns
    df["report_date_as_yyyy_mm_dd"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"]).astype("datetime64[ns]")
    print("[Phase 1.2] CFTC Futures Only OK\n")
    return df

# ─── Fetch Prices ──────────────────────────────────────────────────────────────

def fetch_prices() -> pd.Series:
    print("[Phase 1.3] Fetching NG price data from Yahoo Finance...")
    import urllib.request
    import urllib.parse

    symbol = urllib.parse.quote("NG=F")
    urls = [
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=max",
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=max",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    payload = None
    retries = 4
    for attempt in range(1, retries + 1):
        url = urls[(attempt - 1) % len(urls)]
        try:
            print(f"  [Prices] Attempt {attempt}/{retries}: {url[:80]}...")
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.load(resp)
            print("  [Prices] OK")
            break
        except Exception as exc:
            print(f"  [Prices] Error: {exc}")
            if attempt < retries:
                time.sleep(2 ** attempt)

    if not payload:
        raise RuntimeError("All attempts failed to fetch prices from Yahoo Finance")

    result = payload.get('chart', {}).get('result')
    if not result:
        raise RuntimeError("Yahoo Finance returned no data for NG=F")

    timestamps = result[0].get('timestamp', [])
    closes = result[0].get('indicators', {}).get('quote', [{}])[0].get('close', [])

    dates = []
    prices = []
    for ts, close in zip(timestamps, closes):
        if ts is None or close is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        dates.append(pd.to_datetime(dt))
        prices.append(float(close))

    df = pd.DataFrame({"date": dates, "price": prices})
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").ffill()

    price = df.set_index("date")["price"]
    print(f"  Price range: {price.index.min().date()} to {price.index.max().date()}")
    print("[Phase 1.3] Price OK\n")
    return price

# ─── Derived Mathematical Metrics ─────────────────────────────────────────────

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
    """Return seasonal_avg_by_week (52-element), seasonal_std_by_week, and seasonal_deviation series."""
    if hasattr(dates, 'dt'):
        week_of_year = dates.dt.isocalendar().week.values.astype(int)
    else:
        week_of_year = pd.DatetimeIndex(dates).isocalendar().week.values.astype(int)
    # Map ISO week 53 (e.g., 2026-12-29) into week 52 to prevent NaN year-end gaps
    week_of_year = np.clip(week_of_year, 1, 52)
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
    # Non-reportable contrarian signal
    if nonrept_z is not None and not (isinstance(nonrept_z, float) and np.isnan(nonrept_z)):
        if nonrept_z > 1.5 and mm_z < 0:  score -= 1
        if nonrept_z < -1.5 and mm_z > 0: score += 1
    return int(np.clip(score, -3, 3))


def oi_regime(oi_roc: float, price_roc: float) -> str:
    """Four-state OI regime."""
    if   oi_roc >  3 and price_roc >  0: return "Accumulation"
    elif oi_roc >  3 and price_roc <= 0: return "Distribution"
    elif oi_roc < -3 and price_roc <= 0: return "Long Liquidation"
    elif oi_roc < -3 and price_roc >  0: return "Short Covering"
    return "Neutral"


def momentum_score(change_net: pd.Series) -> pd.Series:
    """Positioning momentum 0-100."""
    with np.errstate(divide='ignore', invalid='ignore'):
        raw = change_net.abs() / change_net.rolling(13).std()
    score = raw.expanding().rank(pct=True) * 100
    return pd.Series(np.clip(score.values, 0, 100), index=change_net.index)


def lagged_corr(net: pd.Series, price: pd.Series, lags=(1, 2, 3, 4), window=20) -> dict:
    """Rolling correlation of net position with future price changes."""
    result = {}
    pct_chg = price.pct_change()
    for lag in lags:
        future = pct_chg.shift(-lag)
        result[f'lag_{lag}w'] = net.rolling(window).corr(future).tolist()
    return result


def compute_trader_stats(net: pd.Series, long_s: pd.Series, short_s: pd.Series,
                         oi: pd.Series, price_series: pd.Series, dates_raw,
                         change_long: pd.Series, change_short: pd.Series) -> dict:
    """Standardized statistical calculation for a trader category."""
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_oi = np.where(oi > 0, (long_s + short_s) / oi, np.nan)

    z_score      = expanding_zscore(net)
    pct_rank_s   = fast_pct_rank(net)
    rolling_corr = net.rolling(20).corr(price_series)
    cot_indices  = {lb: cot_index(net, w).tolist() for lb, w in COT_LOOKBACKS.items()}
    
    change_net   = change_long - change_short
    avg_by_week, std_by_week, deviation = seasonal_stats(net, dates_raw)
    mom_score    = momentum_score(change_net)

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

    return {
        "long":               long_s.tolist(),
        "short":              short_s.tolist(),
        "net":                net.tolist(),
        "pct_of_oi":          pct_oi.tolist(),
        "z_score":            z_score.tolist(),
        "pct_rank":           pct_rank_s.tolist(),
        "rolling_corr":       rolling_corr.tolist(),
        "cot_index":          cot_indices,
        "change_long":        change_long.tolist(),
        "change_short":       change_short.tolist(),
        "change_net":         change_net.tolist(),
        "momentum_score":     mom_score.tolist(),
        "seasonal_deviation": deviation.tolist(),
        "extremes":           extremes,
        # Keep underlying series for helper calculations
        "_z_score_series":    z_score,
        "_seasonal_avg":      avg_by_week,
        "_seasonal_std":      std_by_week,
    }

# ─── Process One Instrument ────────────────────────────────────────────────────

def process_instrument(inst_key: str, inst_df: pd.DataFrame, price_aligned: pd.DataFrame,
                       fut_df: pd.DataFrame = None) -> dict:
    inst_df = inst_df.drop_duplicates(subset=["report_date_as_yyyy_mm_dd"], keep="last")
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

    # OI regime
    oi_roc_4w = oi.pct_change(4) * 100
    price_roc_4w = price_series.pct_change(4) * 100
    oi_regimes = [
        oi_regime(
            float(oi_roc_4w.iloc[i]) if not pd.isna(oi_roc_4w.iloc[i]) else 0,
            float(price_roc_4w.iloc[i]) if not pd.isna(price_roc_4w.iloc[i]) else 0
        ) if not (pd.isna(oi_roc_4w.iloc[i]) or pd.isna(price_roc_4w.iloc[i])) else "Neutral"
        for i in range(len(oi_roc_4w))
    ]

    # Concentration (NYME physical)
    concentration = {}
    if inst_key == "nat_gas_nyme":
        for k, col in CONCENTRATION_COLS.items():
            if col in inst_df.columns:
                concentration[k] = pd.to_numeric(inst_df[col], errors="coerce").tolist()

    # Contract size: latest CFTC `contract_units` string, fallback table otherwise
    units_str = None
    if "contract_units" in inst_df.columns:
        nonnull = inst_df["contract_units"].dropna()
        if len(nonnull):
            units_str = str(nonnull.iloc[-1]).strip()
    parsed_size = parse_contract_size(units_str)
    size_mmbtu = parsed_size or CONTRACT_SIZE_FALLBACK.get(inst_key)
    print(f"    [Contract] {inst_key}: units='{units_str}' -> {size_mmbtu} MMBtu"
          f" ({'CFTC' if parsed_size else 'fallback'})")

    result = {
        "label":         INSTRUMENT_LABELS.get(inst_key, inst_key),
        "dates":         dates_str,
        "price":         price_series.tolist(),
        "open_interest": oi.tolist(),
        "oi_roc_4w":     oi_roc_4w.tolist(),
        "oi_regime":     oi_regimes,
        "season":        season,
        "contract_units":       units_str,
        "contract_size_mmbtu":  size_mmbtu,
        "contract_size_source": "cftc" if parsed_size else "fallback",
    }
    if concentration:
        result["concentration"] = concentration

    trader_nets = {}
    trader_data_raw = {}

    for trader, cols in TRADER_COLUMNS.items():
        lc, sc = cols["long"], cols["short"]
        long_s  = pd.to_numeric(inst_df[lc], errors="coerce").fillna(0) if lc in inst_df.columns else pd.Series(0.0, index=inst_df.index)
        short_s = pd.to_numeric(inst_df[sc], errors="coerce").fillna(0) if sc in inst_df.columns else pd.Series(0.0, index=inst_df.index)
        net     = long_s - short_s
        trader_nets[trader] = net

        # Changes
        clc, csc = cols.get("change_long"), cols.get("change_short")
        if clc and clc in inst_df.columns and inst_df[clc].notna().any():
            chg_l = pd.to_numeric(inst_df[clc], errors="coerce").fillna(0)
        else:
            chg_l = long_s.diff().fillna(0)
            
        if csc and csc in inst_df.columns and inst_df[csc].notna().any():
            chg_s = pd.to_numeric(inst_df[csc], errors="coerce").fillna(0)
        else:
            chg_s = short_s.diff().fillna(0)

        trader_data_raw[trader] = {
            "long": long_s, "short": short_s, "net": net,
            "change_long": chg_l, "change_short": chg_s
        }

        t_dict = compute_trader_stats(net, long_s, short_s, oi, price_series, dates_raw, chg_l, chg_s)
        
        # Managed Money specifics
        if trader == "managed_money":
            z_s = t_dict.pop("_z_score_series")
            edge = (z_s - z_s.shift(1)) - (price_pct_change * 5)
            t_dict["edge"] = edge.tolist()
            t_dict["seasonal_avg_by_week"] = t_dict.pop("_seasonal_avg")
            t_dict["seasonal_std_by_week"] = t_dict.pop("_seasonal_std")
            t_dict["lagged_corr"] = lagged_corr(net, price_series)
            
            # Spread
            spread_col = cols.get("spread")
            if spread_col and spread_col in inst_df.columns:
                sp = pd.to_numeric(inst_df[spread_col], errors="coerce").fillna(0)
                t_dict["spread"] = sp.tolist()
                with np.errstate(divide='ignore', invalid='ignore'):
                    t_dict["spread_pct"] = np.where(oi > 0, sp / oi * 100, np.nan).tolist()
            else:
                t_dict["spread"] = [0.0] * len(inst_df)
                t_dict["spread_pct"] = [0.0] * len(inst_df)
        else:
            t_dict.pop("_z_score_series", None)
            t_dict.pop("_seasonal_avg", None)
            t_dict.pop("_seasonal_std", None)

        result[trader] = t_dict

    # Total Speculative: Managed Money + Other Reportables
    mm_raw = trader_data_raw["managed_money"]
    ot_raw = trader_data_raw["other_reportables"]
    spec_long  = mm_raw["long"] + ot_raw["long"]
    spec_short = mm_raw["short"] + ot_raw["short"]
    spec_net   = spec_long - spec_short
    spec_chg_l = mm_raw["change_long"] + ot_raw["change_long"]
    spec_chg_s = mm_raw["change_short"] + ot_raw["change_short"]
    
    spec_dict = compute_trader_stats(spec_net, spec_long, spec_short, oi, price_series, dates_raw, spec_chg_l, spec_chg_s)
    spec_dict.pop("_z_score_series", None)
    spec_dict.pop("_seasonal_avg", None)
    spec_dict.pop("_seasonal_std", None)
    spec_dict["lagged_corr"] = lagged_corr(spec_net, price_series)
    result["total_speculative"] = spec_dict

    # Net Option Delta Calculation
    # For nat_gas_nyme, nat_gas_ld1, nat_gas_ice_pen:
    if fut_df is not None and inst_key in ["nat_gas_nyme", "nat_gas_ld1", "nat_gas_ice_pen"]:
        fut_sub = fut_df[market_mask(fut_df, inst_key)].copy()
        if len(fut_sub) > 0:
            fut_sub = fut_sub.drop_duplicates(subset=["report_date_as_yyyy_mm_dd"], keep="last")
            fut_sub = fut_sub.sort_values("report_date_as_yyyy_mm_dd").set_index("report_date_as_yyyy_mm_dd")
            # Align with inst_df dates
            aligned_fut = inst_df[["report_date_as_yyyy_mm_dd"]].join(fut_sub, on="report_date_as_yyyy_mm_dd")
            
            # MM net futures
            f_mm_l = pd.to_numeric(aligned_fut.get("m_money_positions_long_all", 0), errors="coerce").fillna(0)
            f_mm_s = pd.to_numeric(aligned_fut.get("m_money_positions_short_all", 0), errors="coerce").fillna(0)
            f_mm_net = f_mm_l - f_mm_s
            mm_opt_delta = mm_raw["net"] - f_mm_net
            result["managed_money"]["option_delta_net"] = mm_opt_delta.tolist()
            
            # Total Speculative net futures
            f_ot_l = pd.to_numeric(aligned_fut.get("other_rept_positions_long", 0), errors="coerce").fillna(0)
            f_ot_s = pd.to_numeric(aligned_fut.get("other_rept_positions_short", 0), errors="coerce").fillna(0)
            f_spec_net = (f_mm_l + f_ot_l) - (f_mm_s + f_ot_s)
            spec_opt_delta = spec_net - f_spec_net
            result["total_speculative"]["option_delta_net"] = spec_opt_delta.tolist()
            print(f"    [Option Delta] {inst_key}: latest MM delta = {mm_opt_delta.iloc[-1]:,.0f}, Spec delta = {spec_opt_delta.iloc[-1]:,.0f}")

    # Pure options contract (02365U): all positions are 100% pure option delta
    if inst_key == "opt_eur_nyme":
        result["managed_money"]["option_delta_net"] = mm_raw["net"].tolist()
        result["total_speculative"]["option_delta_net"] = spec_net.tolist()
        print(f"    [Option Delta] opt_eur_nyme: pure options contract, latest MM delta = {mm_raw['net'].iloc[-1]:,.0f}, Spec delta = {spec_net.iloc[-1]:,.0f}")

    # Composite scores (-3 to +3)
    mm  = result.get("managed_money", {})
    pr  = result.get("producers", {})
    nr  = result.get("non_reportables", {})
    mm_z_list = mm.get("z_score", [])
    pr_z_list = pr.get("z_score", [])
    nr_z_list = nr.get("z_score", [])
    cot_list  = (mm.get("cot_index", {}) or {}).get("w156", [])
    comp = []
    for i in range(len(dates_str)):
        mz = mm_z_list[i] if i < len(mm_z_list) else None
        pz = pr_z_list[i] if i < len(pr_z_list) else None
        nz = nr_z_list[i] if i < len(nr_z_list) else None
        ct = cot_list[i]  if i < len(cot_list)  else None
        comp.append(composite_score(mz, ct, pz, nz))
    result["composite_scores"] = comp

    result["_raw"] = {
        "dates_raw": dates_raw,
        "oi": oi,
        "price_series": price_series,
        "trader_data_raw": trader_data_raw,
        "spec_long": spec_long,
        "spec_short": spec_short,
        "spec_net": spec_net,
        "spec_chg_l": spec_chg_l,
        "spec_chg_s": spec_chg_s,
    }
    return result

# ─── Synthetic Composites ─────────────────────────────────────────────────────

def synthesize_composite(comp_key: str, component_keys: list, instruments_out: dict,
                         include_options_delta=False) -> dict:
    """Build a synthetic composite in NYMEX-equivalent contracts (10,000 MMBtu).

    Components trade in different sizes (NYMEX/CME 10,000 MMBtu, ICE and the
    CME NN/NP look-alikes 2,500 MMBtu), so each component is scaled by
    size / 10,000 before summing. The composite is defined only on report
    dates where EVERY component reports: zero-filling a component that has not
    started yet would create a structural break in the history."""
    print(f"\n[Composite] Building {comp_key} ({INSTRUMENT_LABELS[comp_key]})...")
    comps = [k for k in component_keys if k in instruments_out]
    missing = [k for k in component_keys if k not in instruments_out]
    if missing:
        print(f"  WARNING: components missing from this run: {missing}")
    if not comps:
        raise RuntimeError(f"No components available for {comp_key}")
    scale = {k: (instruments_out[k].get("contract_size_mmbtu") or CONTRACT_SIZE_FALLBACK.get(k, NYMEX_EQ_MMBTU))
                / NYMEX_EQ_MMBTU for k in comps}
    print("  Scale to NYMEX-eq: " + ", ".join(f"{k} x{scale[k]:g}" for k in comps))

    common = None
    for k in comps:
        d = set(instruments_out[k]["_raw"]["dates_raw"].tolist())
        common = d if common is None else common & d
    dates_raw = pd.Series(sorted(common)).reset_index(drop=True)
    dates_str = dates_raw.dt.strftime("%Y-%m-%d").tolist()

    # Price on those dates (same NG=F alignment as the instruments)
    ref = instruments_out["nat_gas_nyme"]["_raw"]
    ref_price = pd.Series(ref["price_series"].values, index=ref["dates_raw"].values)
    price_series = pd.Series(ref_price.reindex(dates_raw.values).values, index=dates_raw.index, dtype="float64")
    price_pct_change = price_series.pct_change()

    comp_oi = pd.Series(0.0, index=dates_raw.index)
    traders_agg = {t: {f: pd.Series(0.0, index=dates_raw.index)
                       for f in ("long", "short", "spread", "change_long", "change_short")}
                   for t in TRADER_COLUMNS}
    spec_agg = {f: pd.Series(0.0, index=dates_raw.index) for f in ("long", "short", "change_long", "change_short")}

    for k in comps:
        c_raw = instruments_out[k]["_raw"]
        f = scale[k]
        pos = pd.Series(range(len(c_raw["dates_raw"])), index=c_raw["dates_raw"].values)
        idx = pos.reindex(dates_raw.values).values.astype(int)   # all present by construction
        comp_oi += c_raw["oi"].iloc[idx].values * f
        for t in TRADER_COLUMNS:
            t_data = c_raw["trader_data_raw"][t]
            for fld in ("long", "short", "change_long", "change_short"):
                traders_agg[t][fld] += t_data[fld].iloc[idx].values * f
            if t == "managed_money":
                sp = instruments_out[k].get("managed_money", {}).get("spread", [])
                if len(sp) == len(pos):
                    traders_agg[t]["spread"] += np.asarray(sp, dtype=float)[idx] * f
        spec_agg["long"] += c_raw["spec_long"].iloc[idx].values * f
        spec_agg["short"] += c_raw["spec_short"].iloc[idx].values * f
        spec_agg["change_long"] += c_raw["spec_chg_l"].iloc[idx].values * f
        spec_agg["change_short"] += c_raw["spec_chg_s"].iloc[idx].values * f

    # Build composite result dict
    season = ["Withdrawal" if m in WITHDRAWAL_MONTHS else "Injection" for m in dates_raw.dt.month]
    oi_roc_4w = comp_oi.pct_change(4) * 100
    price_roc_4w = price_series.pct_change(4) * 100
    oi_regimes = [
        oi_regime(
            float(oi_roc_4w.iloc[i]) if not pd.isna(oi_roc_4w.iloc[i]) else 0,
            float(price_roc_4w.iloc[i]) if not pd.isna(price_roc_4w.iloc[i]) else 0
        ) if not (pd.isna(oi_roc_4w.iloc[i]) or pd.isna(price_roc_4w.iloc[i])) else "Neutral"
        for i in range(len(oi_roc_4w))
    ]

    result = {
        "label":         INSTRUMENT_LABELS[comp_key],
        "dates":         dates_str,
        "price":         price_series.tolist(),
        "open_interest": comp_oi.tolist(),
        "oi_roc_4w":     oi_roc_4w.tolist(),
        "oi_regime":     oi_regimes,
        "season":        season,
        "components":    comps,
        "component_scale": scale,
        "contract_units": "NYMEX-equivalent contracts (10,000 MMBtu)",
        "contract_size_mmbtu": NYMEX_EQ_MMBTU,
        "contract_size_source": "composite",
    }

    # Trader categories
    for trader, cols in TRADER_COLUMNS.items():
        t_agg = traders_agg[trader]
        long_s  = t_agg["long"]
        short_s = t_agg["short"]
        net     = long_s - short_s
        chg_l   = t_agg["change_long"]
        chg_s   = t_agg["change_short"]
        
        t_dict = compute_trader_stats(net, long_s, short_s, comp_oi, price_series, dates_raw, chg_l, chg_s)
        
        if trader == "managed_money":
            z_s = t_dict.pop("_z_score_series")
            edge = (z_s - z_s.shift(1)) - (price_pct_change * 5)
            t_dict["edge"] = edge.tolist()
            t_dict["seasonal_avg_by_week"] = t_dict.pop("_seasonal_avg")
            t_dict["seasonal_std_by_week"] = t_dict.pop("_seasonal_std")
            t_dict["lagged_corr"] = lagged_corr(net, price_series)
            
            # Spread
            sp = t_agg["spread"]
            t_dict["spread"] = sp.tolist()
            with np.errstate(divide='ignore', invalid='ignore'):
                t_dict["spread_pct"] = np.where(comp_oi > 0, sp / comp_oi * 100, np.nan).tolist()
        else:
            t_dict.pop("_z_score_series", None)
            t_dict.pop("_seasonal_avg", None)
            t_dict.pop("_seasonal_std", None)

        result[trader] = t_dict

    # Total Speculative
    spec_long  = spec_agg["long"]
    spec_short = spec_agg["short"]
    spec_net   = spec_long - spec_short
    spec_chg_l = spec_agg["change_long"]
    spec_chg_s = spec_agg["change_short"]
    spec_dict = compute_trader_stats(spec_net, spec_long, spec_short, comp_oi, price_series, dates_raw, spec_chg_l, spec_chg_s)
    spec_dict.pop("_z_score_series", None)
    spec_dict.pop("_seasonal_avg", None)
    spec_dict.pop("_seasonal_std", None)
    spec_dict["lagged_corr"] = lagged_corr(spec_net, price_series)
    result["total_speculative"] = spec_dict

    # Net Option Delta for Prompt Composite
    if comp_key == "comp_hh_prompt":
        # Date-aligned sum of NYMEX-equivalent option deltas across components
        mm_delta_comp = pd.Series(0.0, index=dates_raw.index)
        spec_delta_comp = pd.Series(0.0, index=dates_raw.index)

        for k in comps:
            c_inst = instruments_out[k]
            c_dates = pd.to_datetime(c_inst["dates"])
            mm_d = c_inst.get("managed_money", {}).get("option_delta_net", [])
            sp_d = c_inst.get("total_speculative", {}).get("option_delta_net", [])
            if len(mm_d) == len(c_dates):
                mm_delta_comp += pd.Series(mm_d, index=c_dates).reindex(dates_raw).fillna(0).values * scale[k]
            if len(sp_d) == len(c_dates):
                spec_delta_comp += pd.Series(sp_d, index=c_dates).reindex(dates_raw).fillna(0).values * scale[k]

        result["managed_money"]["option_delta_net"] = mm_delta_comp.tolist()
        result["total_speculative"]["option_delta_net"] = spec_delta_comp.tolist()
        print(f"    [Composite Option Delta] latest MM delta = {mm_delta_comp.iloc[-1]:,.0f}, Spec delta = {spec_delta_comp.iloc[-1]:,.0f}")

    # Composite scores (-3 to +3)
    mm  = result.get("managed_money", {})
    pr  = result.get("producers", {})
    nr  = result.get("non_reportables", {})
    mm_z_list = mm.get("z_score", [])
    pr_z_list = pr.get("z_score", [])
    nr_z_list = nr.get("z_score", [])
    cot_list  = (mm.get("cot_index", {}) or {}).get("w156", [])
    comp = []
    for i in range(len(dates_str)):
        mz = mm_z_list[i] if i < len(mm_z_list) else None
        pz = pr_z_list[i] if i < len(pr_z_list) else None
        nz = nr_z_list[i] if i < len(nr_z_list) else None
        ct = cot_list[i]  if i < len(cot_list)  else None
        comp.append(composite_score(mz, ct, pz, nz))
    result["composite_scores"] = comp

    print(f"  {comp_key}: {len(dates_str)} dates, Latest OI: {comp_oi.iloc[-1]:,.0f}")
    return result

# ─── Correlation Matrix ────────────────────────────────────────────────────────

def build_correlation_matrix(instruments_out: dict, window: int = 52) -> dict:
    """Correlation of weekly Managed Money FLOWS (change in net) across the Henry
    Hub contracts. Flows, not levels: two trending net-position series correlate
    regardless of whether the markets are linked, so level correlation over
    13-52 weeks is mostly spurious."""
    keys = [k for k in BENCHMARK_KEYS if k in instruments_out]
    series_map = {}
    for k in keys:
        inst = instruments_out[k]
        flows = inst.get("managed_money", {}).get("change_net", [])
        dates = inst.get("dates", [])
        if flows and dates:
            series_map[k] = pd.Series(flows, index=pd.to_datetime(dates), dtype="float64").iloc[-window:]

    matrix = []
    for k1 in keys:
        row = []
        for k2 in keys:
            if k1 == k2:
                row.append(1.0)
                continue
            s1, s2 = series_map.get(k1), series_map.get(k2)
            if s1 is None or s2 is None:
                row.append(None)
                continue
            a, b = s1.align(s2, join="inner")
            ok = a.notna() & b.notna()
            row.append(float(a[ok].corr(b[ok])) if ok.sum() >= 10 and a[ok].std() > 0 and b[ok].std() > 0 else None)
        matrix.append(row)

    as_of = instruments_out.get("nat_gas_nyme", {}).get("dates", [""])[-1]
    return {"instruments": keys, "matrix": matrix, "as_of_date": as_of,
            "basis": "weekly change in Managed Money net", "window_weeks": window}

# ─── Coverage Report ──────────────────────────────────────────────────────────

def coverage_report(df: pd.DataFrame, top: int = 40) -> list:
    """List every currently-reporting natural gas market, ranked by latest open
    interest in MMBtu, flagging which ones the dashboard tracks. Printed in the
    CI log and stored in meta so new liquid contracts are easy to spot."""
    latest = df["report_date_as_yyyy_mm_dd"].max()
    recent = df[df["report_date_as_yyyy_mm_dd"] >= latest - pd.Timedelta(days=28)]
    recent = recent.sort_values("report_date_as_yyyy_mm_dd").drop_duplicates("market_and_exchange_names", keep="last")
    tracked_codes = set(INSTRUMENT_CODES.values())
    rows = []
    for _, r in recent.iterrows():
        name = str(r["market_and_exchange_names"]).strip()
        size = parse_contract_size(r.get("contract_units")) or 2500
        oi = pd.to_numeric(r.get("open_interest_all"), errors="coerce")
        oi = 0.0 if pd.isna(oi) else float(oi)
        mm_l = pd.to_numeric(r.get("m_money_positions_long_all"), errors="coerce")
        mm_s = pd.to_numeric(r.get("m_money_positions_short_all"), errors="coerce")
        rows.append({
            "market": name,
            "code": str(r.get("cftc_contract_market_code", "")).strip(),
            "units": str(r.get("contract_units", "")).strip(),
            "open_interest": oi,
            "oi_bcf": oi * size / 1e6,
            "mm_gross": float((0 if pd.isna(mm_l) else mm_l) + (0 if pd.isna(mm_s) else mm_s)),
            "tracked": str(r.get("cftc_contract_market_code", "")).strip() in tracked_codes,
        })
    rows.sort(key=lambda x: -x["oi_bcf"])
    print(f"\n[Coverage] {len(rows)} natural gas markets reporting in the last 4 weeks (ranked by OI, Bcf):")
    for x in rows[:top]:
        print(f"  {'TRACKED  ' if x['tracked'] else 'untracked'} {x['oi_bcf']:>10,.0f} Bcf  OI {x['open_interest']:>11,.0f}  "
              f"MM gross {x['mm_gross']:>10,.0f}  [{x['code']}] {x['market']}  {x['units']}")
    return rows[:top]


# ─── Main Pipeline Execution ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CFTC Natural Gas Positioning Data Pipeline — Enhanced")
    parser.add_argument("--force", action="store_true", help="Force update even if no new data detected")
    args = parser.parse_args()

    print("=" * 60)
    print("CFTC Natural Gas Positioning Data Pipeline — Enhanced")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    if args.force:
        print("Flag: --force enabled (staleness check bypassed)")
    print("=" * 60)

    warnings_list = []

    # Ingestion
    cftc_comb_df = fetch_cftc_combined()
    cftc_fut_df  = fetch_cftc_futures_only()

    # Staleness & endpoint sync check
    incoming_latest = cftc_comb_df["report_date_as_yyyy_mm_dd"].max().strftime("%Y-%m-%d")
    fut_latest = cftc_fut_df["report_date_as_yyyy_mm_dd"].max().strftime("%Y-%m-%d")
    existing_latest = None
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, "r") as f:
                existing = json.load(f)
            existing_latest = existing.get("meta", {}).get("latest_report_date")
        except Exception:
            pass
    print(f"  Existing latest date : {existing_latest or 'none'}")
    print(f"  Incoming Comb date   : {incoming_latest}")
    print(f"  Incoming Fut  date   : {fut_latest}")

    if not args.force and existing_latest and incoming_latest <= existing_latest:
        print("\n[Skip] CFTC has not published new data yet. No update needed. (Use --force to override)")
        _set_gha_output("new_data", "false")
        return

    if not args.force and fut_latest < incoming_latest:
        print(f"\n[Skip] Futures Only endpoint ({fut_latest}) is behind Combined ({incoming_latest}); deferring until synced so option deltas stay accurate.")
        _set_gha_output("new_data", "false")
        return

    coverage = coverage_report(cftc_comb_df)
    print("  Processing full data pipeline...\n")
    _set_gha_output("new_data", "true")

    price_s = fetch_prices()

    # Build price alignment map
    price_df_sorted = price_s.reset_index().rename(columns={"date": "price_date"}).sort_values("price_date")
    price_df_sorted["price_date"] = pd.to_datetime(price_df_sorted["price_date"]).astype("datetime64[ns]")
    cftc_dates_sorted = pd.DataFrame({
        "report_date_as_yyyy_mm_dd": cftc_comb_df["report_date_as_yyyy_mm_dd"].drop_duplicates().sort_values().values
    })
    cftc_dates_sorted["report_date_as_yyyy_mm_dd"] = pd.to_datetime(cftc_dates_sorted["report_date_as_yyyy_mm_dd"]).astype("datetime64[ns]")
    price_aligned = pd.merge_asof(
        cftc_dates_sorted, price_df_sorted,
        left_on="report_date_as_yyyy_mm_dd", right_on="price_date",
        direction="backward",
    ).set_index("report_date_as_yyyy_mm_dd")

    # Process Individual Instruments
    instruments_out = {}
    for inst_key, market_name in INSTRUMENTS.items():
        print(f"[Instrument] {inst_key} ({market_name})...")
        mask = market_mask(cftc_comb_df, inst_key)
        inst_df = cftc_comb_df[mask].copy()
        if len(inst_df) == 0:
            w = f"No rows for {inst_key} ({market_name})"
            print(f"  WARNING: {w}")
            warnings_list.append(w)
            continue
        print(f"  Rows: {len(inst_df):,}")
        inst_result = process_instrument(inst_key, inst_df, price_aligned, fut_df=cftc_fut_df)
        instruments_out[inst_key] = inst_result

    assert "nat_gas_nyme" in instruments_out, "Critical: nat_gas_nyme missing!"
    assert len(instruments_out["nat_gas_nyme"]["dates"]) > 200, "Insufficient history for nat_gas_nyme"

    # Process Synthetic Composites
    # 1. Prompt Core: NYMEX futures + ICE LD1 + ICE PEN + EUR options (NYMEX-equivalent)
    prompt_components = COMPOSITE_COMPONENTS["comp_hh_prompt"]
    instruments_out["comp_hh_prompt"] = synthesize_composite(
        "comp_hh_prompt", prompt_components, instruments_out, include_options_delta=True
    )

    # 2. Clean Outright: every Henry Hub futures/swap contract, no options (NYMEX-equivalent)
    clean_components = COMPOSITE_COMPONENTS["comp_hh_clean"]
    instruments_out["comp_hh_clean"] = synthesize_composite(
        "comp_hh_clean", clean_components, instruments_out, include_options_delta=False
    )

    latest_date = max(max(v["dates"]) for v in instruments_out.values() if v.get("dates"))

    # Build Inter-benchmark Correlation Matrix
    print("\n[Correlation Matrix] Computing inter-benchmark matrix...")
    corr_matrix = build_correlation_matrix(instruments_out)
    print(f"  Matrix dimensions: {len(corr_matrix['instruments'])}x{len(corr_matrix['instruments'])}")
    print(f"  Included instruments: {corr_matrix['instruments']}")

    # Strip internal helper arrays before output
    for v in instruments_out.values():
        v.pop("_raw", None)

    output = {
        "meta": {
            "last_updated":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latest_report_date": latest_date,
            "warnings":           warnings_list,
            "price_source":       "yieldchaser/nat-gas-data-pipeline",
            "coverage":           coverage,
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
    print(f"  Total Instruments & Composites: {len(instruments_out)}")
    print(f"  Instruments list: {list(instruments_out.keys())}")
    print(f"  Latest date: {latest_date}")
    print(f"  Warnings: {warnings_list or 'none'}")

    # Validate output
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    if "NaN" in content or "Infinity" in content:
        print("ERROR: NaN/Infinity found in JSON output!")
        sys.exit(1)
    print("  NaN/Infinity check: PASSED")
    print("\n=== PIPELINE COMPLETE ===")


if __name__ == "__main__":
    main()
