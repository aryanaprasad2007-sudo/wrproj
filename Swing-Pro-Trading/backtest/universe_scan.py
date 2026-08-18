"""
universe_scan.py -- does the tf=3 edge found on 2026-07-30 generalize to
symbols it was never tuned or tested on?

2026-07-30's holdout sweep found that grouping daily bars into 3-trading-
session bars meaningfully beats raw daily bars, on the fixed 22-symbol basket
in run_daily_30y.SYMBOLS (AAPL MSFT ORCL INTC IBM NVDA AMD JPM GS XOM CVX CAT
DE BA WMT COST HD UNH DIS KO GE NKE). Winning config (reports/
holdout_sweep_2026-07-30.md, reproduced in reports/bootstrap_holdout_2026-07-
31.md): 3-session bars, adx_min=15, rsi_long_level=50, atr_stop_mult=1.5,
rr_ratio=2.0, trade_dir="long", use_htf_trend=False. Holdout (2015-2026) on
that basket: n=210, PF 2.992, t=5.36, breadth 22/22.

A finding that only works on the exact 22 names it was discovered on is much
weaker than one that holds on names never touched by any prior test. This
script runs the identical config, unchanged, on a fresh ~100-symbol universe
that deliberately excludes all 22 original names, over each symbol's full
available history (no train/holdout split needed here -- none of this
universe's data was seen during the 2026-07-30 tuning, so the whole history
is out-of-sample by construction).

Usage:  py universe_scan.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from run_daily_30y import SYMBOLS as ORIGINAL_BASKET
from swing_pro import config_v22, run

CACHE = Path(__file__).parent / "cache"
REPORTS = Path(__file__).parent / "reports"
MIN_BARS = 260          # post-grouping bar count; engine needs ~200+ for its slowest average

# deliberately excludes every symbol in ORIGINAL_BASKET
NEW_UNIVERSE = [
    "BRK-B", "V", "MA", "AXP", "BLK", "SPGI", "MCO", "ICE", "CME", "TRV",
    "PGR", "CB", "MET", "PRU", "AFL", "AIG", "JNJ", "PFE", "MRK", "ABBV",
    "LLY", "TMO", "ABT", "MDT", "BSX", "ISRG", "SYK", "ELV", "CI", "HUM",
    "CVS", "PG", "PEP", "MDLZ", "CL", "KMB", "EL", "TGT", "LOW", "TJX",
    "ROST", "MCD", "SBUX", "YUM", "CMG", "HON", "MMM", "UPS", "FDX", "LMT",
    "RTX", "NOC", "GD", "EMR", "ETN", "ITW", "PH", "ROK", "CSCO", "TXN",
    "QCOM", "ADI", "AMAT", "LRCX", "KLAC", "ADBE", "CRM", "NOW", "INTU",
    "ADP", "PAYX", "SLB", "COP", "EOG", "PSX", "VLO", "MPC", "LIN", "APD",
    "ECL", "NEM", "FCX", "NEE", "DUK", "SO", "D", "AEP", "PLD", "AMT",
    "EQIX", "PSA", "O", "T", "VZ", "CMCSA", "GOOGL", "AMZN", "META", "NFLX",
]
assert not (set(NEW_UNIVERSE) & set(ORIGINAL_BASKET)), "overlap with original basket!"

# reference point from 2026-07-30/31: holdout (2015-2026) on the 22-symbol
# basket the edge was FOUND on
ORIGINAL_HOLDOUT = {"n": 210, "pf": 2.992, "t": 5.36, "expR": 0.6484,
                    "breadth": "22/22", "breadth_pct": 100.0}


def fetch(sym: str, start: str = "1995-01-01") -> pd.DataFrame:
    f = CACHE / f"{sym}_1dyf_uniscan.parquet"
    if f.exists():
        return pd.read_parquet(f)
    import yfinance as yf
    df = yf.download(sym, start=start, interval="1d", auto_adjust=False,
                     progress=False, multi_level_index=False)
    if df is None or df.empty:
        raise RuntimeError("no data")
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"])
    CACHE.mkdir(exist_ok=True)
    df.to_parquet(f)
    return df


def group_bars(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """N consecutive trading sessions per bar -- identical to run_timeframe_scan.py."""
    if n == 1:
        return df
    g = np.arange(len(df)) // n
    out = df.groupby(g).agg({"open": "first", "high": "max", "low": "min",
                             "close": "last", "volume": "sum"})
    out.index = df.index[::n][:len(out)]
    return out


def agg(trades: list) -> dict:
    p = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    rs = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    if not len(p):
        return {"n": 0, "net": 0, "win%": np.nan, "pf": np.nan, "expR": np.nan, "t": np.nan}
    w, l = p[p > 0], p[p <= 0]
    t = (float(rs.mean()) / (float(rs.std(ddof=1)) / np.sqrt(len(rs)))
         if len(rs) > 2 and rs.std(ddof=1) > 0 else np.nan)
    return {"n": len(p), "net": round(float(p.sum())),
            "win%": round(100 * len(w) / len(p), 1),
            "pf": round(float(w.sum() / -l.sum()), 2)
                  if len(l) and l.sum() < 0 else np.nan,
            "expR": round(float(rs.mean()), 3) if len(rs) else np.nan,
            "t": round(t, 2) if t == t else np.nan}


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Fetching SPY (market filter)...")
    spy_d = fetch("SPY")
    spy = group_bars(spy_d, 3)

    cfg = config_v22(trade_dir="long", use_htf_trend=False,
                      adx_min=15, rsi_long_level=50,
                      atr_stop_mult=1.5, rr_ratio=2.0)

    print(f"Fetching + testing {len(NEW_UNIVERSE)} new-universe symbols "
          f"(tf=3, config_v22 overrides)...\n")

    failed, skipped_short = [], []
    per_symbol_rows = []
    all_trades = []
    tested, profitable = 0, 0

    for i, sym in enumerate(NEW_UNIVERSE, 1):
        try:
            df_d = fetch(sym)
        except Exception as e:
            print(f"  [{i}/{len(NEW_UNIVERSE)}] {sym}: FETCH FAILED ({str(e)[:80]})")
            failed.append(sym)
            continue
        df = group_bars(df_d, 3)
        if len(df) < MIN_BARS:
            print(f"  [{i}/{len(NEW_UNIVERSE)}] {sym}: too little history "
                  f"({len(df)} 3-session bars < {MIN_BARS}), skipped")
            skipped_short.append(sym)
            continue
        try:
            r = run(df, spy, cfg)
        except Exception as e:
            print(f"  [{i}/{len(NEW_UNIVERSE)}] {sym}: ENGINE FAILED ({str(e)[:80]})")
            failed.append(sym)
            continue
        tr = [t for t in r["trades"] if t.get("pnl") is not None]
        a = agg(tr)
        tested += 1
        if a["net"] > 0:
            profitable += 1
        all_trades += tr
        per_symbol_rows.append({
            "symbol": sym, "since": str(df_d.index[0].date()),
            "years": round((df_d.index[-1] - df_d.index[0]).days / 365.25, 1),
            **a,
        })
        print(f"  [{i}/{len(NEW_UNIVERSE)}] {sym}: n={a['n']:>4}  pf={a['pf']:>6}  "
              f"win%={a['win%']:>5}  expR={a['expR']:>7}  net=${a['net']:>10,.0f}")

    print(f"\n{tested} symbols tested, {len(failed)} failed to fetch/run, "
          f"{len(skipped_short)} skipped (too little history)")

    # ---- aggregate across the whole new universe ----
    A = agg(all_trades)
    breadth_pct = round(100 * profitable / tested, 1) if tested else np.nan
    A["breadth"] = f"{profitable}/{tested}"
    A["breadth_pct"] = breadth_pct

    print(f"\n=== AGGREGATE, new universe (n={tested} symbols) ===")
    print(A)
    print(f"\n=== reference: original 22-symbol basket, 2015-2026 holdout ===")
    print(ORIGINAL_HOLDOUT)

    generalizes = (not np.isnan(A["pf"]) and A["pf"] > 1.5
                   and not np.isnan(A["t"]) and A["t"] > 2
                   and breadth_pct is not np.nan and breadth_pct >= 60)
    verdict = ("EDGE GENERALIZES" if generalizes else
               "EDGE DOES NOT CLEARLY GENERALIZE")
    print(f"\nVERDICT: {verdict}")

    # ---- top 20 by expectancy (discovery output) ----
    ranked = [r for r in per_symbol_rows if r["n"] >= 10]  # drop noise from tiny samples
    too_few = [r["symbol"] for r in per_symbol_rows if r["n"] < 10]
    ranked.sort(key=lambda r: (r["expR"] if r["expR"] == r["expR"] else -999), reverse=True)
    top20 = ranked[:20]

    # ---- write report ----
    out_md = REPORTS / "universe_scan_2026-07-31.md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# Universe generalization scan -- tf=3 winner on names it was never tuned on -- 2026-07-31\n\n")
        f.write("**Question:** the 2026-07-30 finding (3-trading-session bars beat raw daily "
                "bars) was discovered AND holdout-validated entirely on the fixed 22-symbol "
                "basket in `run_daily_30y.SYMBOLS`. Does the same, unchanged config produce a "
                "real edge on symbols that basket never included?\n\n")
        f.write("**Config (unchanged from the 2026-07-30/31 winner):** 3-trading-session bars, "
                "`adx_min=15, rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0, "
                "trade_dir=\"long\", use_htf_trend=False`.\n\n")
        f.write(f"**New universe:** {len(NEW_UNIVERSE)} large-cap names across financials, "
                "healthcare, staples, industrials, semis/software, energy, materials, utilities, "
                "REITs and telecom/megacap tech -- deliberately excludes all 22 original-basket "
                "symbols. Full available history per symbol (no train/holdout split needed: "
                "none of this data was seen during the original tuning, so the entire history "
                "is out-of-sample by construction).\n\n")
        if failed:
            f.write(f"**Fetch/engine failures ({len(failed)}, skipped):** {', '.join(failed)}\n\n")
        if skipped_short:
            f.write(f"**Skipped, too little history ({len(skipped_short)}):** "
                    f"{', '.join(skipped_short)}\n\n")

        f.write("## Generalization verdict\n\n")
        f.write("| | n | PF | win% | expR | t-stat | breadth |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        f.write(f"| **New universe (this scan)** | {A['n']} | {A['pf']} | {A['win%']} | "
                f"{A['expR']} | {A['t']} | {A['breadth']} ({A['breadth_pct']}%) |\n")
        f.write(f"| Original basket, 2015-2026 holdout (2026-07-30/31) | {ORIGINAL_HOLDOUT['n']} | "
                f"{ORIGINAL_HOLDOUT['pf']} | -- | {ORIGINAL_HOLDOUT['expR']} | "
                f"{ORIGINAL_HOLDOUT['t']} | {ORIGINAL_HOLDOUT['breadth']} "
                f"({ORIGINAL_HOLDOUT['breadth_pct']}%) |\n\n")
        f.write(f"**VERDICT: {verdict}**\n\n")
        f.write("Read `t-stat` and `breadth`, not net PnL or PF alone -- a handful of monster "
                "trades in a ~100-symbol pool can carry PF even if most names are flat or "
                "losing. Threshold used here: PF > 1.5, t > 2, breadth >= 60% counts as "
                "'generalizes'; this is a judgment call, not a statistical law -- read the "
                "actual numbers above rather than trusting the label alone.\n\n")

        f.write("## Per-symbol results (full history, tf=3, config unchanged)\n\n")
        per_symbol_rows.sort(key=lambda r: (r["expR"] if r["expR"] == r["expR"] else -999),
                              reverse=True)
        df_all = pd.DataFrame(per_symbol_rows)
        f.write(df_all.to_markdown(index=False))
        f.write("\n\n")
        if too_few:
            f.write(f"*({len(too_few)} symbols with n<10 trades excluded from the ranking "
                    f"below as too noisy to rank on expectancy: {', '.join(too_few)}. They "
                    f"remain in the per-symbol table above and in the aggregate.)*\n\n")

        f.write("## Top 20 by expectancy (expR) -- discovery watchlist\n\n")
        f.write("New PRI-style candidates: symbols where this config shows the strongest "
                "per-trade edge, worth a closer individual look (liquidity, current setup) "
                "before considering for the live basket -- same spirit as how PRI itself was "
                "found and confirmed on 2026-07-30. Filtered to n>=10 trades.\n\n")
        f.write(pd.DataFrame(top20).to_markdown(index=False))
        f.write("\n\n")
        f.write("*Discovery output, not a validation. Each of these is a single-symbol result "
                "on a 3-session chart; treat like run_symbol_test.py's single-symbol runs -- "
                "informative, not conclusive on its own. No trades were placed, no broker "
                "account touched, and no Pine script or live trading state modified in "
                "producing this report.*\n")

    print(f"\n-> {out_md}")


if __name__ == "__main__":
    main()
