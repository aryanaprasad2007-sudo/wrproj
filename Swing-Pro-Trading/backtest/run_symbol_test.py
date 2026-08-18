"""
run_symbol_test.py — does the live daily engine actually work on THIS symbol?

Before pointing the Robinhood desk at a name that is not in the validated
universe, run it through the same engine, same config, over its full history.
The 30y validation (PF 1.47/2.03/2.45 by decade, 1,090 trades) and the daily
track's PF 1.72 benchmark were measured on SPECIFIC baskets. A name outside
them is out-of-sample, and "the engine is validated" does not transfer to it
by assertion -- it has to be measured.

Config is identical to the live daily track: config_v22(trade_dir="long",
use_htf_trend=False) -- v2.2 exits (pure stop + 3R), SPY market filter, the
same 7 gates. Data is free yfinance daily bars, cached in cache/.

Split is chronological halves (H1/H2). This is ONE symbol's history, so treat
it as a sanity check, not a validation: single-name samples are small, the
portfolio logic (concurrency cap, most-oversold priority) does nothing at n=1,
and a good-looking half on 30-50 trades is well within noise.

Usage:
    py run_symbol_test.py PRI
    py run_symbol_test.py PRI KO JPM --start 2010-01-01
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from swing_pro import config_v22, run

CACHE = Path(__file__).parent / "cache"
REPORTS = Path(__file__).parent / "reports"


def fetch(sym: str, start: str) -> pd.DataFrame:
    f = CACHE / f"{sym}_1dyf_symtest.parquet"
    if f.exists():
        df = pd.read_parquet(f)
        if str(df.index[0].date()) <= start or len(df) > 200:
            return df
    import yfinance as yf
    df = yf.download(sym, start=start, interval="1d", auto_adjust=False,
                     progress=False, multi_level_index=False)
    if df is None or df.empty:
        raise RuntimeError(f"no data for {sym}")
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"])
    CACHE.mkdir(exist_ok=True)
    df.to_parquet(f)
    return df


def agg(tr):
    p = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    rs = np.array([t["r"] for t in tr if not np.isnan(t.get("r", np.nan))])
    if not len(p):
        return {"n": 0, "net": 0, "win%": np.nan, "pf": np.nan, "expR": np.nan}
    w, l = p[p > 0], p[p <= 0]
    return {"n": len(p), "net": round(float(p.sum())),
            "win%": round(100 * len(w) / len(p), 1),
            "pf": round(float(w.sum() / -l.sum()), 2)
                  if len(l) and l.sum() < 0 else np.nan,
            "expR": round(float(rs.mean()), 3) if len(rs) else np.nan}


def liquidity(df: pd.DataFrame) -> dict:
    v, px = df["volume"].tail(60), df["close"].tail(60)
    return {"px": round(float(px.iloc[-1]), 2),
            "vol60d": int(v.mean()),
            "dollar_vol_m": round(float((v * px).mean()) / 1e6, 1),
            "range_pct": round(float(((df["high"] - df["low"]) / df["close"])
                                     .tail(60).mean() * 100), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--start", default="1995-01-01")
    a = ap.parse_args()

    REPORTS.mkdir(exist_ok=True)
    spy = fetch("SPY", a.start)
    cfg = config_v22(trade_dir="long", use_htf_trend=False)

    rows = []
    for sym in [s.upper() for s in a.symbols]:
        try:
            df = fetch(sym, a.start)
        except Exception as e:
            print(f"{sym}: FAILED ({e})")
            continue
        r = run(df, spy, cfg)
        tr = [t for t in r["trades"] if t.get("pnl") is not None]
        mid = df.index[len(df) // 2]

        def half(keep):
            out = []
            for t in tr:
                ts = pd.Timestamp(t["entry_time"])
                ts = ts.tz_localize(None) if ts.tzinfo else ts
                if keep(ts):
                    out.append(t)
            return out

        full = agg(tr)
        h1, h2 = agg(half(lambda x: x < mid)), agg(half(lambda x: x >= mid))
        liq = liquidity(df)
        yrs = (df.index[-1] - df.index[0]).days / 365.25
        rows.append({"symbol": sym, "since": str(df.index[0].date()),
                     "years": round(yrs, 1),
                     "trades_per_yr": round(full["n"] / yrs, 2) if yrs else np.nan,
                     **{f"full_{k}": v for k, v in full.items()},
                     **{f"h1_{k}": v for k, v in h1.items()},
                     **{f"h2_{k}": v for k, v in h2.items()}, **liq})
        print(f"\n{sym}  since {df.index[0].date()} ({yrs:.1f}y)  "
              f"${liq['px']:,.2f}  ~${liq['dollar_vol_m']}M/day")
        print(f"  FULL {full}")
        print(f"  H1   {h1}")
        print(f"  H2   {h2}")
        print(f"  -> {full['n'] / yrs:.2f} trades/year "
              f"({full['n'] / yrs / 52:.3f}/week)")

    if not rows:
        return
    out = REPORTS / f"symbol_test_{'_'.join(r['symbol'] for r in rows)}_{date.today()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Single-symbol test — live daily config — {date.today()}\n\n")
        f.write("Engine + config identical to the live daily track "
                "(config_v22, long-only, use_htf_trend=False, pure stop + 3R). "
                "yfinance daily bars.\n\n")
        f.write("**Read this as a sanity check, not a validation.** One symbol "
                "is a small sample, the portfolio logic does nothing at n=1, "
                "and the registered PF 1.72 benchmark belongs to the 13-name "
                "control basket, not to any single name.\n\n")
        f.write(pd.DataFrame(rows).to_markdown(index=False))
        f.write("\n")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
