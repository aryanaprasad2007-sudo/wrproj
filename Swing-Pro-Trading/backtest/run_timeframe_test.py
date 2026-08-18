"""
run_timeframe_test.py — is a LONGER chart timeframe genuinely better, or does it
just produce fewer trades and therefore luckier-looking numbers?

The question is legitimate: iAPE_v4 already carries a validated-timeframe table
(daily VALIDATED, 5-min VALIDATED, 1-min REJECTED, 1-hour FAILED), so "does
weekly beat daily?" is a fair thing to ask. What it cannot be answered with is
one symbol -- PRI weekly shows PF 2.9 on SIX trades, and at n=6 the confidence
interval swallows almost any conclusion.

So this runs the SAME validated engine (config_v22, long-only, use_htf_trend
=False, pure stop + 3R) over the SAME 22-symbol basket used by the 30-year deep
test, resampling daily bars to each candidate timeframe. SPY is resampled
identically so the market filter stays honest.

The decisive column is not aggregate profit factor -- a single monster trade can
carry that. It is BREADTH: how many of the 22 symbols are individually
profitable. An edge shows up across the basket. Luck concentrates in one name.

Usage:
    py run_timeframe_test.py
    py run_timeframe_test.py --tfs 1D 1W 2W 3W 1M
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from run_daily_30y import SYMBOLS, fetch_daily
from swing_pro import config_v22, run

REPORTS = Path(__file__).parent / "reports"
# pandas resample rules. Weekly bars close Friday to match how a chart draws them.
RULES = {"1D": None, "1W": "W-FRI", "2W": "2W-FRI", "3W": "3W-FRI", "1M": "ME"}
MIN_BARS = 260          # engine needs ~200+ for its slowest average to be valid


def resample(df: pd.DataFrame, rule: str | None) -> pd.DataFrame:
    if rule is None:
        return df
    out = df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"})
    return out.dropna(subset=["open", "high", "low", "close"])


def agg(trades: list) -> dict:
    p = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    rs = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    if not len(p):
        return {"trades": 0, "win%": np.nan, "pf": np.nan, "expR": np.nan,
                "net": 0}
    w, l = p[p > 0], p[p <= 0]
    return {"trades": len(p), "win%": round(100 * len(w) / len(p), 1),
            "pf": round(float(w.sum() / -l.sum()), 2)
                  if len(l) and l.sum() < 0 else np.nan,
            "expR": round(float(rs.mean()), 3) if len(rs) else np.nan,
            "net": round(float(p.sum()))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfs", nargs="+", default=["1D", "1W", "2W", "3W", "1M"])
    a = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    print("Loading 30y daily bars (cached after first run)...")
    spy_d = fetch_daily("SPY")
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = fetch_daily(s)
        except Exception as e:
            print(f"  {s}: skipped ({str(e)[:60]})")
    print(f"{len(data)} symbols loaded\n")

    cfg = config_v22(trade_dir="long", use_htf_trend=False)
    rows = []
    for tf in a.tfs:
        rule = RULES.get(tf)
        spy = resample(spy_d, rule)
        all_tr, profitable, tested, per_sym = [], 0, 0, []
        for sym, df_d in data.items():
            df = resample(df_d, rule)
            if len(df) < MIN_BARS:
                continue
            try:
                r = run(df, spy, cfg)
            except Exception:
                continue
            tr = [t for t in r["trades"] if t.get("pnl") is not None]
            tested += 1
            all_tr += tr
            net = sum(t["pnl"] for t in tr)
            per_sym.append((sym, len(tr), round(net)))
            if net > 0:
                profitable += 1
        A = agg(all_tr)
        breadth = f"{profitable}/{tested}"
        rows.append({"timeframe": tf, **A, "symbols_profitable": breadth,
                     "breadth%": round(100 * profitable / tested, 1) if tested else np.nan,
                     "trades_per_symbol": round(A["trades"] / tested, 1) if tested else np.nan})
        print(f"{tf:>4}  trades {A['trades']:>5}  ({rows[-1]['trades_per_symbol']:>5}/symbol)  "
              f"win {A['win%']}%  PF {A['pf']}  expR {A['expR']}  "
              f"breadth {breadth} ({rows[-1]['breadth%']}%)")

    out = pd.DataFrame(rows)
    print("\n" + out.to_string(index=False))

    f = REPORTS / f"timeframe_test_{date.today().isoformat()}.md"
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(f"# Timeframe test — does a longer chart actually help? — {date.today()}\n\n")
        fh.write("Same engine + config as the 30-year deep test (config_v22, long-only, "
                 "use_htf_trend=False), same 22-symbol basket, daily bars resampled to each "
                 "timeframe. SPY resampled identically so the market filter stays honest.\n\n")
        fh.write("**Read BREADTH, not profit factor.** Aggregate PF can be carried by one "
                 "monster trade; breadth (how many of the 22 symbols are individually "
                 "profitable) cannot. Longer timeframes mechanically produce fewer trades, "
                 "and fewer trades produce more extreme numbers in BOTH directions — that is "
                 "variance, not edge.\n\n")
        fh.write(out.to_markdown(index=False))
        fh.write("\n")
    print(f"\n-> {f}")


if __name__ == "__main__":
    main()
