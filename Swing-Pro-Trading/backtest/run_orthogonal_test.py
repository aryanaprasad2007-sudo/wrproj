"""
run_orthogonal_test.py — does FREE orthogonal data (dark-pool + dealer-gamma
footprints) carry the selection edge that OHLCV geometry provably lacks?

Features tagged onto every v2-long trade, all PRIOR-DAY observable:
  dix_high   — SPX dark-pool buying (DIX) above its rolling 60d median
  gex_low    — dealer gamma exposure below its rolling 60d median
  gex_neg    — dealer gamma NEGATIVE (trend-amplifying tape)
  srat_high  — the ticker's own FINRA off-exchange short-ratio above its 20d mean

Protocol (identical to the regime autopsy — single shot, no iteration):
  derive the best gate on H1 (< 2025-07-02) only -> validate untouched on H2.

Usage:  py run_orthogonal_test.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from free_data import load_dix, load_finra_short
from run_regime_autopsy import bucket_table
from swing_pro import config_v2, run

BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]
REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2025-07-02").date()


def main():
    REPORTS.mkdir(exist_ok=True)

    # market-level features (prior-day)
    dg = load_dix()
    m = pd.DataFrame(index=dg.index)
    m["dix_high"] = dg["dix"] > dg["dix"].rolling(60, min_periods=30).median()
    m["gex_low"] = dg["gex"] < dg["gex"].rolling(60, min_periods=30).median()
    m["gex_neg"] = dg["gex"] < 0
    m = m.shift(1)

    # per-ticker FINRA short-ratio feature (prior-day)
    fin = load_finra_short()
    fin["date"] = pd.to_datetime(fin["date"])
    srat = {}
    for s, sub in fin.groupby("symbol"):
        sub = sub.set_index("date").sort_index()
        srat[s] = (sub["short_ratio"] > sub["short_ratio"].rolling(20, min_periods=10).mean()).shift(1)

    print("Tagging v2-long trades with orthogonal features ...")
    spy5 = load_bars("SPY", 730)
    cfg = config_v2(trade_dir="long")
    rows = []
    for s in BASKET:
        r = run(load_bars(s, 730), spy5, cfg)
        for t in r["trades"]:
            d = pd.Timestamp(pd.Timestamp(t["entry_time"]).date())
            row = {"symbol": s, "date": d.date(), "pnl": t["pnl"], "r": t.get("r", np.nan)}
            if d in m.index:
                row.update(m.loc[d].to_dict())
            row["srat_high"] = bool(srat[s].loc[d]) if (s in srat and d in srat[s].index
                                                        and not pd.isna(srat[s].loc[d])) else np.nan
            rows.append(row)
    tr = pd.DataFrame(rows).dropna()
    feats = ["dix_high", "gex_low", "gex_neg", "srat_high"]
    tr[feats] = tr[feats].astype(bool)
    h1, h2 = tr[tr.date < SPLIT], tr[tr.date >= SPLIT]
    print(f"  {len(tr)} tagged trades (H1: {len(h1)}, H2: {len(h2)})")
    if len(h1) < 100 or len(h2) < 100:
        raise SystemExit("ABORT: not enough trades per half - data source fell back "
                         "to a short window? Check that Alpaca keys are visible.")

    t1 = bucket_table(h1, feats)
    best, best_spread = None, 0.0
    for ft in feats:
        a = t1[(t1.feature == ft) & (t1.state == True)]
        b = t1[(t1.feature == ft) & (t1.state == False)]
        if len(a) and len(b) and a.n.iloc[0] >= 40 and b.n.iloc[0] >= 40:
            spread = a.exp_R.iloc[0] - b.exp_R.iloc[0]
            if abs(spread) > abs(best_spread):
                best, best_spread = ft, spread
    best_state = best_spread > 0
    gate = f"{best} == {best_state}"
    print(f"\nH1-derived gate (single shot): TRADE ONLY WHEN {gate} "
          f"(H1 spread {best_spread:+.3f}R)")

    def summarize(sub, label):
        wins = sub.pnl[sub.pnl > 0].sum()
        losses = -sub.pnl[sub.pnl <= 0].sum()
        return {"set": label, "n": len(sub), "net_usd": round(sub.pnl.sum(), 0),
                "exp_R": round(sub.r.mean(), 3),
                "win_%": round((sub.pnl > 0).mean() * 100, 1),
                "pf": round(wins / losses, 2) if losses > 0 else np.inf}

    verdict = pd.DataFrame([
        summarize(h1, "H1 all (derivation)"),
        summarize(h1[h1[best] == best_state], "H1 gated"),
        summarize(h2, "H2 all (validation)"),
        summarize(h2[h2[best] == best_state], "H2 GATED  <- verdict"),
        summarize(h2[h2[best] != best_state], "H2 blocked"),
    ])
    t2 = bucket_table(h2, feats)
    print("\n== H2 validation ==")
    print(verdict.to_string(index=False))

    out = REPORTS / f"orthogonal_test_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Free orthogonal-data test — {date.today().isoformat()}\n\n")
        f.write(f"{len(tr)} v2-long trades tagged with prior-day DIX / GEX / FINRA "
                f"short-ratio features. Same single-shot H1→H2 protocol as the regime "
                f"autopsy.\n\n**Gate derived on H1: `{gate}`** (spread {best_spread:+.3f}R)\n\n")
        f.write("## Verdict\n\n" + verdict.to_markdown(index=False) + "\n\n")
        f.write("## H1 buckets (derivation)\n\n" + t1.to_markdown(index=False) + "\n\n")
        f.write("## H2 buckets (reference, post-hoc)\n\n" + t2.to_markdown(index=False) + "\n\n")
        f.write("*Data: SqueezeMetrics DIX/GEX (free), FINRA daily short volume (free). "
                "If this fails too, daily-granularity orthogonal data is insufficient and "
                "the next test needs intraday flow. Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
