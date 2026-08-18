"""
run_walkforward.py — the referee. Out-of-sample regime-slice test of v1 vs v2.

v2 was derived from ONE window (2026-04-08 → 2026-07-01). The question that
decides everything: does v2-long's edge persist on data it has never seen?

Method: load ~2 years of 5m Alpaca SIP bars, cut history into sequential 60-day
slices, run each config on every slice independently (with a 21-day indicator
warm-up prepended; only trades ENTERED inside the slice count). Slices that
overlap the v2 derivation window are flagged IN-SAMPLE and excluded from the
out-of-sample verdict.

Read the OOS summary line first: % of slices profitable + aggregate PF.
A real edge is boringly repeatable; a curve-fit one has one great quarter.

Usage:  py run_walkforward.py [--days 730] [--slice 60] [--dir long]
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
IS_START = pd.Timestamp("2026-04-08", tz="America/New_York")   # v2 derivation window
IS_END = pd.Timestamp("2026-07-01", tz="America/New_York")
WARMUP = pd.Timedelta(days=21)


def slice_trades(df, spy, cfg, s, e):
    sub = df[(df.index >= s - WARMUP) & (df.index < e)]
    if len(sub) < 500:
        return []
    r = run(sub, spy, cfg)
    return [t for t in r["trades"]
            if pd.Timestamp(t["entry_time"]) >= s]


def tstats(tr):
    pnls = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    rs = np.array([t["r"] for t in tr if not np.isnan(t.get("r", np.nan))])
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls <= 0] if len(pnls) else np.array([])
    return {
        "trades": len(pnls),
        "net_usd": round(float(pnls.sum()), 0) if len(pnls) else 0.0,
        "exp_R": round(float(rs.mean()), 3) if len(rs) else np.nan,
        "win_%": round(float(len(wins) / len(pnls) * 100), 1) if len(pnls) else np.nan,
        "pf": round(float(wins.sum() / -losses.sum()), 2)
              if len(losses) and losses.sum() < 0 else (np.inf if len(wins) else np.nan),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--slice", type=int, default=60)
    ap.add_argument("--dir", default="long", choices=["long", "short", "both"])
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    print(f"Loading {args.days}d of 5m bars: SPY + {', '.join(BASKET)} ...")
    spy = load_bars("SPY", args.days)
    bars = {s: load_bars(s, args.days) for s in BASKET}
    lo = max(df.index[0] for df in bars.values())
    hi = min(df.index[-1] for df in bars.values())
    print(f"  common range {lo.date()} -> {hi.date()}  "
          f"[{bars['AAPL'].attrs.get('source', 'cache')}]")

    cfgs = {"v1_long": Config(trade_dir=args.dir),
            "v2_long": config_v2(trade_dir=args.dir)}

    edges = pd.date_range(lo + WARMUP, hi, freq=f"{args.slice}D")
    rows = []
    for cname, cfg in cfgs.items():
        for j in range(len(edges) - 1):
            s, e = edges[j], edges[j + 1]
            tr = []
            for sym in BASKET:
                tr += slice_trades(bars[sym], spy, cfg, s, e)
            st = tstats(tr)
            st["config"] = cname
            st["slice"] = f"{s.date()} → {e.date()}"
            st["sample"] = "IN-SAMPLE" if (s < IS_END and e > IS_START) else "oos"
            rows.append(st)
            print(f"  {cname:<8} {st['slice']}  {st['sample']:<9} "
                  f"trades={st['trades']:<4} net={st['net_usd']:>8.0f} "
                  f"expR={st['exp_R']:>6} pf={st['pf']}")

    df = pd.DataFrame(rows)[["config", "slice", "sample", "trades", "net_usd",
                             "exp_R", "win_%", "pf"]]

    # OOS verdict per config
    verdicts = []
    for cname in cfgs:
        oos = df[(df.config == cname) & (df["sample"] == "oos") & (df.trades > 0)]
        v = {
            "config": cname,
            "oos_slices": len(oos),
            "slices_profitable": f"{int((oos.net_usd > 0).sum())}/{len(oos)}",
            "oos_net_usd": round(float(oos.net_usd.sum()), 0),
            "oos_trades": int(oos.trades.sum()),
            "median_slice_pf": round(float(oos.pf.replace(np.inf, np.nan).median()), 2),
            "mean_exp_R": round(float((oos.exp_R * oos.trades).sum() / oos.trades.sum()), 3)
                          if oos.trades.sum() else np.nan,
        }
        verdicts.append(v)
    vdf = pd.DataFrame(verdicts)

    out = REPORTS / f"walkforward_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Walk-forward slice test — {date.today().isoformat()}\n\n")
        f.write(f"Basket: {', '.join(BASKET)} · 5m Alpaca SIP · {args.slice}-day slices · "
                f"direction={args.dir}\n\n")
        f.write("v2 was DERIVED on 2026-04-08 → 2026-07-01; slices overlapping that "
                "window are flagged IN-SAMPLE and excluded from the verdict.\n\n")
        f.write("## Out-of-sample verdict\n\n" + vdf.to_markdown(index=False) + "\n\n")
        f.write("## Every slice\n\n" + df.to_markdown(index=False) + "\n\n")
        f.write("*A real edge is boringly repeatable across slices; a curve-fit one has "
                "one great quarter. Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
