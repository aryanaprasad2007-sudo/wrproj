"""
run_timeframe_scan.py — scan chart timeframes for the one that maximises the
backtest, WITH the statistics that say whether the winner is real.

Ari's question: which timeframe gives the highest theoretical PnL? Answered
here honestly, which means reporting three things next to the PnL:

  n        trades. As the timeframe lengthens, n collapses. PF on n=3 is a
           coin-flip dressed as a finding.
  t-stat   mean(R) / (std(R)/sqrt(n)). This is the number that says whether an
           edge is distinguishable from zero. |t| > 2 is the usual "probably
           not luck" line. It PENALISES small samples automatically, which is
           exactly what raw PnL and profit factor fail to do.
  breadth  how many of the 22 symbols are individually profitable. An edge
           shows up across the basket; luck concentrates in one name.

Read the t-stat column, not the net column. Picking the timeframe with the
biggest PnL is how you select the luckiest sample; picking the one with the
best t-stat is how you select the most reliable one. They are usually not the
same timeframe, and the gap between them is the whole lesson.

SCOPE LIMIT — this cannot scan below 1 day. The 30-year dataset is DAILY bars;
resampling only ever goes coarser. Testing minutes/hours needs intraday history,
and the 2-year intraday well is retired (house rule 1). Timeframes are built by
grouping N consecutive TRADING bars, so they never straddle weekends unevenly:
1D=1, 1W=5, 1M=21 sessions, etc.

Usage:  py run_timeframe_scan.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from run_daily_30y import SYMBOLS, fetch_daily
from swing_pro import config_v22, run

REPORTS = Path(__file__).parent / "reports"
MIN_BARS = 260

# label -> trading sessions per bar
GRID = [("1D", 1), ("2D", 2), ("3D", 3), ("1W", 5), ("2W", 10), ("3W", 15),
        ("1M", 21), ("2M", 42), ("3M", 63), ("6M", 126)]


def group_bars(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """N consecutive trading sessions per bar (what an N-session chart draws)."""
    if n == 1:
        return df
    g = np.arange(len(df)) // n
    out = df.groupby(g).agg({"open": "first", "high": "max", "low": "min",
                             "close": "last", "volume": "sum"})
    out.index = df.index[::n][:len(out)]
    return out


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Loading 30y daily bars (cached)...")
    spy_d = fetch_daily("SPY")
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = fetch_daily(s)
        except Exception:
            pass
    print(f"{len(data)} symbols\n")

    cfg = config_v22(trade_dir="long", use_htf_trend=False)
    rows = []
    for label, n in GRID:
        spy = group_bars(spy_d, n)
        pnls, rs, tested, profitable = [], [], 0, 0
        for sym, df_d in data.items():
            df = group_bars(df_d, n)
            if len(df) < MIN_BARS:
                continue
            try:
                r = run(df, spy, cfg)
            except Exception:
                continue
            tr = [t for t in r["trades"] if t.get("pnl") is not None]
            tested += 1
            net = sum(t["pnl"] for t in tr)
            if net > 0:
                profitable += 1
            pnls += [t["pnl"] for t in tr]
            rs += [t["r"] for t in tr if not np.isnan(t.get("r", np.nan))]
        p, R = np.array(pnls), np.array(rs)
        if not len(p):
            continue
        w, l = p[p > 0], p[p <= 0]
        pf = float(w.sum() / -l.sum()) if len(l) and l.sum() < 0 else np.nan
        # the decisive statistic: is expectancy distinguishable from zero?
        t = (float(R.mean()) / (float(R.std(ddof=1)) / np.sqrt(len(R)))
             if len(R) > 2 and R.std(ddof=1) > 0 else np.nan)
        rows.append({
            "tf": label, "sessions/bar": n, "trades": len(p),
            "per_symbol": round(len(p) / tested, 1) if tested else np.nan,
            "win%": round(100 * len(w) / len(p), 1),
            "pf": round(pf, 2), "expR": round(float(R.mean()), 3) if len(R) else np.nan,
            "t_stat": round(t, 2) if t == t else np.nan,
            "net$": round(float(p.sum())),
            "breadth": f"{profitable}/{tested}",
            "breadth%": round(100 * profitable / tested, 1) if tested else np.nan,
        })
        print(f"{label:>3} ({n:>3} sess/bar)  n={len(p):>5}  win {rows[-1]['win%']:>5}%  "
              f"PF {rows[-1]['pf']:>6}  expR {rows[-1]['expR']:>6}  "
              f"t={rows[-1]['t_stat']:>6}  net ${rows[-1]['net$']:>9,}  "
              f"breadth {rows[-1]['breadth']}")

    out = pd.DataFrame(rows)
    best_net = out.loc[out["net$"].idxmax()]
    best_t = out.loc[out["t_stat"].idxmax()]
    best_pf = out.loc[out["pf"].idxmax()]
    print("\n" + out.to_string(index=False))
    print(f"\nHighest NET PnL      : {best_net['tf']}  (${best_net['net$']:,}, "
          f"n={best_net['trades']}, t={best_net['t_stat']})")
    print(f"Highest PROFIT FACTOR: {best_pf['tf']}  (PF {best_pf['pf']}, "
          f"n={best_pf['trades']}, t={best_pf['t_stat']})")
    print(f"Most RELIABLE (t-stat): {best_t['tf']}  (t={best_t['t_stat']}, "
          f"n={best_t['trades']}, PF {best_t['pf']})")

    f = REPORTS / f"timeframe_scan_{date.today().isoformat()}.md"
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(f"# Timeframe scan — {date.today()}\n\n")
        fh.write("Same engine/config as the 30y deep test, 22-symbol basket, daily bars "
                 "grouped into N-session bars. **Cannot scan below 1 day** — the dataset is "
                 "daily and resampling only goes coarser.\n\n")
        fh.write("**Read `t_stat`, not `net$`.** t = mean(R)/(std(R)/sqrt(n)) — it asks "
                 "whether expectancy is distinguishable from zero, and it penalises small "
                 "samples automatically. Raw PnL and profit factor do not: both rise as the "
                 "sample shrinks, because fewer trades means more extreme outcomes in BOTH "
                 "directions. Choosing the timeframe with the biggest PnL is choosing the "
                 "luckiest sample.\n\n")
        fh.write(out.to_markdown(index=False))
        fh.write(f"\n\n- Highest net PnL: **{best_net['tf']}** (n={best_net['trades']}, "
                 f"t={best_net['t_stat']})\n")
        fh.write(f"- Highest profit factor: **{best_pf['tf']}** (n={best_pf['trades']}, "
                 f"t={best_pf['t_stat']})\n")
        fh.write(f"- Most statistically reliable: **{best_t['tf']}** "
                 f"(t={best_t['t_stat']}, n={best_t['trades']})\n")
    print(f"\n-> {f}")


if __name__ == "__main__":
    main()
