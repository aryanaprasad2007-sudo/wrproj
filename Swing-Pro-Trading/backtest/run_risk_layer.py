"""
run_risk_layer.py — the risk & sizing layer study (the last untested axis).

Signals are frozen (v2.2 long-only, all 10 forward-test symbols, 2y). What
changes is PORTFOLIO-LEVEL money management:

  sizing  : flat 10% of equity (current)  vs  equal-risk 0.25% / 0.50% of
            equity at risk per trade (qty = risk$ / stop distance, notional
            capped at 30% equity)
  cap     : max concurrent positions  {unlimited, 5, 3}
  daystop : halt NEW entries after a -1% equity day  {off, on}

Metric: MAR ratio (net% / |maxDD%|) — sizing rules don't change per-trade edge,
they change how much account you make per unit of pain. Winner must beat the
baseline MAR in BOTH halves (same discipline as everything else).

v2.2 has single-exit trades (no partials), so each trade is (entry_px, exit_px,
risk_per_share) and can be re-sized cleanly. Commission 0.01%/side re-applied
to the re-sized notional; slippage is already inside the engine's fill prices.

Usage:  py run_risk_layer.py     (cached data; a few minutes)
"""
from __future__ import annotations

from datetime import date
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import config_v22, run

SYMBOLS = ["AAPL", "NVDA", "TSLA", "MSFT", "META",
           "MSTR", "ORCL", "NFLX", "AVGO", "CRWD"]
REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2025-07-02")
START_EQ = 100_000.0
COMM = 0.0001  # 0.01% per side


def collect_trades():
    spy = load_bars("SPY", 730)
    cfg = config_v22(trade_dir="long")
    evs = []
    for s in SYMBOLS:
        for t in run(load_bars(s, 730), spy, cfg)["trades"]:
            if not t["exits"]:
                continue
            evs.append({
                "symbol": s,
                "entry": pd.Timestamp(t["entry_time"]).tz_localize(None),
                "exit": pd.Timestamp(t["exit_time"]).tz_localize(None),
                "entry_px": t["entry_fill"],
                "exit_px": t["exits"][-1][1],
                "risk_ps": t["risk"],
            })
    return sorted(evs, key=lambda e: e["entry"])


def simulate(trades, sizing, risk_pct, max_pos, daystop):
    eq = START_EQ
    open_pos = []          # list of dicts with exit info
    curve_t, curve_v = [], []
    day = None
    day_start_eq = eq
    halted = False
    taken = skipped = 0

    events = []
    for tr in trades:
        events.append((tr["entry"], "in", tr))
        events.append((tr["exit"], "out", tr))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "out" else 1))  # exits first

    for ts, kind, tr in events:
        d = ts.date()
        if d != day:
            day = d
            day_start_eq = eq
            halted = False
        if kind == "out":
            for p in list(open_pos):
                if p["tr"] is tr:
                    pnl = (tr["exit_px"] - tr["entry_px"]) * p["qty"]
                    pnl -= (tr["entry_px"] + tr["exit_px"]) * p["qty"] * COMM
                    eq += pnl
                    open_pos.remove(p)
            if daystop and (eq - day_start_eq) / day_start_eq <= -0.01:
                halted = True
        else:
            if halted or (max_pos and len(open_pos) >= max_pos):
                skipped += 1
                continue
            if sizing == "flat":
                qty = 0.10 * eq / tr["entry_px"]
            else:
                qty = (risk_pct / 100.0) * eq / max(tr["risk_ps"], 1e-9)
                qty = min(qty, 0.30 * eq / tr["entry_px"])  # notional cap
            if qty <= 0:
                skipped += 1
                continue
            open_pos.append({"tr": tr, "qty": qty})
            taken += 1
        curve_t.append(ts)
        curve_v.append(eq)

    v = np.array(curve_v) if curve_v else np.array([START_EQ])
    peak = np.maximum.accumulate(v)
    maxdd = float(((v - peak) / peak).min() * 100)
    net = float((eq - START_EQ) / START_EQ * 100)
    mar = net / abs(maxdd) if maxdd < 0 else np.nan
    return {"net%": round(net, 2), "maxDD%": round(maxdd, 2),
            "MAR": round(mar, 2) if not np.isnan(mar) else np.nan,
            "taken": taken, "skipped": skipped}


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Collecting v2.2 trade streams (10 symbols, 2y, cached) ...")
    trades = collect_trades()
    h1 = [t for t in trades if t["entry"] < SPLIT]
    h2 = [t for t in trades if t["entry"] >= SPLIT]
    print(f"  {len(trades)} trades ({len(h1)} H1, {len(h2)} H2)")

    grid = []
    for sizing, rp in (("flat", 0), ("eqrisk", 0.25), ("eqrisk", 0.50)):
        for cap in (0, 5, 3):
            for ds in (False, True):
                grid.append((sizing, rp, cap, ds))

    rows = []
    for sizing, rp, cap, ds in grid:
        name = f"{sizing}{rp if rp else ''}_cap{cap or 'inf'}_ds{'1' if ds else '0'}"
        full = simulate(trades, sizing, rp, cap, ds)
        a1 = simulate(h1, sizing, rp, cap, ds)
        a2 = simulate(h2, sizing, rp, cap, ds)
        rows.append({"rule": name, **full,
                     "H1_MAR": a1["MAR"], "H2_MAR": a2["MAR"],
                     "H1_net%": a1["net%"], "H2_net%": a2["net%"]})
        print(f"  {name:<24} net {full['net%']:>6}%  dd {full['maxDD%']:>6}%  "
              f"MAR {full['MAR']:>5}  H1 {a1['MAR']:>5}  H2 {a2['MAR']:>5}")

    df = pd.DataFrame(rows)
    base = df[df.rule == "flat_capinf_ds0"].iloc[0]
    df["beats_base_both_halves"] = np.where(
        (df.H1_MAR > base.H1_MAR) & (df.H2_MAR > base.H2_MAR)
        & (df.rule != base.rule), "YES", "")

    out = REPORTS / f"risk_layer_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Risk & sizing layer study — {date.today().isoformat()}\n\n")
        f.write(f"{len(trades)} v2.2 trades, 10 symbols, 2y. Signals frozen; only "
                f"money management varies. Metric: MAR = net% / |maxDD%|.\n\n")
        f.write(f"Baseline (current live config): flat 10%, no cap, no day-stop -> "
                f"net {base['net%']}%, DD {base['maxDD%']}%, MAR {base['MAR']}\n\n")
        f.write(df.sort_values("MAR", ascending=False).to_markdown(index=False) + "\n\n")
        f.write("*Rules marked YES beat the baseline MAR in both halves — only those "
                "are adoption candidates. Equity marked at trade events (approx DD). "
                "Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
