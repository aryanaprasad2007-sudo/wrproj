"""
run_improvement_test.py â€” testing the fixes for the whipsaw failure mode seen on
the META 5m chart (2026-07-02 screenshot): entries chasing extension, then
stop-out, then instant re-entry churn during counter-trend rips.

Candidates (each mechanically targets the visible failure):
  M1  extension veto     â€” entry only within 2.0 (and 3.0) ATR of the trend line
  M2  pullback-only      â€” drop Entry A (state trigger); enter only at the fast EMA
  M3  loss cooldown      â€” after a losing trade, same direction locked for 10 bars
  M1+M3 combo            â€” location discipline + churn brake

Bar: a fix must improve the FULL 2y result AND both halves (H1/H2) AND not
collapse the trade count, on BOTH sides tested separately. Otherwise it's noise.

Usage:  py run_improvement_test.py
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
SPLIT = pd.Timestamp("2025-07-02")

VARIANTS = {
    "base_v2":        {},
    "M1_ext1.0":      {"max_ext_atr": 1.0},
    "M1_ext2.0":      {"max_ext_atr": 2.0},
    "M2_pullback":    {"use_state_entry": False},
    "M3_cool10":      {"loss_cooldown_bars": 10},
    "M1+M3":          {"max_ext_atr": 1.0, "loss_cooldown_bars": 10},
}


def half_split(trades):
    h1 = [t for t in trades if pd.Timestamp(t["entry_time"]).tz_localize(None) < SPLIT]
    h2 = [t for t in trades if pd.Timestamp(t["entry_time"]).tz_localize(None) >= SPLIT]
    return h1, h2


def agg(trades):
    pnls = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    rs = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls <= 0] if len(pnls) else np.array([])
    return {"n": len(pnls),
            "net": round(float(pnls.sum()), 0) if len(pnls) else 0.0,
            "expR": round(float(rs.mean()), 3) if len(rs) else np.nan,
            "win%": round(float(len(wins) / len(pnls) * 100), 1) if len(pnls) else np.nan,
            "pf": round(float(wins.sum() / -losses.sum()), 2)
                  if len(losses) and losses.sum() < 0 else np.nan}


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Loading 2y of 5m bars (cached) ...")
    spy = load_bars("SPY", 730)
    bars = {s: load_bars(s, 730) for s in BASKET}

    rows = []
    for side in ("long", "short"):
        for vname, ovr in VARIANTS.items():
            trades = []
            for s in BASKET:
                r = run(bars[s], spy, config_v2(trade_dir=side), **ovr)
                trades += r["trades"]
            full = agg(trades)
            h1, h2 = half_split(trades)
            a1, a2 = agg(h1), agg(h2)
            row = {"side": side, "variant": vname, **full,
                   "H1_net": a1["net"], "H1_pf": a1["pf"],
                   "H2_net": a2["net"], "H2_pf": a2["pf"],
                   "both_halves_up": "YES" if (vname != "base_v2") else ""}
            rows.append(row)
            print(f"  {side:<5} {vname:<12} n={full['n']:<5} net={full['net']:>8.0f} "
                  f"expR={full['expR']:>6} pf={full['pf']:>5}  "
                  f"H1 {a1['net']:>7.0f}/{a1['pf']:<5} H2 {a2['net']:>7.0f}/{a2['pf']}")

    df = pd.DataFrame(rows)
    # mark which variants beat base in BOTH halves (per side)
    for side in ("long", "short"):
        b = df[(df.side == side) & (df.variant == "base_v2")].iloc[0]
        m = df.side == side
        df.loc[m, "both_halves_up"] = np.where(
            (df.loc[m, "H1_net"] >= b.H1_net) & (df.loc[m, "H2_net"] >= b.H2_net) &
            (df.loc[m, "variant"] != "base_v2"), "YES", "")

    out = REPORTS / f"improvement_test_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Whipsaw-fix test â€” {date.today().isoformat()}\n\n")
        f.write("Failure mode targeted: late extension-chasing entries + stop-out churn "
                "during counter-trend rips (META 5m screenshot, 2026-07-02).\n\n")
        f.write("Bar for adoption: improves the full-2y result AND both halves AND keeps "
                "a sane trade count â€” separately per side.\n\n")
        f.write(df.to_markdown(index=False) + "\n\n")
        f.write("*Variants marked YES beat base in both halves (net). Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()

