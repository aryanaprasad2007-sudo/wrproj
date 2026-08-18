"""
run_holdout_sweep.py — aggressive parameter search with an honest verdict.

DESIGN (agreed with Ari 2026-07-30, and the discipline is the whole point):
  TRAIN   1995-01-01 -> 2015-01-01   search as hard as you like here
  HOLDOUT 2015-01-01 -> today        looked at ONCE, for the train winner only

The holdout is what makes an aggressive sweep safe. Search thousands of configs
against train and the best one is guaranteed to look good -- that is arithmetic,
not evidence. The single number that means anything is how that winner performs
on data the search never touched.

RANKING METRIC: t-stat of per-trade R  =  mean(R) / (std(R)/sqrt(n)).
NOT profit factor and NOT net PnL. Both of those improve as the sample shrinks,
so ranking on them selects the config that traded least and got luckiest. The
t-stat penalises small samples automatically. A MIN_TRAIN_TRADES floor is also
enforced so a 9-trade fluke cannot win.

ONE SHOT: only the top-ranked train config is scored on the holdout. Alongside
it, pre-specified BASELINES (the current live config at each timeframe) are also
scored -- those are not selected from the sweep, so they are fair comparisons
and cost nothing in multiple-comparison terms.

Timeframes are N consecutive TRADING sessions per bar (1D=1, 1W=5, 2W=10).

Usage:
    py run_holdout_sweep.py                 full grid (slow, ~10 min)
    py run_holdout_sweep.py --smoke         tiny grid, to check plumbing
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from run_daily_30y import SYMBOLS, fetch_daily
from run_timeframe_scan import group_bars
from swing_pro import config_v22, run

REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2015-01-01")
MIN_TRAIN_TRADES = 120          # floor so a tiny lucky sample cannot win
MIN_BARS = 260

# The search space. Timeframe spans the 2D-2W plateau found by the scan.
GRID = {
    "tf":            [2, 3, 5, 10],
    "adx_min":       [10, 15, 20, 25],
    "rsi_long_level": [45, 50, 55],
    "atr_stop_mult": [1.0, 1.5, 2.0, 2.5],
    "rr_ratio":      [1.5, 2.0, 2.5, 3.0, 4.0],
}
SMOKE = {"tf": [3, 5], "adx_min": [20], "rsi_long_level": [52],
         "atr_stop_mult": [1.5], "rr_ratio": [3.0]}


def stats(trades: list, n_sym_tested: int) -> dict:
    p = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    R = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    if not len(p):
        return {"n": 0, "pf": np.nan, "win%": np.nan, "expR": np.nan,
                "t": np.nan, "net": 0.0}
    w, l = p[p > 0], p[p <= 0]
    t = (float(R.mean()) / (float(R.std(ddof=1)) / np.sqrt(len(R)))
         if len(R) > 2 and R.std(ddof=1) > 0 else np.nan)
    return {"n": int(len(p)),
            "pf": round(float(w.sum() / -l.sum()), 3) if len(l) and l.sum() < 0 else np.nan,
            "win%": round(100 * len(w) / len(p), 1),
            "expR": round(float(R.mean()), 4) if len(R) else np.nan,
            "t": round(t, 2) if t == t else np.nan,
            "net": round(float(p.sum()))}


def split_trades(trades: list):
    tr_train, tr_hold = [], []
    for t in trades:
        ts = pd.Timestamp(t["entry_time"])
        ts = ts.tz_localize(None) if ts.tzinfo else ts
        (tr_train if ts < SPLIT else tr_hold).append(t)
    return tr_train, tr_hold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    grid = SMOKE if a.smoke else GRID
    REPORTS.mkdir(exist_ok=True)

    print("Loading 30y daily bars (cached)...")
    spy_d = fetch_daily("SPY")
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = fetch_daily(s)
        except Exception:
            pass
    print(f"{len(data)} symbols")

    # pre-group bars once per timeframe (the expensive-ish part done N times not N*configs)
    tfs = sorted(set(grid["tf"]))
    grouped = {n: ({s: group_bars(df, n) for s, df in data.items()},
                   group_bars(spy_d, n)) for n in tfs}
    print(f"grouped bars for timeframes {tfs}")

    keys = ["tf", "adx_min", "rsi_long_level", "atr_stop_mult", "rr_ratio"]
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"sweeping {len(combos)} configs x {len(data)} symbols "
          f"= {len(combos)*len(data)} runs\n")

    t0, rows = time.time(), []
    for i, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        n = params["tf"]
        dfs, spy = grouped[n]
        cfg = config_v22(trade_dir="long", use_htf_trend=False,
                         adx_min=params["adx_min"],
                         rsi_long_level=params["rsi_long_level"],
                         atr_stop_mult=params["atr_stop_mult"],
                         rr_ratio=params["rr_ratio"])
        all_tr, tested, prof_train = [], 0, 0
        for sym, df in dfs.items():
            if len(df) < MIN_BARS:
                continue
            try:
                r = run(df, spy, cfg)
            except Exception:
                continue
            tested += 1
            tr = [t for t in r["trades"] if t.get("pnl") is not None]
            all_tr += tr
            tr_train, _ = split_trades(tr)
            if sum(t["pnl"] for t in tr_train) > 0:
                prof_train += 1
        tr_train, tr_hold = split_trades(all_tr)
        S_tr = stats(tr_train, tested)
        S_ho = stats(tr_hold, tested)
        rows.append({**params, "tested": tested,
                     "train_breadth": f"{prof_train}/{tested}",
                     **{f"train_{k}": v for k, v in S_tr.items()},
                     # holdout stored but NOT used for ranking or selection
                     **{f"_hold_{k}": v for k, v in S_ho.items()}})
        if i % 20 == 0 or i == len(combos):
            print(f"  {i}/{len(combos)}  ({time.time()-t0:.0f}s)")

    df = pd.DataFrame(rows)
    eligible = df[(df["train_n"] >= MIN_TRAIN_TRADES) & df["train_t"].notna()].copy()
    if eligible.empty:
        print("no config cleared the minimum train-trade floor"); return
    eligible = eligible.sort_values("train_t", ascending=False).reset_index(drop=True)

    print("\n=== TRAIN LEADERBOARD (1995-2015) — holdout NOT consulted ===")
    show = ["tf", "adx_min", "rsi_long_level", "atr_stop_mult", "rr_ratio",
            "train_n", "train_win%", "train_pf", "train_expR", "train_t",
            "train_breadth"]
    print(eligible[show].head(12).to_string(index=False))

    win = eligible.iloc[0]
    print(f"\n=== TRAIN WINNER (selected on train t-stat alone) ===")
    print(f"  tf={win['tf']} sessions/bar · adx_min={win['adx_min']} · "
          f"rsi_long={win['rsi_long_level']} · stop={win['atr_stop_mult']}xATR · "
          f"rr={win['rr_ratio']}")
    print(f"  TRAIN   n={win['train_n']} PF {win['train_pf']} win {win['train_win%']}% "
          f"expR {win['train_expR']} t={win['train_t']} breadth {win['train_breadth']}")
    print(f"\n=== HOLDOUT 2015-2026 — opened once, for this config only ===")
    print(f"  HOLDOUT n={win['_hold_n']} PF {win['_hold_pf']} win {win['_hold_win%']}% "
          f"expR {win['_hold_expR']} t={win['_hold_t']} net ${win['_hold_net']:,}")
    decay = ((win['_hold_expR'] - win['train_expR']) / abs(win['train_expR']) * 100
             if win['train_expR'] else np.nan)
    print(f"  expectancy change train -> holdout: {decay:+.1f}%")
    verdict = ("HOLDS UP" if (win['_hold_t'] == win['_hold_t'] and win['_hold_t'] > 2
                              and win['_hold_pf'] > 1.15) else "DOES NOT HOLD")
    print(f"  VERDICT: {verdict}")

    # pre-specified baselines (NOT selected by the sweep, so fair to also score)
    print("\n=== BASELINES (live config, not sweep-selected) on the same holdout ===")
    base_rows = []
    for n in tfs:
        b = df[(df["tf"] == n) & (df["adx_min"] == 20) &
               (df["rsi_long_level"] == 52 if 52 in grid["rsi_long_level"] else True) &
               (df["atr_stop_mult"] == 1.5) & (df["rr_ratio"] == 3.0)]
        if not b.empty:
            r = b.iloc[0]
            base_rows.append(r)
            print(f"  tf={n:>2}  HOLDOUT n={r['_hold_n']} PF {r['_hold_pf']} "
                  f"expR {r['_hold_expR']} t={r['_hold_t']}")
    if not base_rows:
        print("  (live config not in this grid — rsi_long_level 52 not swept)")

    stamp = date.today().isoformat()
    eligible.to_csv(REPORTS / f"holdout_sweep_{stamp}.csv", index=False)
    with open(REPORTS / f"holdout_sweep_{stamp}.md", "w", encoding="utf-8") as f:
        f.write(f"# Train/holdout parameter sweep — {stamp}\n\n")
        f.write(f"Train 1995-2015 · Holdout 2015-2026 · {len(combos)} configs · "
                f"22-symbol basket · ranked on train t-stat with a "
                f"{MIN_TRAIN_TRADES}-trade floor.\n\n")
        f.write("The holdout was computed for every config but used for NOTHING except "
                "reporting the single train winner below — no config was chosen, tuned or "
                "filtered using it.\n\n## Train leaderboard\n\n")
        f.write(eligible[show].head(15).to_markdown(index=False))
        f.write(f"\n\n## Winner on the untouched holdout\n\n"
                f"`tf={win['tf']} adx_min={win['adx_min']} rsi_long={win['rsi_long_level']} "
                f"stop={win['atr_stop_mult']}xATR rr={win['rr_ratio']}`\n\n"
                f"| split | n | PF | win% | expR | t |\n|---|---|---|---|---|---|\n"
                f"| train | {win['train_n']} | {win['train_pf']} | {win['train_win%']} | "
                f"{win['train_expR']} | {win['train_t']} |\n"
                f"| **holdout** | {win['_hold_n']} | {win['_hold_pf']} | {win['_hold_win%']} | "
                f"{win['_hold_expR']} | {win['_hold_t']} |\n\n"
                f"Expectancy change: **{decay:+.1f}%** · **VERDICT: {verdict}**\n")
    print(f"\n-> {REPORTS / f'holdout_sweep_{stamp}.md'}")


if __name__ == "__main__":
    main()
