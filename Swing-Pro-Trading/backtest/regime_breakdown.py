"""
regime_breakdown.py — descriptive regime/vol split of the 2026-07-30 holdout winner.

Context: run_holdout_sweep.py found tf=3 adx_min=15 rsi_long=50 stop=1.5xATR
rr=2.0 as the train-selected config, and it held up on the untouched 2015-2026
holdout (PF 2.99, t 5.36 — reports/holdout_sweep_2026-07-30.md). An aggregate
number like that can hide a config that only works in one market regime and
loses in another. This script runs the SAME config on the FULL 1995-2026
basket (no train/holdout split — this is a post-hoc descriptive breakdown,
not a new selection) and cuts every closed trade two ways:

  1. Momentum regime: SPY close > rising 50d SMA, decided on the PRIOR close.
     This is the EXACT frozen classifier from switch_shadow.py (registered
     2026-07-11) — reused verbatim, not re-derived, so this split is
     apples-to-apples with the switch-policy audition.
  2. Vol regime: rolling 20d SPY daily-return stdev, decided on the PRIOR
     close (same lag convention as #1 for consistency), bucketed above/below
     the vol series' OWN full-history median (a fixed threshold over
     1995-2026, not an expanding one — "historical median" read as the
     series' own distribution, not a look-ahead-free running estimate).

Both classifiers run on DAILY SPY bars regardless of the 3-session bars the
engine itself trades on — switch_shadow's classifier is explicitly a daily
close comparison, so grouping it to 3-session bars would be a different
(untested) rule. Trades are assigned to a regime by their entry_time via
an as-of lookup against the daily regime series.

This is PURELY DESCRIPTIVE. A near-identical regime-gating idea was already
tested and REJECTED for single-symbol trading on 2026-07-30 (see
reports/ for that date's switch/symbol-test material) — this script does not
revisit that verdict and produces no recommendation to gate any live config.
No orders, no broker calls, no Pine script changes.

Usage:  py regime_breakdown.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import indicators as ta
from run_daily_30y import SYMBOLS, fetch_daily
from run_timeframe_scan import group_bars
from swing_pro import config_v22, run

REPORTS = Path(__file__).parent / "reports"
TF = 3
WINNER = dict(adx_min=15, rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0)


def _naive(t) -> pd.Timestamp:
    ts = pd.Timestamp(t)
    return ts.tz_localize(None) if ts.tzinfo else ts


def build_daily_regimes(spy_daily: pd.DataFrame) -> pd.DataFrame:
    """Frozen momentum classifier from switch_shadow.py (verbatim) plus a
    vol-regime split, both decided on the PRIOR daily close."""
    c = spy_daily["close"]
    sma50 = pd.Series(ta.sma(c.to_numpy(float), 50), index=c.index)
    mom_raw = (c > sma50) & (sma50 > sma50.shift(5))
    mom = mom_raw.shift(1).fillna(False).astype(bool)

    ret = c.pct_change()
    vol20 = ret.rolling(20).std()
    vol_med = vol20.median()  # fixed threshold over the full 1995-2026 vol series
    high_vol_raw = vol20 > vol_med
    high_vol = high_vol_raw.shift(1).fillna(False).astype(bool)

    return pd.DataFrame({"momentum": mom, "high_vol": high_vol}, index=c.index)


def label_trades(trades: list, regimes: pd.DataFrame) -> list:
    mom_series = regimes["momentum"]
    vol_series = regimes["high_vol"]
    out = []
    for t in trades:
        if t.get("pnl") is None or t.get("r") is None:
            continue
        entry = _naive(t["entry_time"])
        try:
            mom = bool(mom_series.asof(entry))
            hv = bool(vol_series.asof(entry))
        except Exception:
            continue
        if pd.isna(mom) or pd.isna(hv):
            continue
        out.append({**t, "momentum": mom, "high_vol": hv})
    return out


def stats(trades: list) -> dict:
    if not trades:
        return {"n": 0, "pf": np.nan, "win%": np.nan, "expR": np.nan, "t": np.nan}
    p = np.array([t["pnl"] for t in trades])
    R = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    w, l = p[p > 0], p[p <= 0]
    tstat = (float(R.mean()) / (float(R.std(ddof=1)) / np.sqrt(len(R)))
             if len(R) > 2 and R.std(ddof=1) > 0 else np.nan)
    return {"n": int(len(p)),
            "pf": round(float(w.sum() / -l.sum()), 3) if len(l) and l.sum() < 0 else np.nan,
            "win%": round(100 * len(w) / len(p), 1),
            "expR": round(float(R.mean()), 4) if len(R) else np.nan,
            "t": round(tstat, 2) if tstat == tstat else np.nan}


def bucket(trades: list, **filters) -> list:
    return [t for t in trades if all(t[k] == v for k, v in filters.items())]


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Loading 30y daily bars (cached) ...")
    spy_daily = fetch_daily("SPY")
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = fetch_daily(s)
        except Exception as e:
            print(f"  {s}: FAILED ({e})")
    print(f"{len(data)}/{len(SYMBOLS)} symbols loaded")

    regimes = build_daily_regimes(spy_daily)

    spy3 = group_bars(spy_daily, TF)
    cfg = config_v22(trade_dir="long", use_htf_trend=False, **WINNER)

    all_trades, tested = [], 0
    for sym, df in data.items():
        df3 = group_bars(df, TF)
        if len(df3) < 260:
            continue
        try:
            r = run(df3, spy3, cfg)
        except Exception as e:
            print(f"  {sym}: run failed ({e})")
            continue
        tested += 1
        all_trades += r["trades"]

    closed = label_trades(all_trades, regimes)
    print(f"{tested}/{len(data)} symbols tested · {len(closed)} closed trades labeled "
          f"(of {len(all_trades)} total)")

    overall = stats(closed)
    mom_only = stats(bucket(closed, momentum=True))
    nonmom_only = stats(bucket(closed, momentum=False))
    hv_only = stats(bucket(closed, high_vol=True))
    lv_only = stats(bucket(closed, high_vol=False))
    four = {
        "momentum x high-vol": stats(bucket(closed, momentum=True, high_vol=True)),
        "momentum x low-vol": stats(bucket(closed, momentum=True, high_vol=False)),
        "non-momentum x high-vol": stats(bucket(closed, momentum=False, high_vol=True)),
        "non-momentum x low-vol": stats(bucket(closed, momentum=False, high_vol=False)),
    }

    def pf_ok(s):
        return isinstance(s["pf"], float) and not np.isnan(s["pf"]) and s["pf"] > 1.0

    def t_ok(s):
        return isinstance(s["t"], float) and not np.isnan(s["t"]) and s["t"] > 2.0

    two_way_universal = all(pf_ok(s) and s["n"] >= 20 for s in
                            (mom_only, nonmom_only, hv_only, lv_only))
    four_way_universal = all(pf_ok(s) and s["n"] >= 20 for s in four.values())

    if four_way_universal:
        verdict = ("REGIME-UNIVERSAL — PF > 1.0 in all four momentum x vol buckets "
                   "(each with >=20 trades); the edge is not concentrated in one regime.")
    elif two_way_universal:
        verdict = ("MOSTLY REGIME-UNIVERSAL on the two 2-way splits, but at least one "
                   "of the four finer momentum x vol buckets is weak or thin — see the "
                   "table below for which one.")
    else:
        verdict = ("REGIME-CONCENTRATED — at least one momentum or vol bucket shows "
                   "PF <= 1.0 (or too few trades to judge). The aggregate holdout number "
                   "is being carried by a subset of regimes, not all of them.")

    stamp = date.today().isoformat()
    out = REPORTS / f"regime_breakdown_{stamp}.md"
    rows2way = [
        {"bucket": "Momentum (SPY above rising 50d)", **mom_only},
        {"bucket": "Non-momentum (SPY below / 50d not rising)", **nonmom_only},
        {"bucket": "High-vol (20d SPY vol > historical median)", **hv_only},
        {"bucket": "Low-vol (20d SPY vol <= historical median)", **lv_only},
    ]
    rows4way = [{"bucket": k, **v} for k, v in four.items()]

    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Regime breakdown of the 2026-07-30 holdout winner — {stamp}\n\n")
        f.write(f"Config: `tf={TF} adx_min={WINNER['adx_min']} "
                f"rsi_long={WINNER['rsi_long_level']} stop={WINNER['atr_stop_mult']}xATR "
                f"rr={WINNER['rr_ratio']}` · engine `swing_pro.config_v22` · "
                f"{tested}/{len(SYMBOLS)}-symbol basket (`run_daily_30y.SYMBOLS`) · "
                "FULL 1995-2026 sample, no train/holdout split (descriptive only).\n\n")
        f.write("Momentum classifier: frozen rule from `switch_shadow.py` (registered "
                "2026-07-11) — SPY close > rising 50d SMA, decided on the prior daily "
                "close. Reused verbatim. Vol classifier: rolling 20d SPY daily-return "
                "stdev, same prior-close lag convention, bucketed against the vol "
                "series' own full-history median. Both computed on DAILY SPY bars "
                "independent of the 3-session bars the engine trades on.\n\n")
        f.write(f"**Overall (all closed trades, unsplit): n={overall['n']} "
                f"PF={overall['pf']} win%={overall['win%']} expR={overall['expR']} "
                f"t={overall['t']}**\n\n")
        f.write("## Two-way splits\n\n")
        f.write(pd.DataFrame(rows2way).to_markdown(index=False))
        f.write("\n\n## Four-way split (momentum x vol)\n\n")
        f.write(pd.DataFrame(rows4way).to_markdown(index=False))
        f.write(f"\n\n## Verdict\n\n{verdict}\n\n")
        f.write("This is descriptive context on where the edge concentrates, not a "
                "reason to add regime-gating to any live config — a similar idea was "
                "already tested and rejected for single-symbol trading on 2026-07-30. "
                "No orders were placed, no broker or Pine state was touched.\n")

    print(f"\nOverall: {overall}")
    print("Two-way:")
    for r in rows2way:
        print(f"  {r}")
    print("Four-way:")
    for r in rows4way:
        print(f"  {r}")
    print(f"\nVerdict: {verdict}")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
