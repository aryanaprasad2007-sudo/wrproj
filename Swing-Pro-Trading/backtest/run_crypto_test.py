"""
run_crypto_test.py — does the VALIDATED stock engine generalize to crypto?

A PRE-REGISTERED out-of-sample generalization test (NOT tuning). It runs the
exact live engine — config_v22(use_htf_trend=False, long-only, pure stop + 3R) —
completely unchanged, on 24/7 crypto bars from Alpaca. The daily run (2026-07-09)
FAILED on a thin 96-trade sample; this adds an intraday timeframe for a
large-sample, statistically decisive read.

WHY THIS IS USEFUL FOR STOCKS (Ari's caveat): if the same 7-gate momentum engine
shows an edge on a totally different asset class AT SCALE, that's robustness
evidence it captures real momentum structure, not an equity curve-fit. If it
fails at scale too, that's a decisive humility check on the stock engine. Crypto
is a fast-clock generalization testbed — NOT a source of stock parameters.

Pre-registration — fixed BEFORE the run:
  * universe   : BTC ETH SOL LTC DOGE LINK BCH UNI
  * market gate: BTC vs its 50-period EMA (crypto-beta regime, SPY analog)
  * costs      : REALISTIC crypto taker fee (--commission %/side; 0.15 default
                 for intraday) — decisive at high trade counts, unlike the
                 engine's 1bp equity default.
  * split      : H1 = start → --split, H2 = --split → now
  * PASS bar   : basket PF > 1.15 in BOTH halves (the project's standing bar)
  * one run per timeframe, reporting only. Engine logic is NOT touched.

Bars are cached to cache/crypto/ so re-runs are instant.

Usage: py run_crypto_test.py [--timeframe 1Hour] [--commission 0.15]
                             [--start 2021-01-01] [--split 2023-09-01]
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import _env
from swing_pro import config_v22, run

HERE = Path(__file__).parent
REPORTS = HERE / "reports"
CACHE = HERE / "cache" / "crypto"
UNIVERSE = ["BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD",
            "DOGE/USD", "LINK/USD", "BCH/USD", "UNI/USD"]
BASE = "https://data.alpaca.markets/v1beta3/crypto/us/bars"


def crypto_bars(sym, timeframe, start, refresh=False):
    """Daily/intraday crypto OHLCV, paginated + cached to parquet, tz-aware (NY).
    Crypto is 24/7 so there is no RTH filtering. Pages cap at ~1 week regardless
    of limit, so long histories are many requests — the cache pays for itself."""
    CACHE.mkdir(parents=True, exist_ok=True)
    fn = CACHE / f"{sym.replace('/', '-')}_{timeframe}_{start}.parquet"
    if fn.exists() and not refresh:
        return pd.read_parquet(fn)
    rows, page = [], None
    while True:
        q = {"symbols": sym, "timeframe": timeframe, "start": start, "limit": 10000}
        if page:
            q["page_token"] = page
        req = urllib.request.Request(BASE + "?" + urllib.parse.urlencode(q), headers={
            "APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
            "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY")})
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode())
        rows += d.get("bars", {}).get(sym, [])
        page = d.get("next_page_token")
        if not page:
            break
    df = pd.DataFrame(rows).rename(columns={"t": "time", "o": "open", "h": "high",
                                            "l": "low", "c": "close", "v": "volume"})
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/New_York")
    df = df.set_index("time")[["open", "high", "low", "close", "volume"]]
    df.to_parquet(fn)
    return df


def pf(pnls):
    w = sum(p for p in pnls if p > 0)
    l = -sum(p for p in pnls if p <= 0)
    return (w / l) if l > 0 else (float("inf") if w > 0 else float("nan"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1Day")
    ap.add_argument("--commission", type=float, default=None,
                    help="%%/side taker fee; default 0.15 for intraday, engine default for daily")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--split", default="2023-09-01")
    a = ap.parse_args()
    intraday = a.timeframe != "1Day"
    comm = a.commission if a.commission is not None else (0.15 if intraday else 0.01)

    REPORTS.mkdir(exist_ok=True)
    cfg = config_v22(trade_dir="long", use_htf_trend=False,
                     initial_capital=2000, qty_pct_equity=10, commission_pct=comm)

    def which(ts):
        return "H1" if str(ts)[:10] < a.split else "H2"

    print(f"[{a.timeframe}] fetching BTC market proxy (cached)…")
    btc = crypto_bars("BTC/USD", a.timeframe, a.start)

    per_sym, agg = [], {"H1": [], "H2": []}
    for sym in UNIVERSE:
        try:
            df = crypto_bars(sym, a.timeframe, a.start)
        except Exception as e:
            print(f"  {sym}: fetch failed — {str(e)[:60]}")
            continue
        res = run(df, btc, cfg)
        h = {"H1": [], "H2": []}
        for t in res["trades"]:
            if t.get("pnl") is not None:
                h[which(t["entry_time"])].append(t["pnl"])
        agg["H1"] += h["H1"]; agg["H2"] += h["H2"]
        allp = h["H1"] + h["H2"]
        per_sym.append({"sym": sym, "n": len(allp), "pf_h1": pf(h["H1"]),
                        "pf_h2": pf(h["H2"]), "pf": pf(allp), "net": sum(allp),
                        "bars": len(df)})
        print(f"  {sym:<9} bars={len(df):>6} n={len(allp):>4}  "
              f"PF H1 {pf(h['H1']):>5.2f} / H2 {pf(h['H2']):>5.2f}  "
              f"full {pf(allp):>5.2f}  net ${sum(allp):>9,.0f}")

    pf_h1, pf_h2 = pf(agg["H1"]), pf(agg["H2"])
    pf_all = pf(agg["H1"] + agg["H2"])
    n_all = len(agg["H1"]) + len(agg["H2"])
    both_pass = (pf_h1 > 1.15) and (pf_h2 > 1.15)
    consistent = sum(1 for s in per_sym if s["pf_h1"] > 1.0 and s["pf_h2"] > 1.0)
    verdict = "GENERALIZES" if both_pass else "DOES NOT GENERALIZE (as-is)"

    print(f"\nBASKET  n={n_all}  PF H1 {pf_h1:.2f} / H2 {pf_h2:.2f}  full {pf_all:.2f}  "
          f"(commission {comm}%/side)")
    print(f"Both-halves >1.15: {'PASS' if both_pass else 'FAIL'} -> {verdict}  "
          f"· both-halves-positive symbols {consistent}/{len(per_sym)}")

    tag = a.timeframe.lower()
    out = REPORTS / f"crypto_test_{tag}_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Crypto generalization test ({a.timeframe}) — {date.today().isoformat()}\n\n")
        f.write(f"Pre-registered OOS test of the UNCHANGED engine (config_v22, "
                f"use_htf_trend=False, long-only, pure stop + 3R) on {a.timeframe} "
                f"crypto bars, {a.start}→now, realistic **{comm}%/side** taker fee.\n\n")
        f.write(f"## Verdict: {verdict}\n\n")
        f.write(f"Basket PF **H1 {pf_h1:.2f} / H2 {pf_h2:.2f}** (full {pf_all:.2f}, "
                f"**{n_all} trades** — large sample). Bar = PF>1.15 both halves → "
                f"**{'PASS' if both_pass else 'FAIL'}**. Both-halves-positive: "
                f"{consistent}/{len(per_sym)}.\n\n")
        f.write("| symbol | bars | trades | PF H1 | PF H2 | PF full | net (2k) |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for s in per_sym:
            f.write(f"| {s['sym']} | {s['bars']} | {s['n']} | {s['pf_h1']:.2f} | "
                    f"{s['pf_h2']:.2f} | {s['pf']:.2f} | ${s['net']:,.0f} |\n")
        f.write(f"\nCosts are decisive at this trade count: {comm}%/side = "
                f"{2*comm:.2f}% round-trip. Crypto is one correlated beta (all names "
                f"track BTC). Not financial advice.\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
