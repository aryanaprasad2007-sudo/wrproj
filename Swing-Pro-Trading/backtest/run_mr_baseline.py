"""
run_mr_baseline.py — MR-1 baseline: PRE-REGISTERED, frozen 2026-07-05 (Chat C).

Hypothesis: when a healthy large-cap gets briefly oversold inside a long-term
uptrend, it snaps back to its short-term mean within days. Fingerprint source:
regime autopsy 2026-07-01 (below-50d dip-buys were H2's best trades, PF 2.25).

SPEC (literature priors, zero fitting — this file is the registration):
  Universe   the 22 long-history names from run_daily_30y (incl. GE/IBM/INTC)
  Direction  long only
  Regime     close > 200d SMA
  Trigger    RSI(3) < 15 at the close
  Entry      market at next open
  Exit       first close > 10d SMA -> sell next open
  Time stop  10 sessions held, then out at next open
  Stop       disaster only: 3×ATR(14) below signal close
  Sizing     flat 10% of portfolio equity, max 10 concurrent,
             most-oversold (lowest RSI) admitted first
  Costs      0.01%/side commission + 1-tick slippage (matches swing_pro)

BARS (all pre-registered; well = 30y daily yfinance, fresh for the MR family):
  B1  PF > 1.15 in EACH decade (D1 1995-2005, D2 2005-2015, D3 2015-2026)
  B2  >= 500 trades total
  B3  >= 17/22 symbols profitable
  B4  daily-P&L correlation vs SWING_PRO-D (v2.2-D, long-only) < +0.30
  B5  50/50 combined curve MAR >= the better single-system MAR

DECISION TREE (locked before running): all pass -> ADOPTED. PF < 1.0 across
the board -> family BURIED, no rescue-tuning. Marginal (2/3 decades, or PF
1.00-1.15) -> ONE pre-declared 8-cell grid (RSI(2)<10, RSI(3)<10/15/20,
3 or 5 down-closes, exit 5d vs 10d SMA) derived on 1995-2015, single
confirmation shot on 2015-2026. Then stop regardless.

Usage:  py run_mr_baseline.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from mean_rev import MRConfig, run_portfolio, curve_stats
from run_daily_30y import SYMBOLS, fetch_daily
from swing_pro import config_v22, run as sp_run

REPORTS = Path(__file__).parent / "reports"
D1 = pd.Timestamp("2005-01-01")
D2 = pd.Timestamp("2015-01-01")


def era(t):
    ts = pd.Timestamp(t["entry_time"])
    ts = ts.tz_localize(None) if ts.tzinfo else ts
    return "D1" if ts < D1 else ("D2" if ts < D2 else "D3")


def agg(tr):
    p = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    rs = np.array([t["r"] for t in tr if not np.isnan(t.get("r", np.nan))])
    pc = np.array([t["pct"] for t in tr]) if tr else np.array([])
    hb = np.array([t["bars_held"] for t in tr]) if tr else np.array([])
    w, l = (p[p > 0], p[p <= 0]) if len(p) else (np.array([]), np.array([]))
    return {"n": len(p), "net": round(float(p.sum())) if len(p) else 0,
            "exp%": round(float(pc.mean()), 3) if len(pc) else np.nan,
            "expR": round(float(rs.mean()), 3) if len(rs) else np.nan,
            "win%": round(100 * len(w) / len(p), 1) if len(p) else np.nan,
            "avg_hold": round(float(hb.mean()), 1) if len(hb) else np.nan,
            "pf": round(float(w.sum() / -l.sum()), 2)
                  if len(l) and l.sum() < 0 else np.nan}


def main():
    REPORTS.mkdir(exist_ok=True)
    today = date.today().isoformat()
    print("Loading 30y daily bars (cached parquet) ...")
    dfs = {}
    for s in SYMBOLS:
        try:
            dfs[s] = fetch_daily(s)
        except Exception as e:
            print(f"  {s}: FAILED ({e})")
    spy = fetch_daily("SPY")

    # ── MR-1 portfolio run ────────────────────────────────────────────────────
    print(f"Running MR-1 portfolio engine on {len(dfs)} symbols ...")
    cfg = MRConfig()
    res = run_portfolio(dfs, cfg)
    tr = [t for t in res["trades"] if t["reason"] != "end_of_data"]
    eras = {"D1": [], "D2": [], "D3": []}
    for t in tr:
        eras[era(t)].append(t)
    a_full, a1, a2, a3 = agg(tr), agg(eras["D1"]), agg(eras["D2"]), agg(eras["D3"])
    per_sym = []
    for s in sorted(dfs):
        st = [t for t in tr if t["symbol"] == s]
        a = agg(st)
        per_sym.append({"symbol": s, **a})
    reasons = pd.Series([t["reason"] for t in tr]).value_counts().to_dict()
    mr_curve = curve_stats(res["equity"], cfg.initial_capital)

    # ── SWING_PRO-D comparison series (same well, validated flagship config) ──
    print("Recomputing SWING_PRO-D (v2.2-D long-only) for the correlation bar ...")
    sp_cfg = config_v22(trade_dir="long", use_htf_trend=False)
    sp_eqs = {}
    for s, df in dfs.items():
        r = sp_run(df, spy, sp_cfg)
        sp_eqs[s] = pd.Series(r["equity"], index=df.index)
    cal = res["equity"].index
    sp_total = (pd.concat(sp_eqs, axis=1).reindex(cal).ffill()
                .fillna(sp_cfg.initial_capital).sum(axis=1))
    sp_pnl = sp_total.diff().fillna(0.0)
    mr_pnl = res["equity"].diff().fillna(0.0)
    corr = float(np.corrcoef(mr_pnl.to_numpy(), sp_pnl.to_numpy())[0, 1])

    sp_curve = curve_stats(sp_total, float(sp_total.iloc[0]))
    r_mr = res["equity"].pct_change().fillna(0.0)
    r_sp = sp_total.pct_change().fillna(0.0)
    combo = 100.0 * (1.0 + 0.5 * r_mr + 0.5 * r_sp).cumprod()
    combo_curve = curve_stats(combo, 100.0)

    # ── verdict vs the pre-registered bars ───────────────────────────────────
    b1 = all(not np.isnan(a["pf"]) and a["pf"] > 1.15 for a in (a1, a2, a3))
    b2 = a_full["n"] >= 500
    prof = sum(1 for r_ in per_sym if r_["net"] > 0)
    b3 = prof >= 17
    b4 = corr < 0.30
    b5 = (not np.isnan(combo_curve["mar"])
          and combo_curve["mar"] >= max(mr_curve["mar"], sp_curve["mar"]))
    bars = {"B1 PF>1.15 all decades": b1, "B2 n>=500": b2,
            f"B3 >=17/22 profitable (got {prof}/{len(per_sym)})": b3,
            f"B4 corr<0.30 (got {corr:+.3f})": b4,
            f"B5 combo MAR beats both (combo {combo_curve['mar']} vs "
            f"MR {mr_curve['mar']} / SP-D {sp_curve['mar']})": b5}
    decade_pfs = [a["pf"] for a in (a1, a2, a3)]
    if all(bars.values()):
        verdict = "ADOPTED — all pre-registered bars cleared"
    elif all(not np.isnan(pf) and pf < 1.0 for pf in decade_pfs):
        verdict = "BURIED — no edge in any decade; family closed, no rescue-tuning"
    else:
        verdict = ("MARGINAL — decision tree says: run the ONE pre-declared "
                   "8-cell grid (derive 1995-2015, confirm once on 2015-2026)")

    print(f"\nFULL 30y: {a_full}")
    print(f"D1: {a1}\nD2: {a2}\nD3: {a3}")
    print(f"Exit reasons: {reasons} | max concurrent: {res['max_concurrent']}")
    print(f"MR curve: {mr_curve} | SP-D curve: {sp_curve} | 50/50: {combo_curve}")
    for k, v in bars.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"VERDICT: {verdict}")

    out = REPORTS / f"mr_baseline_{today}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# MR-1 baseline — pre-registered one-shot — {today}\n\n")
        f.write("Spec + bars frozen in `run_mr_baseline.py` before the run. "
                "Long-only daily mean reversion: close>200d SMA, RSI(3)<15, "
                "next-open entry, exit first close>10d SMA, 10-session time "
                "stop, 3×ATR disaster stop, flat 10%/max 10 concurrent.\n\n")
        f.write(f"## VERDICT: {verdict}\n\n")
        f.write("| bar | result |\n|---|---|\n")
        for k, v in bars.items():
            f.write(f"| {k} | {'PASS' if v else 'FAIL'} |\n")
        f.write("\n## By era\n\n")
        f.write(pd.DataFrame([{"era": "FULL 30y", **a_full},
                              {"era": "D1 1995-2005", **a1},
                              {"era": "D2 2005-2015", **a2},
                              {"era": "D3 2015-2026", **a3}]).to_markdown(index=False))
        f.write(f"\n\nExit reasons: {reasons} · max concurrent positions: "
                f"{res['max_concurrent']}\n\n")
        f.write("## Curves\n\n")
        f.write(pd.DataFrame([{"curve": "MR-1 portfolio", **mr_curve},
                              {"curve": "SWING_PRO-D aggregate", **sp_curve},
                              {"curve": "50/50 daily-rebalanced", **combo_curve}])
                .to_markdown(index=False))
        f.write(f"\n\nDaily-P&L correlation MR-1 vs SWING_PRO-D: **{corr:+.3f}**\n\n")
        f.write("## Per symbol\n\n" + pd.DataFrame(per_sym).to_markdown(index=False))
        f.write("\n\n*Same caveats as the 30y flagship test: survivors-only "
                "universe, split-adjusted yfinance bars, stops assume fill at "
                "the stop price (gaps can slip). Not financial advice.*\n")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
