"""
run_exit_sweep.py — systematic EXIT-layer search (entries frozen at v2-long).

Rationale: 2 years of testing says entry selection is ~zero-edge OHLCV-wide,
but the exit/execution layer is where value survived (variant B, partial-TP in
the ablation). Exits touch every trade and have far fewer degrees of freedom
than entries — less curve-fit surface.

Grid (64 configs): rrRatio {1.5,2.0,2.5,3.0} × partial {on@1R/50%, off}
                   × breakeven {off, 0.5R, 1.0R, 1.5R} × trend-exit {on, off}

Pre-registered protocol: rank configs on H1 net ONLY -> take the top config
(and top-5 list for context) -> validate on H2. A winner must beat base_v2 in
BOTH halves. Everything else is reported as the noise it probably is.

Usage:  py run_exit_sweep.py     (~10 min; writes reports/exit_sweep_<date>.md)
"""
from __future__ import annotations

from datetime import date
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import config_v2, run

BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]
REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2025-07-02")


def agg(trades):
    pnls = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls <= 0] if len(pnls) else np.array([])
    return {"n": len(pnls),
            "net": round(float(pnls.sum()), 0) if len(pnls) else 0.0,
            "pf": round(float(wins.sum() / -losses.sum()), 3)
                  if len(losses) and losses.sum() < 0 else np.nan}


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Exit sweep: loading cached 2y bars ...")
    spy = load_bars("SPY", 730)
    bars = {s: load_bars(s, 730) for s in BASKET}

    grid = list(product([1.5, 2.0, 2.5, 3.0],          # rrRatio
                        [True, False],                  # partial
                        [0.0, 0.5, 1.0, 1.5],           # beTrigger (0 = off)
                        [True, False]))                 # exitOnTrend
    print(f"  {len(grid)} exit configs × {len(BASKET)} symbols ...")

    rows = []
    for k, (rr, part, be, tex) in enumerate(grid):
        ovr = dict(rr_ratio=rr, use_partial=part,
                   use_breakeven=be > 0, be_trigger_r=be if be > 0 else 1.0,
                   exit_on_trend=tex)
        trades = []
        for s in BASKET:
            trades += run(bars[s], spy, config_v2(trade_dir="long"), **ovr)["trades"]
        h1 = [t for t in trades if pd.Timestamp(t["entry_time"]).tz_localize(None) < SPLIT]
        h2 = [t for t in trades if pd.Timestamp(t["entry_time"]).tz_localize(None) >= SPLIT]
        f, a1, a2 = agg(trades), agg(h1), agg(h2)
        rows.append({"rr": rr, "partial": part, "beR": be, "trend_exit": tex,
                     "n": f["n"], "net": f["net"], "pf": f["pf"],
                     "H1_net": a1["net"], "H1_pf": a1["pf"],
                     "H2_net": a2["net"], "H2_pf": a2["pf"]})
        if (k + 1) % 8 == 0:
            print(f"  {k + 1}/{len(grid)} done")

    df = pd.DataFrame(rows)
    base = df[(df.rr == 2.0) & df.partial & (df.beR == 1.0) & df.trend_exit].iloc[0]

    # pre-registered: rank on H1, validate on H2
    ranked = df.sort_values("H1_net", ascending=False).reset_index(drop=True)
    top = ranked.iloc[0]
    top5 = ranked.head(5)
    validated = (top.H1_net > base.H1_net) and (top.H2_net > base.H2_net)

    out = REPORTS / f"exit_sweep_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f_:
        f_.write(f"# Exit-layer sweep — {date.today().isoformat()}\n\n")
        f_.write(f"64 exit configs, entries frozen at v2-long, 2y, basket of 5. "
                 f"Protocol: rank on H1, validate on H2.\n\n")
        f_.write(f"**Base (v2.1 shipped): rr=2.0, partial@1R/50%, BE@1R, trend-exit on** "
                 f"-> net {base.net}, PF {base.pf} (H1 {base.H1_net}, H2 {base.H2_net})\n\n")
        f_.write(f"**H1 winner:** rr={top.rr}, partial={top.partial}, BE={top.beR}R, "
                 f"trend_exit={top.trend_exit} -> H1 {top.H1_net}, H2 {top.H2_net}\n\n")
        f_.write(f"**VALIDATED (beats base in both halves): {'YES' if validated else 'NO'}**\n\n")
        f_.write("## Top 5 by H1 (validation columns H2_*)\n\n")
        f_.write(top5.to_markdown(index=False) + "\n\n")
        f_.write("## Full grid\n\n" + df.sort_values("net", ascending=False)
                 .to_markdown(index=False) + "\n\n")
        f_.write("*Only a both-halves winner earns a change to SWING_PRO_v2.pine. "
                 "Not financial advice.*\n")
    print(f"\nH1 winner validated on H2: {validated}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
