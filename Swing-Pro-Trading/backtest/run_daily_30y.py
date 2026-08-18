"""
run_daily_30y.py — SWING_PRO-D across THREE MARKET GENERATIONS (1995-2026).

The decade test validated the daily engine on 2016-2026. This is the deep test:
~30 years of free yfinance daily bars — dot-com bubble AND bust, 2008, the 2010s
bull, COVID, the 2022 bear. Basket = 20 long-history names deliberately
including that era's LOSERS (GE, IBM, INTC) so survivorship can't flatter it.

Pre-registered bar: PF > 1.15 in ALL THREE decades:
  D1 1995-2005 · D2 2005-2015 · D3 2015-2026

Config: identical to the validated decade run — v2.2 exits (pure stop + 3R),
long-only, local daily EMA50 regime, SPY market filter, same 7 gates.
Usage:  py run_daily_30y.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from swing_pro import config_v22, run

SYMBOLS = ["AAPL", "MSFT", "ORCL", "INTC", "IBM", "NVDA", "AMD",
           "JPM", "GS", "XOM", "CVX", "CAT", "DE", "BA",
           "WMT", "COST", "HD", "UNH", "DIS", "KO", "GE", "NKE"]
CACHE = Path(__file__).parent / "cache"
REPORTS = Path(__file__).parent / "reports"
D1 = pd.Timestamp("2005-01-01")
D2 = pd.Timestamp("2015-01-01")


def fetch_daily(sym: str) -> pd.DataFrame:
    f = CACHE / f"{sym}_1dyf_30y.parquet"
    if f.exists():
        return pd.read_parquet(f)
    import yfinance as yf
    df = yf.download(sym, start="1995-01-01", interval="1d", auto_adjust=False,
                     progress=False, multi_level_index=False)
    if df is None or df.empty:
        raise RuntimeError(f"no data for {sym}")
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"])
    df.to_parquet(f)
    return df


def agg(tr):
    p = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    rs = np.array([t["r"] for t in tr if not np.isnan(t.get("r", np.nan))])
    w, l = (p[p > 0], p[p <= 0]) if len(p) else (np.array([]), np.array([]))
    return {"n": len(p), "net": round(float(p.sum())) if len(p) else 0,
            "expR": round(float(rs.mean()), 3) if len(rs) else np.nan,
            "win%": round(100 * len(w) / len(p), 1) if len(p) else np.nan,
            "pf": round(float(w.sum() / -l.sum()), 2)
                  if len(l) and l.sum() < 0 else np.nan}


def era(t):
    ts = pd.Timestamp(t["entry_time"])
    ts = ts.tz_localize(None) if ts.tzinfo else ts
    return "D1" if ts < D1 else ("D2" if ts < D2 else "D3")


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Fetching ~30y of daily bars (yfinance, cached after first run) ...")
    spy = fetch_daily("SPY")
    cfg = config_v22(trade_dir="long", use_htf_trend=False)

    rows, all_tr = [], []
    for s in SYMBOLS:
        try:
            df = fetch_daily(s)
        except Exception as e:
            print(f"  {s}: FAILED ({e})")
            continue
        r = run(df, spy, cfg)
        all_tr += r["trades"]
        st = r["stats"]
        rows.append({"symbol": s, "since": str(df.index[0].date()),
                     "trades": st["trades"], "net": round(st["net_profit"]),
                     "win%": round(st["win_rate"], 1),
                     "pf": round(st["profit_factor"], 2)})
        print(f"  {s}: since {df.index[0].date()}  n={st['trades']} "
              f"net={st['net_profit']:.0f} pf={st['profit_factor']:.2f}")

    eras = {"D1": [], "D2": [], "D3": []}
    for t in all_tr:
        eras[era(t)].append(t)
    a_full = agg(all_tr)
    a1, a2, a3 = agg(eras["D1"]), agg(eras["D2"]), agg(eras["D3"])
    passed = all(not np.isnan(a["pf"]) and a["pf"] > 1.15 for a in (a1, a2, a3))

    print(f"\nFULL 30y: {a_full}")
    print(f"D1 1995-2005: {a1}\nD2 2005-2015: {a2}\nD3 2015-2026: {a3}")
    print(f"VALIDATED (PF>1.15 in ALL THREE decades): {passed}")

    out = REPORTS / f"daily_30y_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# SWING_PRO-D — three-decade deep test — {date.today().isoformat()}\n\n")
        f.write(f"{len(rows)} long-history symbols (incl. era losers GE/IBM/INTC) · "
                f"1995-2026 daily · v2.2-D config · bar: PF > 1.15 in all three "
                f"decades.\n\n**VALIDATED: {'YES' if passed else 'NO'}**\n\n")
        f.write("## By era\n\n")
        f.write(pd.DataFrame([{"era": "FULL 30y", **a_full},
                              {"era": "D1 1995-2005 (dot-com boom+bust)", **a1},
                              {"era": "D2 2005-2015 (2008 crisis + recovery)", **a2},
                              {"era": "D3 2015-2026 (modern era)", **a3}]).to_markdown(index=False) + "\n\n")
        f.write("## Per symbol\n\n" + pd.DataFrame(rows).to_markdown(index=False) + "\n\n")
        f.write("*yfinance split-adjusted daily bars; survivors-only basket (delisted "
                "names absent) — losers GE/IBM/INTC included to blunt that bias. "
                "Overnight gaps can slip stops in reality. Not financial advice.*\n")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
