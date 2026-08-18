"""
run_ab_v2.py — head-to-head: SWING_PRO baseline (v1) vs config_v2.

v2 = v1 minus MACD-flip exit, minus volume gate, minus (dead) trend gate.
Note the one-at-a-time ablation never tested these removals COMBINED — that
interaction is exactly what this A/B measures.

Usage:  py run_ab_v2.py [--days 59] [--dir both|long|short]
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import Config, config_v2, run

BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]
REPORTS = Path(__file__).parent / "reports"


def side_stats(trades: list[dict]) -> dict:
    pnls = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    rs = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls <= 0] if len(pnls) else np.array([])
    return {
        "trades": len(pnls),
        "net_usd": round(float(pnls.sum()), 0) if len(pnls) else 0.0,
        "exp_R": round(float(rs.mean()), 3) if len(rs) else np.nan,
        "win_%": round(float(len(wins) / len(pnls) * 100), 1) if len(pnls) else np.nan,
        "pf": round(float(wins.sum() / -losses.sum()), 2)
              if len(losses) and losses.sum() < 0 else np.nan,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=59)
    ap.add_argument("--dir", default="both", choices=["both", "long", "short"])
    args = ap.parse_args()

    REPORTS.mkdir(exist_ok=True)
    spy = load_bars("SPY", args.days)
    bars = {s: load_bars(s, args.days) for s in BASKET}

    cfgs = {"v1_baseline": Config(trade_dir=args.dir),
            "v2": config_v2(trade_dir=args.dir)}

    rows, agg = [], {}
    for name, cfg in cfgs.items():
        all_trades = []
        for s in BASKET:
            r = run(bars[s], spy, cfg)
            st = r["stats"]
            rows.append({"config": name, "symbol": s, "trades": st["trades"],
                         "net_usd": round(st["net_profit"], 0),
                         "exp_R": round(st["expectancy_r"], 3),
                         "win_%": round(st["win_rate"], 1),
                         "pf": round(st["profit_factor"], 2),
                         "maxDD_%": round(st["max_dd_pct"], 2)})
            all_trades.extend(r["trades"])
        agg[name] = side_stats(all_trades)
        # long/short split — direction matters for "which side has the edge"
        agg[name + " (longs)"] = side_stats([t for t in all_trades if t["side"] == "long"])
        agg[name + " (shorts)"] = side_stats([t for t in all_trades if t["side"] == "short"])

    per_sym = pd.DataFrame(rows)
    agg_df = pd.DataFrame(agg).T

    print("\n== Aggregate (basket) ==")
    print(agg_df.to_string())
    print("\n== Per symbol ==")
    print(per_sym.to_string(index=False))

    out = REPORTS / f"ab_v1_vs_v2_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# SWING_PRO v1 vs v2 — {date.today().isoformat()}\n\n")
        f.write(f"Basket: {', '.join(BASKET)} · 5m · {args.days}d · dir={args.dir}\n\n")
        f.write("v2 = v1 **minus** MACD-flip exit, volume gate, dead trend gate "
                "(see ablation_2026-07-01.md for the evidence).\n\n")
        f.write("## Aggregate\n\n" + agg_df.to_markdown() + "\n\n")
        f.write("## Per symbol\n\n" + per_sym.to_markdown(index=False) + "\n\n")
        f.write("*Same 59-day window the ablation used — v2 is IN-SAMPLE by "
                "construction. The verdict that counts comes from walk-forward on "
                "longer (Alpaca) history. Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
