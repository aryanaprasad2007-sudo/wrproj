"""
bootstrap_holdout.py — uncertainty band on the 2026-07-30 holdout winner.

The train/holdout sweep (run_holdout_sweep.py, 2026-07-30) found a config that
held up on the untouched 2015-2026 holdout: n=210 closed trades, PF 2.99,
win 51.4%, expR 0.648R, t-stat 5.36. Those are point estimates with no
uncertainty band.

This script reproduces that exact holdout trade set, then bootstraps it
(resample-with-replacement, 10,000 iterations) to put a 90% confidence
interval on expectancy (mean R) and profit factor, and reports what fraction
of resamples show expectancy <= 0 -- a rough "probability the edge is zero or
negative" under this sampling.

Winning config: 3-trading-session bars, adx_min=15, rsi_long_level=50,
atr_stop_mult=1.5, rr_ratio=2.0, trade_dir="long", use_htf_trend=False.

Usage:  py bootstrap_holdout.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from run_daily_30y import SYMBOLS, fetch_daily
from run_timeframe_scan import group_bars
from swing_pro import config_v22, run

REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2015-01-01")
MIN_BARS = 260
TF = 3
N_SIM = 10_000
rng = np.random.default_rng(7)

CFG_PARAMS = dict(trade_dir="long", use_htf_trend=False,
                   adx_min=15, rsi_long_level=50,
                   atr_stop_mult=1.5, rr_ratio=2.0)


def collect_holdout_r() -> list:
    print("Loading 30y daily bars (cached)...")
    spy_d = fetch_daily("SPY")
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = fetch_daily(s)
        except Exception:
            pass
    print(f"{len(data)} symbols")

    spy = group_bars(spy_d, TF)
    cfg = config_v22(**CFG_PARAMS)

    r_vals, tested = [], 0
    for sym, df in data.items():
        g = group_bars(df, TF)
        if len(g) < MIN_BARS:
            continue
        try:
            res = run(g, spy, cfg)
        except Exception:
            continue
        tested += 1
        for t in res["trades"]:
            if t.get("pnl") is None:
                continue
            ts = pd.Timestamp(t["entry_time"])
            ts = ts.tz_localize(None) if ts.tzinfo else ts
            if ts < SPLIT:
                continue
            r = t.get("r", np.nan)
            if not np.isnan(r):
                r_vals.append(float(r))
    print(f"{tested} symbols tested, {len(r_vals)} holdout trades collected")
    return r_vals


def profit_factor(r: np.ndarray) -> float:
    pos = r[r > 0].sum()
    neg = r[r < 0].sum()
    if neg >= 0:
        return np.nan
    return float(pos / -neg)


def main():
    REPORTS.mkdir(exist_ok=True)
    r_vals = collect_holdout_r()
    r = np.array(r_vals)
    n = len(r)

    point_expR = float(r.mean())
    point_pf = profit_factor(r)
    print(f"\nPoint estimate: n={n} expR={point_expR:.4f} PF={point_pf:.3f}")

    print(f"Running {N_SIM:,}-iteration bootstrap...")
    boot_expR = np.empty(N_SIM)
    boot_pf = np.empty(N_SIM)
    for i in range(N_SIM):
        idx = rng.integers(0, n, n)
        s = r[idx]
        boot_expR[i] = s.mean()
        boot_pf[i] = profit_factor(s)

    exp_p5, exp_p50, exp_p95 = np.percentile(boot_expR, [5, 50, 95])
    pf_valid = boot_pf[~np.isnan(boot_pf)]
    pf_p5, pf_p50, pf_p95 = np.percentile(pf_valid, [5, 50, 95])
    frac_nonpositive = float((boot_expR <= 0).mean())
    n_pf_nan = int(np.isnan(boot_pf).sum())

    zero_in_ci = "INSIDE" if exp_p5 <= 0 <= exp_p95 else "OUTSIDE"

    print(f"\nExpectancy 90% CI: [{exp_p5:.4f}, {exp_p95:.4f}]  median {exp_p50:.4f}")
    print(f"Profit factor 90% CI: [{pf_p5:.3f}, {pf_p95:.3f}]  median {pf_p50:.3f}")
    print(f"P(expectancy <= 0) = {frac_nonpositive*100:.2f}%")
    print(f"Zero/negative expectancy is {zero_in_ci} the 90% CI")

    stamp = date.today().isoformat()
    out = REPORTS / f"bootstrap_holdout_{stamp}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Bootstrap CI on the holdout winner — {stamp}\n\n")
        f.write("Reproduces the 2015-2026 holdout trade set for the train-sweep "
                "winner from 2026-07-30 (`run_holdout_sweep.py`) and bootstraps "
                f"it {N_SIM:,} times (resample-with-replacement) to put an "
                "uncertainty band on the point-estimate expectancy and profit "
                "factor.\n\n")
        f.write(f"**Config:** 3-trading-session bars, adx_min=15, "
                f"rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0, "
                f"trade_dir=\"long\", use_htf_trend=False\n\n")
        f.write("## Reproduced holdout sample\n\n")
        f.write(f"- Trades (entry_time >= 2015-01-01): **n={n}**\n")
        f.write(f"- Point-estimate expectancy: **{point_expR:.4f}R**\n")
        f.write(f"- Point-estimate profit factor: **{point_pf:.3f}**\n\n")
        if n != 210:
            f.write(f"*Note: original sweep reported n=210; this run reproduced "
                    f"n={n}. Difference likely reflects data-cache refresh since "
                    f"2026-07-30 (new bars appended, or a symbol fetch failure) "
                    f"rather than a config mismatch.*\n\n")
        f.write(f"## Bootstrap ({N_SIM:,} resamples, resample-with-replacement, n={n} per resample)\n\n")
        f.write("| metric | 5th pct | median | 95th pct |\n|---|---|---|---|\n")
        f.write(f"| Expectancy (mean R) | {exp_p5:.4f} | {exp_p50:.4f} | {exp_p95:.4f} |\n")
        f.write(f"| Profit factor | {pf_p5:.3f} | {pf_p50:.3f} | {pf_p95:.3f} |\n\n")
        if n_pf_nan:
            f.write(f"*{n_pf_nan} of {N_SIM:,} resamples had zero losing trades "
                    f"(profit factor undefined) and were excluded from the PF "
                    f"percentiles.*\n\n")
        f.write(f"**P(expectancy <= 0) = {frac_nonpositive*100:.2f}%** — the "
                f"fraction of resamples where the edge would have been zero or "
                f"negative.\n\n")
        f.write(f"**Zero/negative expectancy is {zero_in_ci} the 90% confidence "
                f"interval.**\n\n")
        if zero_in_ci == "OUTSIDE":
            f.write("The bootstrap does not overlap zero at the 90% level — under "
                    "this resampling, the edge on the holdout sample looks real, "
                    "not noise.\n\n")
        else:
            f.write("The bootstrap's lower tail reaches zero or below at the 90% "
                    "level — the holdout sample alone cannot rule out a "
                    "zero-or-negative true edge with this much confidence.\n\n")
        f.write("*Bootstrap assumes trade independence; real trades cluster by "
                "regime and symbol, so true tails are somewhat fatter than shown "
                "here. Not financial advice. No trades were placed in producing "
                "this report.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
