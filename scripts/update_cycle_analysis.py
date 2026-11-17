#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Henry Hub swing-cycle & turning-point analysis -> data/cycle_analysis.json

Answers three questions with event-based statistics (no fixed-horizon returns):

  1. What does the NG swing cycle look like?  Confirmed swing pivots (zigzag,
     20% reversal) on the roll-adjusted front month: how many cycles per year,
     how far and how long swings run, which months troughs and peaks occur in,
     and where the swing in progress sits against that history.
  2. Does positioning mark the turns?  Event study of Managed Money positioning
     (3-year COT index, 4-week flow) from 12 weeks before to 12 weeks after
     every trough and peak, against all weeks; plus a scorecard of positioning
     signals measured as turning-point detectors (hit rate vs base rate).
  3. Which way do moves resolve?  First-passage odds: from a given week, does
     price rise X% before it falls X%?  Unconditional, by month, and under
     conditions matching today.

Prices: Yahoo NG=F daily since 2000. Roll-day returns are zeroed (same method
as the CTA model) so contract-roll gaps (up to ~30% in winter) neither create
nor hide swings. Pivot prices are reported in actual front-month terms too.
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_cftc_data import _set_gha_output, fetch_prices, sanitise  # noqa: E402
from update_cta_model import roll_adjusted_log_price  # noqa: E402

OUTPUT_PATH = "data/cycle_analysis.json"
CFTC_PATH = "data/cftc_processed.json"
MODEL_ID = "hh_cycle_v1"

SWING_TH = 0.20            # 20% reversal confirms a pivot (~1.7 cycles/yr in NG)
EVENT_WINDOW = 12          # weeks either side of a pivot in the event study
HIT_WINDOW = 4             # a signal "hits" if a matching pivot is within +/-4 weeks
PASSAGE_LEVELS = (0.15, 0.20)
COT_WARMUP_WEEKS = 156
OOS_SPLIT = "2018-01-01"   # signals were selected on data before this date; later data is out-of-sample
TRADER_GROUPS = {"mm": "managed_money", "prod": "producers", "swap": "swap_dealers",
                 "other": "other_reportables", "nonrept": "non_reportables", "spec": "total_speculative"}
POSITIONING_SOURCES = {
    "nat_gas_nyme": "NYMEX Henry Hub futures (longest history)",
    "comp_hh_prompt": "HH Prompt Core composite (NYMEX-equivalent, includes ICE)",
}


# ─── Swing pivots ─────────────────────────────────────────────────────────────

def zigzag(s: pd.Series, th: float):
    """Confirmed swing pivots. A peak is confirmed once price falls >= th below
    the running high since the last trough, and vice versa. Pivots strictly
    alternate. Returns (pivots, state) where pivots are dicts with the pivot
    date/price and the date it became confirmed, and state describes the swing
    in progress (direction, running extreme)."""
    v, ix = s.values.astype(float), s.index
    piv = []
    hi_i = lo_i = 0
    state = 0
    for i in range(1, len(v)):
        if state >= 0 and v[i] > v[hi_i]:
            hi_i = i
        if state <= 0 and v[i] < v[lo_i]:
            lo_i = i
        if state >= 0 and v[i] <= v[hi_i] * (1 - th):
            if state == 0 and lo_i < hi_i and v[hi_i] >= v[lo_i] * (1 + th):
                piv.append({"i": lo_i, "type": "T", "ci": hi_i})
            piv.append({"i": hi_i, "type": "P", "ci": i})
            state, lo_i = -1, i
            continue
        if state <= 0 and v[i] >= v[lo_i] * (1 + th):
            if state == 0 and hi_i < lo_i and v[hi_i] >= v[lo_i] * (1 + th):
                piv.append({"i": hi_i, "type": "P", "ci": lo_i})
            piv.append({"i": lo_i, "type": "T", "ci": i})
            state, hi_i = 1, i
            continue
    ext_i = hi_i if state == 1 else lo_i
    return piv, {"direction": "up" if state == 1 else "down" if state == -1 else "undetermined", "ext_i": ext_i}


def pct_rank(values, x):
    a = np.asarray(values, dtype=float)
    return float((a < x).mean() * 100) if len(a) else None


def wilson(k, n, z=1.96):
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


# ─── Positioning metrics ──────────────────────────────────────────────────────

def positioning_frame(cftc: dict, key: str) -> pd.DataFrame:
    """Weekly positioning features for every trader group: 3-year COT index,
    weekly flow, 2-week flow and 4-week flow z-score. Managed Money columns keep
    their short names (cot, z, flow, flow2, flow4z) for backward compatibility."""
    inst = cftc["instruments"][key]
    idx = pd.to_datetime(inst["dates"])
    cols = {}
    for g, tk in TRADER_GROUPS.items():
        t = inst.get(tk)
        if not t:
            continue
        flow = pd.Series(t["change_net"], index=idx, dtype="float64")
        f4 = flow.rolling(4).sum()
        cols[f"{g}_cot"] = pd.Series(t["cot_index"]["w156"], index=idx, dtype="float64")
        cols[f"{g}_flow"] = flow
        cols[f"{g}_flow2"] = flow.rolling(2).sum()
        cols[f"{g}_flow4z"] = (f4 - f4.rolling(156, min_periods=52).mean()) / f4.rolling(156, min_periods=52).std()
    df = pd.DataFrame(cols)
    df["z"] = pd.Series(inst["managed_money"]["z_score"], index=idx, dtype="float64")
    df["cot"], df["flow"], df["flow2"], df["flow4z"] = df.mm_cot, df.mm_flow, df.mm_flow2, df.mm_flow4z
    return df[df.index >= idx[0] + pd.Timedelta(weeks=COT_WARMUP_WEEKS)]


SIGNALS = [
    # key, label, pivot it should mark, rule(df) -> bool series, plain-English rule
    ("crowded_long", "Crowded long", "P", lambda d: d.cot >= 90, "MM 3y COT index >= 90"),
    ("crowded_short", "Crowded short", "T", lambda d: d.cot <= 10, "MM 3y COT index <= 10"),
    ("z_high", "Extreme long (Z >= +2)", "P", lambda d: d.z >= 2, "MM net Z-score >= +2"),
    ("z_low", "Extreme short (Z <= -2)", "T", lambda d: d.z <= -2, "MM net Z-score <= -2"),
    ("liquidation", "Liquidation after crowded long", "P",
     lambda d: (d.cot.rolling(6).max() >= 80) & (d.flow2 < 0), "COT >= 80 within 6w and MM selling over 2w"),
    ("covering", "Covering after crowded short", "T",
     lambda d: (d.cot.rolling(6).min() <= 20) & (d.flow2 > 0), "COT <= 20 within 6w and MM buying over 2w"),
    ("blowoff", "Flow blow-off, then selling", "P",
     lambda d: (d.flow4z.rolling(4).max() > 1.5) & (d.flow < 0), "4w MM flow > +1.5 sd within 4w, then a selling week"),
    ("capitulation", "Flow capitulation, then buying", "T",
     lambda d: (d.flow4z.rolling(4).min() < -1.5) & (d.flow > 0), "4w MM flow < -1.5 sd within 4w, then a buying week"),
    # Cross-group combinations. Found by testing 1,104 single and paired
    # conditions across all six trader groups (2,208 tests) on NYMEX data:
    # chosen on 2009-2017 (>=5 episodes, lift >= 1.5, p < 0.05) and kept only if
    # they held on unseen 2018-2026 data (lift >= 1.3, p < 0.05). From the
    # survivors, one representative per distinct mechanism is used here.
    ("spec_crowded_selling", "Speculators crowded long, starting to sell", "P",
     lambda d: (d.spec_cot >= 80) & (d.spec_flow2 < 0), "MM + Other COT >= 80 and selling over 2w"),
    ("prod_short_spec_buying", "Producers heavily short while speculators buy", "P",
     lambda d: (d.prod_cot <= 20) & (d.spec_flow2 > 0), "Producer COT <= 20 and MM + Other buying over 2w"),
    ("mm_surge_other_selling", "Managed Money surge, Other Reportables selling", "P",
     lambda d: (d.mm_flow4z > 1) & (d.other_flow2 < 0), "4w MM flow > +1 sd while Other Reportables sell over 2w"),
    ("nonrept_crowded_short", "Small traders crowded short", "T",
     lambda d: d.nonrept_cot <= 20, "Non-reportable COT <= 20"),
]
COMBINATION_SIGNALS = {"spec_crowded_selling", "prod_short_spec_buying", "mm_surge_other_selling", "nonrept_crowded_short"}


def near_pivot(weeks: pd.DatetimeIndex, pivot_dates, window: int) -> pd.Series:
    out = pd.Series(False, index=weeks)
    w = pd.Timedelta(weeks=window)
    for t in pivot_dates:
        out[(weeks >= t - w) & (weeks <= t + w)] = True
    return out


def episodes(mask: pd.Series, gap: int = 2):
    """Group firing weeks into episodes (runs separated by > gap weeks)."""
    eps, cur, last = [], [], None
    for t in mask.index[mask.values]:
        if last is not None and (t - last).days / 7 > gap:
            eps.append(cur)
            cur = []
        cur.append(t)
        last = t
    if cur:
        eps.append(cur)
    return eps


def resolved_mask(W: pd.DatetimeIndex, hit_mask: pd.Series, last_confirmed: pd.Timestamp) -> pd.Series:
    """A week's outcome is final once every turn that could fall in its
    +/-HIT_WINDOW window is known. Zigzag pivots are confirmed in order, so any
    turn not yet confirmed must be dated after the last confirmed pivot: a week
    is resolved if it already has a confirmed matching turn nearby (a hit can't
    be undone) or its whole window ends on/before the last confirmed pivot.
    Everything else is PENDING and is left out of the statistics, otherwise a
    signal that fired in the last few weeks would always count as a miss."""
    return hit_mask | (W + pd.Timedelta(weeks=HIT_WINDOW) <= last_confirmed)


def _period_stats(fire, hit_mask, period_mask, resolved):
    m = period_mask & resolved
    f, h = fire[m], hit_mask[m]
    n = int(f.sum())
    eps = episodes(f)
    base = float(h.mean()) if len(h) else 0.0
    hits = int((f & h).sum())
    ep_hits = sum(1 for e in eps if h.loc[e].any())
    return {"weeks": n, "episodes": len(eps), "episodes_hit": ep_hits,
            "lift": (hits / n) / base if n and base > 0 else None}


def scorecard(pos: pd.DataFrame, pivots_T, pivots_P, last_confirmed: pd.Timestamp) -> list:
    W = pos.index
    pT = [t for t in pivots_T if W[0] <= t <= W[-1]]
    pP = [t for t in pivots_P if W[0] <= t <= W[-1]]
    nearT, nearP = near_pivot(W, pT, HIT_WINDOW), near_pivot(W, pP, HIT_WINDOW)
    out = []
    for key, label, typ, rule, desc in SIGNALS:
        fire_all = rule(pos).reindex(W).fillna(False).astype(bool)
        hit_mask, opp_mask = (nearT, nearP) if typ == "T" else (nearP, nearT)
        res = resolved_mask(W, hit_mask, last_confirmed)
        fire = fire_all & res                          # scored firings only
        pts = pT if typ == "T" else pP
        n = int(fire.sum())
        hits = int((fire & hit_mask).sum())
        base = float(hit_mask[res].mean()) if res.any() else 0.0
        eps = episodes(fire)
        ep_hits = sum(1 for e in eps if hit_mask.loc[e].any())
        lo, hi = wilson(ep_hits, len(eps))
        caught = sum(1 for t in pts if fire_all[(W >= t - pd.Timedelta(weeks=HIT_WINDOW)) & (W <= t + pd.Timedelta(weeks=HIT_WINDOW))].any())
        pending_weeks = int((fire_all & ~res).sum())
        out.append({
            "key": key, "label": label, "marks": "trough" if typ == "T" else "peak", "rule": desc,
            "weeks_fired": n, "episodes": len(eps), "episodes_hit": ep_hits,
            "pending_weeks": pending_weeks,
            "hit_rate": hits / n if n else None, "base_rate": base,
            "lift": (hits / n) / base if n and base > 0 else None,
            "episode_hit_rate": ep_hits / len(eps) if eps else None, "episode_ci": [lo, hi],
            "opposite_rate": float((fire & opp_mask).sum() / n) if n else None,
            "pivots_caught": caught, "pivots_total": len(pts),
            "active_now": bool(fire_all.iloc[-1]),
            "combination": key in COMBINATION_SIGNALS,
            "in_sample": _period_stats(fire_all, hit_mask, W < pd.Timestamp(OOS_SPLIT), res),
            "out_of_sample": _period_stats(fire_all, hit_mask, W >= pd.Timestamp(OOS_SPLIT), res),
            "last_fired": fire_all[fire_all].index[-1].strftime("%Y-%m-%d") if fire_all.any() else None,
        })
    return out


def signal_log(pos: pd.DataFrame, pivots_T, pivots_P, last_confirmed: pd.Timestamp) -> dict:
    """Automatically maintained record, rebuilt on every run so it grows as new
    reports arrive: every firing episode of every signal with its outcome
    (hit / miss / pending), and every confirmed turn with the signals that
    flagged it, including whether they were PUBLISHED before the turn
    (CFTC releases Tuesday positions on Friday)."""
    W = pos.index
    pub = lambda t: t + pd.Timedelta(days=3)  # noqa: E731
    pT = [t for t in pivots_T if t >= W[0]]
    pP = [t for t in pivots_P if t >= W[0]]
    nearT, nearP = near_pivot(W, pT, HIT_WINDOW), near_pivot(W, pP, HIT_WINDOW)
    win = pd.Timedelta(weeks=HIT_WINDOW)
    eps_out, fires = [], {}
    for key, label, typ, rule, _desc in SIGNALS:
        fire = rule(pos).reindex(W).fillna(False).astype(bool)
        fires[key] = (fire, typ, label)
        hit_mask = nearT if typ == "T" else nearP
        res = resolved_mask(W, hit_mask, last_confirmed)
        pts = pT if typ == "T" else pP
        for e in episodes(fire):
            start, end = e[0], e[-1]
            match = [t for t in pts if start - win <= t <= end + win]
            outcome = "hit" if match else ("miss" if res.loc[e].all() else "pending")
            eps_out.append({
                "signal": key, "label": label, "marks": "trough" if typ == "T" else "peak",
                "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"),
                "published": pub(start).strftime("%Y-%m-%d"), "weeks": len(e),
                "active": bool(end == W[-1]), "outcome": outcome,
                "turn": match[0].strftime("%Y-%m-%d") if match else None,
                "lead_weeks": round((match[0] - pub(start)).days / 7, 1) if match else None,
            })
    turns = []
    for typ, pts in (("T", pT), ("P", pP)):
        for t in pts:
            flags = []
            for key, (fire, ftyp, label) in fires.items():
                if ftyp != typ:
                    continue
                wk = fire[(W >= t - win) & (W <= t + win) & fire]
                if len(wk):
                    first = wk.index[0]
                    flags.append({"signal": key, "label": label, "first": first.strftime("%Y-%m-%d"),
                                  "in_advance": bool(pub(first) <= t)})
            turns.append({"date": t.strftime("%Y-%m-%d"), "type": "trough" if typ == "T" else "peak",
                          "flags": flags, "flagged_in_advance": any(f["in_advance"] for f in flags)})
    eps_out.sort(key=lambda x: x["start"], reverse=True)
    turns.sort(key=lambda x: x["date"], reverse=True)
    return {"episodes": eps_out, "turns": turns,
            "resolved_through": (last_confirmed - win).strftime("%Y-%m-%d")}


def event_study(pos: pd.DataFrame, adj_w: pd.Series, pivots_T, pivots_P) -> dict:
    offsets = list(range(-EVENT_WINDOW, EVENT_WINDOW + 1))
    W = pos.index

    def band(series: pd.Series, dates):
        rows = []
        for t in dates:
            j = series.index.searchsorted(t)
            if j >= len(series) or series.index[j] != t:
                continue
            if j - EVENT_WINDOW < 0 or j + EVENT_WINDOW >= len(series):
                continue
            rows.append(series.iloc[j - EVENT_WINDOW: j + EVENT_WINDOW + 1].values)
        if not rows:
            return None
        a = np.vstack(rows)
        return {"n": len(rows), "median": np.nanmedian(a, 0).tolist(),
                "p25": np.nanpercentile(a, 25, 0).tolist(), "p75": np.nanpercentile(a, 75, 0).tolist()}

    pT = [t for t in pivots_T if t >= W[0]]
    pP = [t for t in pivots_P if t >= W[0]]
    out = {"offsets": offsets, "metrics": {}}
    for m, label in (("cot", "MM 3-year COT index"), ("flow4z", "MM 4-week flow (z-score)")):
        s = pos[m]
        out["metrics"][m] = {
            "label": label,
            "troughs": band(s, pT), "peaks": band(s, pP),
            "all_weeks": {"median": float(s.median()), "p25": float(s.quantile(.25)), "p75": float(s.quantile(.75))},
            "current": float(s.iloc[-1]) if pd.notna(s.iloc[-1]) else None,
        }
    # Average price shape around pivots (% from pivot price), for context
    lp = np.log(adj_w.reindex(W))
    rel = {}
    for typ, dates in (("troughs", pT), ("peaks", pP)):
        rows = []
        for t in dates:
            j = lp.index.searchsorted(t)
            if j - EVENT_WINDOW < 0 or j + EVENT_WINDOW >= len(lp) or lp.index[j] != t:
                continue
            seg = lp.iloc[j - EVENT_WINDOW: j + EVENT_WINDOW + 1].values - lp.iloc[j]
            rows.append((np.exp(seg) - 1) * 100)
        rel[typ] = np.nanmedian(np.vstack(rows), 0).tolist() if rows else None
    out["price_pct_from_pivot"] = rel
    return out


def first_passage(adj_w: pd.Series, level: float) -> pd.DataFrame:
    """For each week: +1 if price rises `level` before falling `level`, -1 if
    the opposite, NaN if neither has happened yet (censored), and weeks taken."""
    v = adj_w.values
    res, wk = np.full(len(v), np.nan), np.full(len(v), np.nan)
    for i in range(len(v)):
        up, dn = v[i] * (1 + level), v[i] * (1 - level)
        for j in range(i + 1, len(v)):
            if v[j] >= up:
                res[i], wk[i] = 1, j - i
                break
            if v[j] <= dn:
                res[i], wk[i] = -1, j - i
                break
    return pd.DataFrame({"outcome": res, "weeks": wk}, index=adj_w.index)


def passage_stats(fp: pd.DataFrame, mask=None) -> dict:
    d = fp if mask is None else fp[mask.reindex(fp.index).fillna(False).astype(bool)]
    d = d.dropna()
    n = len(d)
    if n == 0:
        return {"n": 0}
    k = int((d.outcome > 0).sum())
    med_wk = float(d.weeks.median())
    n_eff = max(1, int(round(n / max(med_wk, 1))))   # overlapping windows -> conservative CI
    lo, hi = wilson(round(k / n * n_eff), n_eff)
    return {"n": n, "n_effective": n_eff, "p_up_first": k / n, "ci": [lo, hi],
            "median_weeks": med_wk}


# ─── Build ────────────────────────────────────────────────────────────────────

def build(daily_front: pd.Series, cftc: dict) -> dict:
    daily_front = daily_front.dropna().sort_index()
    logp, n_rolls = roll_adjusted_log_price(daily_front)
    adj_daily = np.exp(logp)

    # Weekly on COT report dates (Tuesdays), plus the latest daily close
    weeks = pd.to_datetime(cftc["instruments"]["nat_gas_nyme"]["dates"])
    weeks = weeks[weeks >= adj_daily.index[0]]
    adj_w = adj_daily.reindex(adj_daily.index.union(weeks)).ffill().reindex(weeks)
    front_w = daily_front.reindex(daily_front.index.union(weeks)).ffill().reindex(weeks)
    last_day = adj_daily.index[-1]
    adj_ext, front_ext = adj_w.copy(), front_w.copy()
    if last_day > weeks[-1]:
        adj_ext.loc[last_day] = adj_daily.iloc[-1]
        front_ext.loc[last_day] = daily_front.iloc[-1]

    piv, st = zigzag(adj_ext, SWING_TH)
    ix = adj_ext.index
    pivots = []
    for k, p in enumerate(piv):
        prev = piv[k - 1] if k else None
        pivots.append({
            "date": ix[p["i"]].strftime("%Y-%m-%d"), "type": "trough" if p["type"] == "T" else "peak",
            "front_price": float(front_ext.iloc[p["i"]]), "adj_price": float(adj_ext.iloc[p["i"]]),
            "confirmed": ix[p["ci"]].strftime("%Y-%m-%d"),
            "confirm_lag_weeks": (ix[p["ci"]] - ix[p["i"]]).days / 7,
            "swing_pct": (adj_ext.iloc[p["i"]] / adj_ext.iloc[prev["i"]] - 1) * 100 if prev else None,
            "swing_weeks": (ix[p["i"]] - ix[prev["i"]]).days / 7 if prev else None,
        })
    last_confirmed = ix[piv[-1]["i"]] if piv else ix[0]
    piv_T = [ix[p["i"]] for p in piv if p["type"] == "T"]
    piv_P = [ix[p["i"]] for p in piv if p["type"] == "P"]

    ups = [(p["swing_pct"], p["swing_weeks"]) for p in pivots if p["type"] == "peak" and p["swing_pct"] is not None]
    downs = [(p["swing_pct"], p["swing_weeks"]) for p in pivots if p["type"] == "trough" and p["swing_pct"] is not None]
    years = (ix[-1] - ix[0]).days / 365.25

    # Swing in progress
    last = piv[-1]
    last_i = last["i"]
    direction = st["direction"]
    ext_i = st["ext_i"]
    cur_adj, cur_front = float(adj_ext.iloc[-1]), float(front_ext.iloc[-1])
    move_now = (cur_adj / adj_ext.iloc[last_i] - 1) * 100
    move_ext = (adj_ext.iloc[ext_i] / adj_ext.iloc[last_i] - 1) * 100
    weeks_now = (ix[-1] - ix[last_i]).days / 7
    same = ups if direction == "up" else downs
    # adj series is anchored to today's front price, so levels below are in today's terms
    ext_level = float(adj_ext.iloc[ext_i])
    confirm_level = ext_level * (1 - SWING_TH) if direction == "up" else ext_level * (1 + SWING_TH)
    current = {
        "as_of": ix[-1].strftime("%Y-%m-%d"), "price": cur_front,
        "direction": direction,
        "since_pivot": pivots[-1],
        "move_pct": move_now, "extreme_move_pct": move_ext, "weeks": weeks_now,
        "extreme_date": ix[ext_i].strftime("%Y-%m-%d"), "extreme_level": ext_level,
        "drawback_from_extreme_pct": (cur_adj / ext_level - 1) * 100,
        "confirm_level": confirm_level,
        "confirm_rule": (f"A peak is confirmed if the front month closes at or below {confirm_level:.3f} "
                         f"(20% under the swing high of {ext_level:.3f})") if direction == "up" else
                        (f"A trough is confirmed if the front month closes at or above {confirm_level:.3f} "
                         f"(20% over the swing low of {ext_level:.3f})"),
        "amplitude_pctile": pct_rank([abs(a) for a, _ in same], abs(move_ext)),
        "duration_pctile": pct_rank([w for _, w in same], weeks_now),
        "typical_amplitude_pct": float(np.median([a for a, _ in same])) if same else None,
        "typical_weeks": float(np.median([w for _, w in same])) if same else None,
    }

    month_T = [0] * 12
    month_P = [0] * 12
    for p in pivots:
        m = int(p["date"][5:7]) - 1
        (month_T if p["type"] == "trough" else month_P)[m] += 1

    # Positioning analyses per source
    positioning = {}
    for key, label in POSITIONING_SOURCES.items():
        if key not in cftc["instruments"]:
            continue
        pos = positioning_frame(cftc, key)
        positioning[key] = {
            "label": label, "start": pos.index[0].strftime("%Y-%m-%d"), "end": pos.index[-1].strftime("%Y-%m-%d"),
            "event_study": event_study(pos, adj_w, piv_T, piv_P),
            "scorecard": scorecard(pos, piv_T, piv_P, last_confirmed),
            "signal_log": signal_log(pos, piv_T, piv_P, last_confirmed),
            "current": {"cot": float(pos.cot.iloc[-1]), "z": float(pos.z.iloc[-1]),
                        "flow4z": float(pos.flow4z.iloc[-1]) if pd.notna(pos.flow4z.iloc[-1]) else None,
                        "spec_cot": float(pos.spec_cot.iloc[-1]), "nonrept_cot": float(pos.nonrept_cot.iloc[-1]),
                        "prod_cot": float(pos.prod_cot.iloc[-1])},
            # Weekly history for the Date Inspector (report dates; CFTC publishes 3 days later)
            "history": {
                "dates": [t.strftime("%Y-%m-%d") for t in pos.index],
                "mm_cot": pos.cot.tolist(), "mm_z": pos.z.tolist(), "mm_flow2": pos.flow2.tolist(),
                "mm_flow4z": pos.flow4z.tolist(), "spec_cot": pos.spec_cot.tolist(),
                "prod_cot": pos.prod_cot.tolist(), "nonrept_cot": pos.nonrept_cot.tolist(),
                "signals": {k: [int(x) for x in rule(pos).reindex(pos.index).fillna(False).astype(bool)]
                            for k, _l, _t, rule, _d in SIGNALS},
            },
        }

    # First passage
    passage = {}
    cur_month = ix[-1].month
    # Real-time swing state for every week (last pivot CONFIRMED by that week)
    rt_state = pd.Series(index=adj_w.index, dtype="object")
    conf = sorted(((ix[p["ci"]], "up" if p["type"] == "T" else "down") for p in piv))
    j, s_now = 0, None
    for t in adj_w.index:
        while j < len(conf) and conf[j][0] <= t:
            s_now = conf[j][1]
            j += 1
        rt_state[t] = s_now
    pos_main = positioning_frame(cftc, "nat_gas_nyme")
    cot_bucket = pd.cut(pos_main.cot, [-1, 20, 80, 101], labels=["short", "mid", "long"]).astype("object")
    cur_bucket = "short" if pos_main.cot.iloc[-1] <= 20 else "long" if pos_main.cot.iloc[-1] >= 80 else "mid"
    months = pd.Series(adj_w.index.month, index=adj_w.index)
    near_months = {((cur_month - 2) % 12) + 1, cur_month, (cur_month % 12) + 1}
    for lvl in PASSAGE_LEVELS:
        fp = first_passage(adj_w, lvl)
        by_month = [passage_stats(fp, months == m) for m in range(1, 13)]
        cond = {
            "all_weeks": passage_stats(fp),
            "season": passage_stats(fp, months.isin(near_months)),
            "swing_state": passage_stats(fp, rt_state == direction),
            "positioning": passage_stats(fp, cot_bucket.reindex(fp.index) == cur_bucket),
            "season_and_swing": passage_stats(fp, months.isin(near_months) & (rt_state == direction)),
            "all_three": passage_stats(fp, months.isin(near_months) & (rt_state == direction)
                                       & (cot_bucket.reindex(fp.index) == cur_bucket)),
        }
        passage[f"{int(lvl * 100)}"] = {"level_pct": lvl * 100, "by_month": by_month, "conditions": cond}

    out = {
        "meta": {
            "model": MODEL_ID,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of": ix[-1].strftime("%Y-%m-%d"),
            "cftc_latest_report_date": cftc.get("meta", {}).get("latest_report_date"),
            "price_source": "Yahoo NG=F daily, roll-day returns neutralised, sampled on COT report dates",
            "rolls_neutralised": n_rolls,
            "params": {"swing_threshold_pct": SWING_TH * 100, "event_window_weeks": EVENT_WINDOW, "oos_split": OOS_SPLIT,
                       "hit_window_weeks": HIT_WINDOW, "passage_levels_pct": [l * 100 for l in PASSAGE_LEVELS],
                       "conditions_now": {"months": sorted(near_months), "swing_state": direction,
                                          "mm_cot_bucket": cur_bucket}},
        },
        "series": {"dates": [t.strftime("%Y-%m-%d") for t in ix], "front": front_ext.tolist(), "adjusted": adj_ext.tolist()},
        "pivots": pivots,
        "swing_stats": {
            "years": years, "cycles_per_year": sum(1 for p in pivots if p["type"] == "trough") / years,
            "up": {"n": len(ups), "median_pct": float(np.median([a for a, _ in ups])) if ups else None,
                   "median_weeks": float(np.median([w for _, w in ups])) if ups else None,
                   "swings": [[a, w] for a, w in ups]},
            "down": {"n": len(downs), "median_pct": float(np.median([a for a, _ in downs])) if downs else None,
                     "median_weeks": float(np.median([w for _, w in downs])) if downs else None,
                     "swings": [[a, w] for a, w in downs]},
            "median_confirm_lag_weeks": float(np.median([p["confirm_lag_weeks"] for p in pivots])),
            "troughs_by_month": month_T, "peaks_by_month": month_P,
        },
        "current": current,
        "positioning": positioning,
        "first_passage": passage,
    }
    return out


def main():
    ap = argparse.ArgumentParser(description="Henry Hub swing-cycle analysis")
    ap.add_argument("--prices-csv", help="Offline: CSV with date,close instead of Yahoo")
    args = ap.parse_args()
    with open(CFTC_PATH, "r", encoding="utf-8") as f:
        cftc = json.load(f)
    if args.prices_csv:
        df = pd.read_csv(args.prices_csv, parse_dates=["date"])
        front = df.set_index("date")["close"].astype(float)
    else:
        front = fetch_prices()
    out = sanitise(build(front, cftc))

    prev = None
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = None
    strip = lambda o: {k: v for k, v in o.items() if k != "meta"}  # noqa: E731
    changed = prev is None or strip(prev) != strip(json.loads(json.dumps(out)))
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), allow_nan=False)

    c, s = out["current"], out["swing_stats"]
    print(f"As of {c['as_of']}: front {c['price']:.3f}, swing {c['direction']} since {c['since_pivot']['date']} "
          f"({c['since_pivot']['type']} {c['since_pivot']['front_price']:.3f}); move {c['move_pct']:+.1f}% "
          f"(extreme {c['extreme_move_pct']:+.1f}%) over {c['weeks']:.0f}w; "
          f"amplitude pctile {c['amplitude_pctile']:.0f}, duration pctile {c['duration_pctile']:.0f}")
    print(f"  {c['confirm_rule']}")
    print(f"  {len(out['pivots'])} pivots, {s['cycles_per_year']:.2f} cycles/yr; up median {s['up']['median_pct']:+.0f}% "
          f"/{s['up']['median_weeks']:.0f}w, down median {s['down']['median_pct']:+.0f}%/{s['down']['median_weeks']:.0f}w")
    for lvl, fp in out["first_passage"].items():
        cc = fp["conditions"]
        print(f"  P(+{lvl}% before -{lvl}%): all {cc['all_weeks']['p_up_first']:.0%} (n={cc['all_weeks']['n']}), "
              + ", ".join(f"{k} {v['p_up_first']:.0%} (n={v['n']})" for k, v in cc.items() if k != 'all_weeks' and v.get('n')))
    for key, p in out["positioning"].items():
        print(f"  [{key}] " + "; ".join(f"{r['label']}: lift {r['lift']:.2f} ({r['pivots_caught']}/{r['pivots_total']})"
                                        for r in p["scorecard"] if r["lift"] is not None))
    print(f"  Wrote {OUTPUT_PATH} ({os.path.getsize(OUTPUT_PATH) / 1024:.0f} KB), changed={changed}")
    _set_gha_output("cycle_changed", "true" if changed else "false")


if __name__ == "__main__":
    main()
