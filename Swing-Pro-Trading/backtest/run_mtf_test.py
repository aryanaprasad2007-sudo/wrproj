"""
run_mtf_test.py — A/B/C test of the "1m engine, 5m view" theory. Long-only.

  A  control    : v2-long on 5m bars (aggregated from the same 1m data)
  B  fills1m    : same 5m signals, exits filled on real 1m bars (resolution only)
  C  trigger1m  : 5m setup gate + 1m entry trigger + 1m structure stops (the theory)

C vs A answers "is the theory right?". C vs B separates entry-timing edge from
mere fill resolution. yfinance caps 1m history at ~30 days — first screen only;
rerun with Alpaca keys for the real verdict.

Usage:  py run_mtf_test.py [--days 29]
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars_1m, resample_5m
from mtf_engine import run_mtf
from swing_pro import config_v2, run

BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]
REPORTS = Path(__file__).parent / "reports"


def agg(results: list[dict]) -> dict:
    tr = [t for r in results for t in r["trades"]]
    pnls = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    rs = np.array([t["r"] for t in tr if not np.isnan(t.get("r", np.nan))])
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls <= 0] if len(pnls) else np.array([])
    risks = np.array([t["risk"] / t["entry_fill"] for t in tr]) if tr else np.array([])
    return {
        "trades": len(tr),
        "net_usd": round(float(pnls.sum()), 0) if len(pnls) else 0.0,
        "exp_R": round(float(rs.mean()), 3) if len(rs) else np.nan,
        "win_%": round(float(len(wins) / len(pnls) * 100), 1) if len(pnls) else np.nan,
        "pf": round(float(wins.sum() / -losses.sum()), 2)
              if len(losses) and losses.sum() < 0 else np.nan,
        "avg_risk_%px": round(float(risks.mean() * 100), 3) if len(risks) else np.nan,
        "syms+": sum(1 for r in results
                     if sum(t["pnl"] for t in r["trades"]) > 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=29)
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    print(f"Loading 1m bars (~{args.days}d): SPY + {', '.join(BASKET)} ...")
    spy1 = load_bars_1m("SPY", args.days)
    bars1 = {s: load_bars_1m(s, args.days) for s in BASKET}
    for s, df in bars1.items():
        print(f"  {s}: {len(df)} 1m bars  {df.index[0].date()} -> {df.index[-1].date()}"
              f"  [{df.attrs.get('source', 'cache')}]")

    cfg = config_v2(trade_dir="long")
    spy5 = resample_5m(spy1)

    variants = {"A_control_5m": None, "B_fills1m": "fills1m", "C_trigger1m": "trigger1m"}
    per_rows, agg_rows = [], []
    for name, mode in variants.items():
        results = []
        for s in BASKET:
            if mode is None:
                r = run(resample_5m(bars1[s]), spy5, cfg)
            else:
                r = run_mtf(bars1[s], spy1, cfg, mode=mode)
            results.append(r)
            st = r["stats"]
            per_rows.append({"variant": name, "symbol": s, "trades": st["trades"],
                             "net_usd": round(st["net_profit"], 0),
                             "exp_R": round(st["expectancy_r"], 3),
                             "win_%": round(st["win_rate"], 1),
                             "pf": round(st["profit_factor"], 2)})
        a = agg(results)
        a["variant"] = name
        agg_rows.append(a)
        print(f"  {name:<14} trades={a['trades']:<4} netUSD={a['net_usd']:>8.0f} "
              f"expR={a['exp_R']:>6.3f} win%={a['win_%']:>5.1f} pf={a['pf']:>5.2f} "
              f"risk%px={a['avg_risk_%px']:>6.3f} syms+={a['syms+']}/5")

    agg_df = pd.DataFrame(agg_rows)[["variant", "trades", "net_usd", "exp_R",
                                     "win_%", "pf", "avg_risk_%px", "syms+"]]
    per_df = pd.DataFrame(per_rows)

    out = REPORTS / f"mtf_test_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# 1m-engine / 5m-view test — {date.today().isoformat()}\n\n")
        f.write(f"Basket: {', '.join(BASKET)} · long-only v2 config · ~{args.days}d of 1m "
                f"bars (yfinance cap) · SPY market ref\n\n")
        f.write("**A** = 5m control · **B** = 5m signals with 1m fills (resolution only) · "
                "**C** = 5m setup + 1m trigger + 1m structure stops (the theory)\n\n")
        f.write("`avg_risk_%px` = average per-share risk as % of entry price — C should be "
                "materially smaller if the tighter-1m-stops mechanism is doing its job.\n\n")
        f.write("## Aggregate\n\n" + agg_df.to_markdown(index=False) + "\n\n")
        f.write("## Per symbol\n\n" + per_df.to_markdown(index=False) + "\n\n")
        f.write("*~1 month of data = first screen, not a verdict. Rerun with Alpaca keys "
                "for multi-month/multi-regime confirmation. Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
