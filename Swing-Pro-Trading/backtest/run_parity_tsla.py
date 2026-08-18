"""
run_parity_tsla.py — parity check: Python engine vs the TradingView Strategy
Tester numbers read off Ari's screen (2026-07-02).

TradingView (TSLA, SWING_PRO_v2, Dec 22 2025 - Jul 1 2026, 100K, defaults):
  Total PnL +814.49 (+0.81%) | 13 trades, 46.15% win | PF 2.469
  Max DD $352.31 | avg PnL $64.69 | largest win 567.38 / loss 180.45 | avg bars 69
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import config_v22, config_v2, run

TV = {"net": 814.49, "trades": 13, "win%": 46.15, "pf": 2.469,
      "largest_win": 567.38, "largest_loss": 180.45, "avg_bars": 69}
START = pd.Timestamp("2025-12-22", tz="America/New_York")


def summarize(name, res, df):
    tr = res["trades"]
    if not tr:
        print(f"{name}: no trades")
        return
    pnls = np.array([t["pnl"] for t in tr])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    idx = df.index
    bars = []
    for t in tr:
        try:
            e = idx.get_loc(pd.Timestamp(t["entry_time"]))
            x = idx.get_loc(pd.Timestamp(t["exit_time"]))
            bars.append(x - e)
        except KeyError:
            pass
    print(f"\n{name}")
    print(f"  trades        : {len(tr)}   (TV: {TV['trades']})")
    print(f"  net PnL       : {pnls.sum():+.2f}   (TV: +{TV['net']})")
    print(f"  win rate      : {len(wins) / len(tr) * 100:.2f}%   (TV: {TV['win%']}%)")
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    print(f"  profit factor : {pf:.3f}   (TV: {TV['pf']})")
    print(f"  largest win   : {pnls.max():+.2f}   (TV: +{TV['largest_win']})")
    print(f"  largest loss  : {pnls.min():+.2f}   (TV: -{TV['largest_loss']})")
    if bars:
        print(f"  avg bars/trade: {np.mean(bars):.0f}   (TV: {TV['avg_bars']})")
    print("  trade list:")
    for t in tr:
        print(f"    {t['entry_time'][:16]} -> {str(t.get('exit_time'))[:16]}  "
              f"{t['exits'][-1][3]:<11} pnl {t['pnl']:+8.2f}")


def main():
    spy = load_bars("SPY", 730)
    tsla = load_bars("TSLA", 730)
    df = tsla[tsla.index >= START]
    spy_w = spy[spy.index >= START]
    print(f"TSLA window: {df.index[0]} -> {df.index[-1]}  ({len(df)} bars)")

    summarize("Python v2.2 long-only (expected match)",
              run(df, spy_w, config_v22(trade_dir="long")), df)
    summarize("Python v2.1 long-only (in case the old script is still loaded)",
              run(df, spy_w, config_v2(trade_dir="long")), df)


if __name__ == "__main__":
    main()
