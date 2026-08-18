"""
run_universe_scan.py — WHERE does the v2.2 engine actually fit?

The one axis never tested: symbol selection. Momentum engines often fit
higher-beta names better than mega-caps. ~50 liquid US names, 2y of 5m bars,
v2.2 long-only on each.

Pre-registered protocol (single shot):
  1. Rank every symbol by H1 profit factor (min 25 H1 trades).
  2. The top-5 H1 basket is THE candidate. Validate its aggregate on H2 vs the
     current basket's H2. No re-picking after seeing H2.

Usage:  py run_universe_scan.py     (fetch-heavy first run; ~20-30 min)
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import config_v22, run

UNIVERSE = [
    # current basket
    "AAPL", "NVDA", "TSLA", "MSFT", "META",
    # mega/large tech & semis
    "AMZN", "GOOGL", "AMD", "AVGO", "NFLX", "CRM", "ORCL", "ADBE", "INTC",
    "MU", "QCOM", "AMAT", "LRCX", "KLAC", "ARM", "SMCI", "DELL",
    # high-beta momentum names
    "PLTR", "COIN", "MSTR", "HOOD", "SHOP", "PYPL", "UBER", "ABNB", "DASH",
    "SNOW", "CRWD", "PANW", "NET", "DDOG", "MDB",
    # other sectors (does the engine generalize at all?)
    "BA", "CAT", "DE", "GS", "JPM", "XOM", "CVX", "UNH", "LLY",
    "WMT", "COST", "HD", "DIS",
]
REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2025-07-02")
CURRENT = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]


def halves(trades):
    h1 = [t for t in trades if pd.Timestamp(t["entry_time"]).tz_localize(None) < SPLIT]
    h2 = [t for t in trades if pd.Timestamp(t["entry_time"]).tz_localize(None) >= SPLIT]
    return h1, h2


def agg(trades):
    pnls = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls <= 0] if len(pnls) else np.array([])
    return {"n": len(pnls), "net": round(float(pnls.sum()), 0) if len(pnls) else 0,
            "pf": round(float(wins.sum() / -losses.sum()), 2)
                  if len(losses) and losses.sum() < 0 else np.nan}


def main():
    REPORTS.mkdir(exist_ok=True)
    spy = load_bars("SPY", 730)
    cfg = config_v22(trade_dir="long")

    rows, trades_by_sym = [], {}
    for i, s in enumerate(UNIVERSE):
        try:
            df = load_bars(s, 730)
            r = run(df, spy, cfg)
        except Exception as e:
            print(f"  {s}: FAILED ({e})")
            continue
        tr = r["trades"]
        trades_by_sym[s] = tr
        h1, h2 = halves(tr)
        a1, a2 = agg(h1), agg(h2)
        rows.append({"symbol": s, "n": len(tr),
                     "H1_n": a1["n"], "H1_net": a1["net"], "H1_pf": a1["pf"],
                     "H2_n": a2["n"], "H2_net": a2["net"], "H2_pf": a2["pf"],
                     "full_net": round(sum(t["pnl"] for t in tr), 0)})
        print(f"  [{i + 1}/{len(UNIVERSE)}] {s}: n={len(tr)} "
              f"H1 pf={a1['pf']} H2 pf={a2['pf']}")

    df = pd.DataFrame(rows)
    eligible = df[(df.H1_n >= 25) & df.H1_pf.notna()].sort_values("H1_pf", ascending=False)
    top5 = list(eligible.head(5).symbol)

    cand_h2 = agg([t for s in top5 for t in halves(trades_by_sym[s])[1]])
    curr_h2 = agg([t for s in CURRENT if s in trades_by_sym
                   for t in halves(trades_by_sym[s])[1]])
    validated = (not np.isnan(cand_h2["pf"])) and (not np.isnan(curr_h2["pf"])) \
        and cand_h2["pf"] > curr_h2["pf"] and cand_h2["net"] > curr_h2["net"]

    out = REPORTS / f"universe_scan_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Universe scan — {date.today().isoformat()}\n\n")
        f.write(f"{len(rows)} symbols · v2.2 long-only · 2y of 5m bars. Protocol: "
                f"rank by H1 PF (min 25 H1 trades), top-5 basket validated on H2.\n\n")
        f.write(f"**H1 top-5 candidate basket: {', '.join(top5)}**\n\n")
        f.write(f"| basket | H2 trades | H2 net | H2 PF |\n|---|---|---|---|\n")
        f.write(f"| candidate (H1 top-5) | {cand_h2['n']} | {cand_h2['net']} | {cand_h2['pf']} |\n")
        f.write(f"| current (Big Tech 5) | {curr_h2['n']} | {curr_h2['net']} | {curr_h2['pf']} |\n\n")
        f.write(f"**VALIDATED (candidate beats current on H2): "
                f"{'YES' if validated else 'NO'}**\n\n")
        f.write("## All symbols (sorted by H1 PF)\n\n")
        f.write(df.sort_values("H1_pf", ascending=False).to_markdown(index=False) + "\n\n")
        f.write("*Basket changes only on a YES — and even then, the forward test "
                "re-verifies before anything trades it. Not financial advice.*\n")
    print(f"\nCandidate: {top5}  validated: {validated}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
