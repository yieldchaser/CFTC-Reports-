#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Henry Hub CTA trend model -> data/cta_model.json

Produces three things the dashboard's "CTA & Flows" tab renders:

  1. Momentum thresholds: how far the roll-adjusted front-month price sits
     above/below its short / medium / long trend reference (moving average),
     in %, plus the price level at which each horizon's signal flips.
  2. Simulated realized CTA positioning ($bn): a transparent, volatility-
     targeted trend-follower, scaled to dollars by fitting it to CFTC Managed
     Money net length in the Henry Hub futures complex (NYMEX-equivalent $).
  3. 1-month conditional projections: the same model run forward 21 trading
     days under five price paths (+/-2 sigma, +/-1 sigma, flat).

Inputs: Yahoo Finance NG=F daily closes (10y) and data/cftc_processed.json.
Runs daily (prices move daily) and after each weekly CFTC update.

Model choices, stated plainly so they can be challenged:
  * Rolls: NG=F is an unadjusted continuous series. NG roll gaps are large and
    seasonal (e.g. Oct->Nov contango), which would fake trend signals. The
    return on each roll day (first session after NYMEX last trade, i.e. the
    2nd-to-last trading day of the month) is set to zero. This removes the gap
    at the cost of one genuine daily return per month.
  * Trend per horizon N: z = ln(P / SMA_N) / (sigma_d * sqrt(N/3)), where
    sqrt(N/3) is the random-walk std of a price's distance from its own N-day
    mean, so z ~ N(0,1) with no trend. Signal = clip(z, -1, 1).
  * Exposure = mean(signals) * (vol_target / realized_vol_60d).
  * Dollar scale K: OLS slope of weekly CFTC MM net $ on model exposure over
    the last 156 weeks (the intercept soaks up NG's structural MM short, which
    is not trend-driven). Only if the slope is <= 0 is a dispersion match (std
    ratio) used instead. Fit quality (corr) is published and shown in the UI.
  * Projections hold volatility at its as-of estimate (a smooth scenario path
    would otherwise shrink realized vol and inflate leverage).
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday,
                                    USLaborDay, USMartinLutherKingJr, USMemorialDay,
                                    USPresidentsDay, USThanksgivingDay, nearest_workday)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_cftc_data import (COMPOSITE_COMPONENTS, CONTRACT_SIZE_FALLBACK,  # noqa: E402
                              _set_gha_output, sanitise)

OUTPUT_PATH = "data/cta_model.json"
CFTC_PATH = "data/cftc_processed.json"
MODEL_ID = "hh_cta_trend_v1"

HORIZONS = {"short": 20, "medium": 60, "long": 250}
VOL_WINDOW = 60
VOL_TARGET = 0.15            # annualised; only shapes exposure, K sets the $ scale
PROJ_DAYS = 21
SCENARIOS = [                 # (key, label, move in 1-month sigmas)
    ("up_big", "Up Big", 2.0),
    ("up_small", "Up Small", 1.0),
    ("flat", "Flat Market", 0.0),
    ("down_small", "Down Small", -1.0),
    ("down_big", "Down Big", -2.0),
]
CALIB_WEEKS = 156
CALIB_TARGET_KEY = "comp_hh_prompt"   # NYMEX + ICE LD1 + ICE PEN + EUR options
OUT_PRICE_DAYS = 1260                 # ~5y of daily prices for chart overlays
OUT_MODEL_DAYS = 756                  # ~3y of thresholds / simulated positions


class NymexHolidays(AbstractHolidayCalendar):
    """Approximate CME energy holiday calendar (only used to date future sessions)."""
    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


# ─── Prices ───────────────────────────────────────────────────────────────────

def fetch_daily_prices(rng: str = "10y") -> pd.Series:
    symbol = urllib.parse.quote("NG=F")
    urls = [f"https://query{h}.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={rng}"
            for h in (2, 1)]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    payload = None
    for attempt in range(1, 5):
        url = urls[(attempt - 1) % len(urls)]
        try:
            print(f"  [Prices] Attempt {attempt}/4: {url[:90]}")
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25) as r:
                payload = json.load(r)
            break
        except Exception as exc:  # network / HTTP errors
            print(f"  [Prices] Error: {exc}")
            if attempt < 4:
                time.sleep(2 ** attempt)
    if not payload:
        raise RuntimeError("Yahoo Finance NG=F fetch failed")
    res = (payload.get("chart") or {}).get("result")
    if not res:
        raise RuntimeError("Yahoo Finance returned no NG=F result")
    res = res[0]
    offset = int((res.get("meta") or {}).get("gmtoffset") or 0)
    ts = res.get("timestamp") or []
    closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    rows = [(datetime.fromtimestamp(t + offset, tz=timezone.utc).date(), float(c))
            for t, c in zip(ts, closes) if t is not None and c is not None and c > 0]
    s = pd.Series({pd.Timestamp(d): c for d, c in rows}).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if len(s) < 400:
        raise RuntimeError(f"Too little NG=F history ({len(s)} rows)")
    if (s.index >= s.index.max() - pd.Timedelta(days=30)).sum() < 12:
        raise RuntimeError("NG=F feed is not daily; refusing to build the model on coarse bars")
    print(f"  [Prices] {len(s)} sessions {s.index[0].date()} -> {s.index[-1].date()}, last {s.iloc[-1]:.3f}")
    return s


def roll_days(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """First session of each new NG front month = 2nd-to-last trading day of each
    calendar month (NYMEX NG last trade is 3 business days before the delivery
    month). Uses the series' own sessions, so holidays are handled implicitly.
    The current, still-incomplete month is excluded (its roll is in the future)."""
    out = []
    months = index.to_period("M")
    last_month = months[-1]
    for m in months.unique():
        if m == last_month:
            continue
        sess = index[months == m]
        if len(sess) >= 3:
            out.append(sess[-2])
    return pd.DatetimeIndex(out)


def roll_adjusted_log_price(front: pd.Series) -> tuple[pd.Series, int]:
    r = np.log(front).diff()
    rd = roll_days(front.index)
    r.loc[r.index.isin(rd)] = 0.0
    r.iloc[0] = 0.0
    # Anchor so the latest adjusted price equals the current front-month price:
    # thresholds then read directly in today's contract terms.
    logp = r.cumsum()
    logp = logp - logp.iloc[-1] + math.log(front.iloc[-1])
    return logp, int(len(rd))


# ─── Model ────────────────────────────────────────────────────────────────────

def model_state(logp: np.ndarray, sigma_d: np.ndarray):
    """Vectorised model over a log-price path. Returns dict of arrays."""
    p = np.exp(logp)
    s = pd.Series(p)
    out = {"pct": {}, "sma": {}, "signal": {}}
    sigs = []
    for name, n in HORIZONS.items():
        sma = s.rolling(n, min_periods=n).mean().to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            dist = np.log(p / sma)
            z = dist / (sigma_d * np.sqrt(n / 3.0))
        sig = np.clip(z, -1.0, 1.0)
        out["pct"][name] = (p / sma - 1.0) * 100.0
        out["sma"][name] = sma
        out["signal"][name] = sig
        sigs.append(sig)
    avg = np.mean(np.vstack(sigs), axis=0)  # NaN until the long horizon is warm
    with np.errstate(divide="ignore", invalid="ignore"):
        lev = VOL_TARGET / (sigma_d * math.sqrt(252))
    out["exposure"] = avg * lev
    return out


def mm_usd_series(cftc: dict, key: str) -> pd.Series:
    """CFTC Managed Money net length in $bn, NYMEX-equivalent, for an instrument
    or composite (composites are sized component-by-component)."""
    insts = cftc["instruments"]
    comps = insts.get(key, {}).get("components") or COMPOSITE_COMPONENTS.get(key) or [key]
    total = None
    for k in comps:
        inst = insts.get(k)
        if not inst:
            continue
        size = inst.get("contract_size_mmbtu") or CONTRACT_SIZE_FALLBACK.get(k)
        dates = pd.to_datetime(inst["dates"])
        net = pd.Series(inst["managed_money"]["net"], index=dates, dtype="float64")
        px = pd.Series(inst["price"], index=dates, dtype="float64")
        usd = net * size * px / 1e9
        total = usd if total is None else total.add(usd, fill_value=np.nan)
    if total is None:
        return pd.Series(dtype="float64")
    return total.dropna()


def calibrate(exposure: pd.Series, target: pd.Series) -> dict:
    # Align weekly CFTC Tuesdays with the model value on (or just before) that date
    exp_on = exposure.dropna().reindex(target.index, method="ffill")
    df = pd.DataFrame({"x": exp_on, "y": target}).dropna().iloc[-CALIB_WEEKS:]
    n = len(df)
    info = {"target": f"CFTC Managed Money net, {CALIB_TARGET_KEY} (NYMEX-equivalent $bn)",
            "n_obs": n, "window_weeks": CALIB_WEEKS}
    if n < 20:
        raise RuntimeError(f"Not enough overlap to calibrate CTA scale (n={n})")
    x, y = df["x"].to_numpy(), df["y"].to_numpy()
    # Slope (with intercept), not regression through the origin: NG Managed Money
    # carries a large structural short (roll-yield / producer-hedge-mirroring books)
    # that trend signals cannot explain. The intercept absorbs that book; the slope
    # is the $ that co-moves with the trend signal, i.e. the CTA-like component.
    sx, sy = float(np.std(x)), float(np.std(y))
    corr = float(np.corrcoef(x, y)[0, 1]) if sx > 0 and sy > 0 else 0.0
    slope = corr * sy / sx if sx > 0 else 0.0
    # A weak positive slope is still the unbiased estimate of $ per unit of trend
    # exposure. Matching dispersion would assign ALL Managed Money variance to
    # trend-following and overstate CTA flows several-fold when the fit is weak
    # (it does in NG: much of MM is structural/discretionary). Dispersion
    # matching is used only when the slope is non-positive.
    if slope > 0:
        k, method = slope, "ols_slope"
    else:
        k, method = (sy / sx if sx > 0 else 0.0), "dispersion_match"
    info.update({"method": method, "k_usd_bn_per_unit": k, "corr": corr, "r2": corr ** 2,
                 "intercept_usd_bn": float(y.mean() - k * x.mean()),
                 "start": df.index[0].strftime("%Y-%m-%d"),
                 "end": df.index[-1].strftime("%Y-%m-%d")})
    return info


def future_sessions(after: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    hol = NymexHolidays().holidays(after, after + pd.Timedelta(days=60))
    bdays = pd.bdate_range(after + pd.Timedelta(days=1), periods=n + 15, freq="C", holidays=hol)
    return bdays[:n]


# ─── Main ─────────────────────────────────────────────────────────────────────

def decompose(exposure: pd.Series, target: pd.Series, k: float) -> dict:
    """Split weekly Managed Money net ($bn) into a trend-following part (the CTA
    replica, k x exposure) and everything else (discretionary and structural
    positioning), after Bouchouev, Sun & Fattouh (OIES 2026). Also measures the
    trend-follower share of fund FLOWS: rolling 52-week R^2 of weekly changes in
    MM $ on weekly changes in the trend component. A share near zero means funds
    are trading against, or regardless of, price trends."""
    e = exposure.dropna().reindex(target.index, method="ffill")
    df = pd.DataFrame({"mm": target, "trend": e * k}).dropna()
    df["other"] = df.mm - df.trend
    share = df.mm.diff().rolling(52, min_periods=40).corr(df.trend.diff()) ** 2
    oz = (df.other - df.other.rolling(156, min_periods=104).mean()) / df.other.rolling(156, min_periods=104).std()
    d = lambda ix: [x.strftime("%Y-%m-%d") for x in ix]  # noqa: E731
    last = df.index[-1]
    return {
        "dates": d(df.index), "mm_usd_bn": df.mm.tolist(), "trend_usd_bn": df.trend.tolist(),
        "other_usd_bn": df.other.tolist(), "trend_share": share.reindex(df.index).tolist(),
        "latest": {
            "date": last.strftime("%Y-%m-%d"), "mm": float(df.mm.iloc[-1]), "trend": float(df.trend.iloc[-1]),
            "other": float(df.other.iloc[-1]),
            "other_z": float(oz.iloc[-1]) if pd.notna(oz.iloc[-1]) else None,
            "trend_share": float(share.iloc[-1]) if pd.notna(share.iloc[-1]) else None,
            "trend_share_median_5y": float(share.iloc[-260:].median()),
            "trend_share_pctile": float((share.dropna() < share.iloc[-1]).mean() * 100) if pd.notna(share.iloc[-1]) else None,
        },
    }


def build(front: pd.Series, cftc: dict) -> dict:
    logp, n_rolls = roll_adjusted_log_price(front)
    r = logp.diff()
    sigma_d = r.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std().to_numpy()
    st = model_state(logp.to_numpy(), sigma_d)
    idx = front.index
    exposure = pd.Series(st["exposure"], index=idx)

    target = mm_usd_series(cftc, CALIB_TARGET_KEY)
    calib = calibrate(exposure, target)
    k = calib["k_usd_bn_per_unit"]
    position = exposure * k

    # Latest-state summary
    last_i = len(idx) - 1
    sig_now = sigma_d[last_i]
    if not np.isfinite(sig_now) or not np.isfinite(st["exposure"][last_i]):
        raise RuntimeError("Model not warm at latest date")
    levels = {}
    for name, n in HORIZONS.items():
        levels[name] = {
            "window_days": n,
            "pct_from_threshold": st["pct"][name][last_i],
            "threshold_price": st["sma"][name][last_i],
            "signal": st["signal"][name][last_i],
            "direction": "long" if st["pct"][name][last_i] > 0 else "short",
        }

    # Projections
    fut = future_sessions(idx[-1], PROJ_DAYS)
    sig_1m = sig_now * math.sqrt(PROJ_DAYS)
    lp = logp.to_numpy()
    sig_hist = sigma_d.copy()
    projections = {}
    for key, label, mult in SCENARIOS:
        move = mult * sig_1m
        path = lp[-1] + move * np.arange(1, PROJ_DAYS + 1) / PROJ_DAYS
        full_lp = np.concatenate([lp, path])
        full_sig = np.concatenate([sig_hist, np.full(PROJ_DAYS, sig_now)])
        fs = model_state(full_lp, full_sig)
        pos = fs["exposure"][-PROJ_DAYS:] * k
        projections[key] = {
            "label": label,
            "sigma_mult": mult,
            "move_pct": (math.exp(move) - 1) * 100,
            "end_price": float(front.iloc[-1] * math.exp(move)),
            "position_usd_bn": pos.tolist(),
            "price": (front.iloc[-1] * np.exp(path - lp[-1])).tolist(),
            "end_position_usd_bn": float(pos[-1]),
            "flow_usd_bn": float(pos[-1] - position.iloc[-1]),
            "end_signals": {h: float(fs["signal"][h][-1]) for h in HORIZONS},
        }

    tail_p = slice(max(0, len(idx) - OUT_PRICE_DAYS), None)
    tail_m = slice(max(0, len(idx) - OUT_MODEL_DAYS), None)
    d = lambda ix: [x.strftime("%Y-%m-%d") for x in ix]  # noqa: E731

    out = {
        "meta": {
            "model": MODEL_ID,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of": idx[-1].strftime("%Y-%m-%d"),
            "price_source": "Yahoo Finance NG=F (front-month continuous), roll-day returns neutralised",
            "cftc_latest_report_date": cftc.get("meta", {}).get("latest_report_date"),
            "roll_days_neutralised": n_rolls,
            "params": {"horizons": HORIZONS, "vol_window": VOL_WINDOW, "vol_target": VOL_TARGET,
                       "projection_days": PROJ_DAYS,
                       "scenario_sigmas": {k_: m for k_, _, m in SCENARIOS}},
            "calibration": calib,
        },
        "latest": {
            "date": idx[-1].strftime("%Y-%m-%d"),
            "price": float(front.iloc[-1]),
            "price_chg_1d_pct": float((front.iloc[-1] / front.iloc[-2] - 1) * 100),
            "realized_vol_ann_pct": float(sig_now * math.sqrt(252) * 100),
            "one_month_sigma_pct": float((math.exp(sig_1m) - 1) * 100),
            "exposure": float(exposure.iloc[-1]),
            "position_usd_bn": float(position.iloc[-1]),
            "position_chg_1w_usd_bn": float(position.iloc[-1] - position.iloc[-6]),
            "levels": levels,
        },
        "price": {"dates": d(idx[tail_p]), "front": front.iloc[tail_p].tolist()},
        "thresholds": {"dates": d(idx[tail_m]),
                       **{h: st["pct"][h][tail_m].tolist() for h in HORIZONS},
                       "trigger": {h: st["sma"][h][tail_m].tolist() for h in HORIZONS}},
        "position": {"dates": d(idx[tail_m]), "usd_bn": position.iloc[tail_m].tolist()},
        "cftc_mm_usd_bn": {"dates": d(target.index), "values": target.tolist()},
        "decomposition": decompose(exposure, target, k),
        "projections": {"dates": d(fut), "scenarios": projections},
    }
    return out


def main():
    ap = argparse.ArgumentParser(description="Henry Hub CTA trend model")
    ap.add_argument("--prices-csv", help="Offline: CSV with date,close instead of Yahoo")
    args = ap.parse_args()

    print("=" * 60)
    print(f"CTA trend model  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    with open(CFTC_PATH, "r", encoding="utf-8") as f:
        cftc = json.load(f)

    if args.prices_csv:
        df = pd.read_csv(args.prices_csv, parse_dates=["date"])
        front = df.set_index("date")["close"].astype(float).sort_index()
    else:
        front = fetch_daily_prices()

    out = build(front, cftc)
    out = sanitise(out)

    prev = None
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = None
    def _strip(o):
        o = json.loads(json.dumps(o))
        o.get("meta", {}).pop("generated_at", None)
        return o
    changed = prev is None or _strip(prev) != _strip(out)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), allow_nan=False)

    L, c = out["latest"], out["meta"]["calibration"]
    print(f"  As of {L['date']}: NG {L['price']:.3f}  CTA position {L['position_usd_bn']:+.2f} $bn")
    for h, v in L["levels"].items():
        print(f"    {h:<6} {v['pct_from_threshold']:+6.1f}%  trigger {v['threshold_price']:.3f}  signal {v['signal']:+.2f}")
    print(f"  Calibration: {c['method']} K={c['k_usd_bn_per_unit']:.2f} corr={c['corr']:.2f} n={c['n_obs']}")
    for k_, p in out["projections"]["scenarios"].items():
        print(f"    {p['label']:<12} {p['move_pct']:+6.1f}%  -> {p['end_position_usd_bn']:+.2f} $bn (flow {p['flow_usd_bn']:+.2f})")
    print(f"  Wrote {OUTPUT_PATH} ({os.path.getsize(OUTPUT_PATH)/1024:.0f} KB), changed={changed}")
    _set_gha_output("cta_changed", "true" if changed else "false")


if __name__ == "__main__":
    main()
