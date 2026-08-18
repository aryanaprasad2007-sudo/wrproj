"""
run_regime_autopsy.py — WHEN does the system win?

The walk-forward showed v1/v2 have ~zero OOS edge overall, but the winning
slices clustered (Nov'24–May'25, Sep'25–Jan'26). If a prior-day-observable
market regime separates the winning tape from the losing tape, gating entries
on it is a legitimate conditioning filter — IF it survives honest validation.

Anti-curve-fit protocol (single shot, pre-registered):
  1. Run v2-long over 2y, tag every trade with PRIOR-DAY regime features
     (no lookahead: all features shifted one full day).
  2. Bucket trades per feature on H1 ONLY (first year). Pick the single feature
     with the largest expectancy spread (min 40 trades per side).
  3. Apply that one gate, untouched, to H2 (second year). Report. No iteration.

Usage:  py run_regime_autopsy.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import config_v2, run

BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]
REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2025-07-02").date()


def daily(df5: pd.DataFrame) -> pd.DataFrame:
    g = df5.groupby(df5.index.tz_localize(None).normalize())
    return pd.DataFrame({"close": g["close"].last(), "high": g["high"].max()})


def regime_features(spy_d: pd.DataFrame, sym_d: pd.DataFrame) -> pd.DataFrame:
    """All features observable at the PRIOR day's close (shift(1) at the end)."""
    f = pd.DataFrame(index=spy_d.index)
    c = spy_d["close"]
    sma50 = c.rolling(50).mean()
    ret = c.pct_change()
    rv20 = ret.rolling(20).std() * np.sqrt(252) * 100
    f["spy_above_50d"] = c > sma50
    f["spy_50d_rising"] = sma50 > sma50.shift(5)
    f["spy_near_20d_high"] = c >= 0.97 * c.rolling(20).max()
    f["spy_5d_ret_pos"] = c.pct_change(5) > 0
    f["vol_calm"] = rv20 < rv20.rolling(100, min_periods=50).median()
    sc = sym_d["close"].reindex(f.index).ffill()
    f["sym_above_50d"] = sc > sc.rolling(50).mean()
    return f.shift(1)  # prior-day values only


def bucket_table(trades: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    rows = []
    for ft in feats:
        for val in (True, False):
            sub = trades[trades[ft] == val]
            if len(sub) == 0:
                continue
            wins = sub.pnl[sub.pnl > 0].sum()
            losses = -sub.pnl[sub.pnl <= 0].sum()
            rows.append({"feature": ft, "state": val, "n": len(sub),
                         "net_usd": round(sub.pnl.sum(), 0),
                         "exp_R": round(sub.r.mean(), 3),
                         "win_%": round((sub.pnl > 0).mean() * 100, 1),
                         "pf": round(wins / losses, 2) if losses > 0 else np.inf})
    return pd.DataFrame(rows)


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Loading cached 2y of 5m bars ...")
    spy5 = load_bars("SPY", 730)
    spy_d = daily(spy5)
    cfg = config_v2(trade_dir="long")

    all_tr = []
    for s in BASKET:
        df5 = load_bars(s, 730)
        feats = regime_features(spy_d, daily(df5))
        r = run(df5, spy5, cfg)
        for t in r["trades"]:
            d = pd.Timestamp(t["entry_time"]).date()
            row = {"symbol": s, "date": d, "pnl": t["pnl"], "r": t.get("r", np.nan)}
            key = pd.Timestamp(d)
            if key in feats.index:
                row.update(feats.loc[key].to_dict())
            all_tr.append(row)
    tr = pd.DataFrame(all_tr).dropna()
    feats = [c for c in tr.columns if c.startswith(("spy_", "vol_", "sym_"))]
    tr[feats] = tr[feats].astype(bool)
    h1 = tr[tr.date < SPLIT]
    h2 = tr[tr.date >= SPLIT]
    print(f"  {len(tr)} regime-tagged trades  (H1: {len(h1)}, H2: {len(h2)})")

    # ── derive on H1 only ─────────────────────────────────────────────────────
    t1 = bucket_table(h1, feats)
    best, best_spread, best_state = None, 0.0, True
    for ft in feats:
        a = t1[(t1.feature == ft) & (t1.state == True)]
        b = t1[(t1.feature == ft) & (t1.state == False)]
        if len(a) and len(b) and a.n.iloc[0] >= 40 and b.n.iloc[0] >= 40:
            spread = a.exp_R.iloc[0] - b.exp_R.iloc[0]
            if abs(spread) > abs(best_spread):
                best, best_spread = ft, spread
                best_state = spread > 0
    gate_desc = f"{best} == {best_state}"
    print(f"\nH1-derived gate (pre-registered, single shot): TRADE ONLY WHEN {gate_desc}"
          f"  (H1 expR spread {best_spread:+.3f})")

    # ── validate on H2, untouched ────────────────────────────────────────────
    def summarize(sub, label):
        wins = sub.pnl[sub.pnl > 0].sum()
        losses = -sub.pnl[sub.pnl <= 0].sum()
        return {"set": label, "n": len(sub), "net_usd": round(sub.pnl.sum(), 0),
                "exp_R": round(sub.r.mean(), 3),
                "win_%": round((sub.pnl > 0).mean() * 100, 1),
                "pf": round(wins / losses, 2) if losses > 0 else np.inf}

    h2_gated = h2[h2[best] == best_state]
    h2_blocked = h2[h2[best] != best_state]
    verdict = pd.DataFrame([
        summarize(h1, "H1 all (derivation set)"),
        summarize(h1[h1[best] == best_state], "H1 gated"),
        summarize(h2, "H2 all (validation set)"),
        summarize(h2_gated, "H2 GATED  <- the verdict"),
        summarize(h2_blocked, "H2 blocked by gate"),
    ])
    t2 = bucket_table(h2, feats)

    print("\n== H2 validation ==")
    print(verdict.to_string(index=False))

    out = REPORTS / f"regime_autopsy_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Regime autopsy — {date.today().isoformat()}\n\n")
        f.write(f"v2-long, 2y Alpaca 5m, {len(tr)} regime-tagged trades. All features "
                f"prior-day-observable (shifted 1 day; no lookahead).\n\n")
        f.write(f"**Protocol:** gate derived on H1 (< {SPLIT}) only, applied once to H2. "
                f"No iteration.\n\n")
        f.write(f"**H1-derived gate: trade only when `{gate_desc}`** "
                f"(H1 expectancy spread {best_spread:+.3f}R)\n\n")
        f.write("## Verdict table\n\n" + verdict.to_markdown(index=False) + "\n\n")
        f.write("## H1 buckets (derivation set)\n\n" + t1.to_markdown(index=False) + "\n\n")
        f.write("## H2 buckets (shown AFTER the gate was fixed — reference only)\n\n")
        f.write(t2.to_markdown(index=False) + "\n\n")
        f.write("*If 'H2 GATED' does not clearly beat 'H2 all', regime conditioning on "
                "these features is dead too, and the honest conclusion stands: the edge "
                "must come from orthogonal data, not OHLCV geometry. Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
