"""
run_execution_batch.py — the CLOSING ACT against the 2y dataset.
Two final studies, then this well is retired (H1/H2 split is wearing out).

B) LIMIT-ENTRY: instead of a market order at next 5m open (pays spread+slip),
   work a limit at the signal bar's close for K 5m bars (K=1, K=3), fills
   checked against real 1m lows. Misses runners; saves costs on every fill.
   Exits (stop / 3R target) are anchored to the signal close, so they are
   IDENTICAL — only the entry price and the missed-trade set change.

C) TIME-STOP: first an MAE/MFE portrait of every trade (how far do winners /
   losers drift, in R, before resolving?). Thresholds for the time-stop rules
   are derived from the H1 distribution ONLY, then all rules are validated on
   H2. Rule form: "if unrealized < X·R after N 5m bars, exit at that close."

Adoption bar, as always: beat v2.2 baseline in BOTH halves.
Usage:  py run_execution_batch.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars, load_bars_1m
from swing_pro import config_v22, run

SYMBOLS = ["AAPL", "NVDA", "TSLA", "MSFT", "META",
           "MSTR", "ORCL", "NFLX", "AVGO", "CRWD"]
REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2025-07-02")
COMM = 0.0001
SLIP = 0.01


def agg(pnls):
    p = np.array(pnls)
    if not len(p):
        return {"n": 0, "net": 0.0, "pf": np.nan}
    w, l = p[p > 0], p[p <= 0]
    return {"n": len(p), "net": round(float(p.sum()), 0),
            "pf": round(float(w.sum() / -l.sum()), 2) if len(l) and l.sum() < 0 else np.nan}


def main():
    REPORTS.mkdir(exist_ok=True)
    spy = load_bars("SPY", 730)
    cfg = config_v22(trade_dir="long")

    trades = []   # per-trade dict incl. 5m path & 1m window
    for s in SYMBOLS:
        df5 = load_bars(s, 730)
        df1 = load_bars_1m(s, 730)
        idx5 = df5.index
        r = run(df5, spy, cfg)
        for t in r["trades"]:
            try:
                ei = idx5.get_loc(pd.Timestamp(t["entry_time"]))
                xi = idx5.get_loc(pd.Timestamp(t["exit_time"]))
            except KeyError:
                continue
            path = df5.iloc[ei:xi + 1]
            entry_ts = idx5[ei]
            w1 = df1[(df1.index >= entry_ts) & (df1.index < entry_ts + pd.Timedelta(minutes=15))]
            trades.append({
                "symbol": s, "entry_ts": entry_ts,
                "ref": t["signal_ref"], "risk": t["risk"],
                "mkt_fill": t["entry_fill"], "exit_px": t["exits"][-1][1],
                "reason": t["exits"][-1][3],
                "hi_path": path["high"].to_numpy(), "lo_path": path["low"].to_numpy(),
                "cl_path": path["close"].to_numpy(),
                "m1_open": w1["open"].to_numpy(), "m1_low": w1["low"].to_numpy(),
                "m1_bar5": ((w1.index - entry_ts).total_seconds() // 300).astype(int),
            })
    tr = pd.DataFrame([{k: v for k, v in t.items() if not isinstance(v, np.ndarray)}
                       for t in trades])
    tr["h"] = np.where(tr.entry_ts.dt.tz_localize(None) < SPLIT, "H1", "H2")
    print(f"{len(trades)} trades reconstructed with paths")

    # ── baseline (market entries, as traded) ─────────────────────────────────
    base_pnl = [(t["exit_px"] - t["mkt_fill"]) -
                (t["exit_px"] + t["mkt_fill"]) * COMM for t in trades]
    tr["pnl_base"] = base_pnl

    # ── B) limit entries ─────────────────────────────────────────────────────
    for K in (1, 3):
        pnls, filled = [], 0
        col = []
        for t in trades:
            lim = t["ref"]
            m = t["m1_bar5"] < K
            fill = np.nan
            if m.any():
                opens, lows = t["m1_open"][m], t["m1_low"][m]
                if len(opens) and opens[0] <= lim:
                    fill = opens[0]
                elif (lows <= lim).any():
                    fill = lim
            if not np.isnan(fill):
                filled += 1
                pnls.append((t["exit_px"] - fill) - (t["exit_px"] + fill) * COMM)
                col.append(pnls[-1])
            else:
                col.append(np.nan)
        tr[f"pnl_limK{K}"] = col
        print(f"  limit K={K}: filled {filled}/{len(trades)}")

    # ── C) MAE/MFE + time-stops ──────────────────────────────────────────────
    mae = [(t["lo_path"].min() - t["ref"]) / t["risk"] for t in trades]
    mfe = [(t["hi_path"].max() - t["ref"]) / t["risk"] for t in trades]
    nbars = [len(t["cl_path"]) for t in trades]
    tr["mae_R"], tr["mfe_R"], tr["nbars"] = mae, mfe, nbars

    h1w = tr[(tr.h == "H1") & (tr.pnl_base > 0)]
    med_bars_w = int(h1w.nbars.median()) if len(h1w) else 24
    rules = [(med_bars_w, 0.0), (med_bars_w, 0.5), (med_bars_w * 2, 0.5)]

    for N, X in rules:
        col = []
        for t in trades:
            cl = t["cl_path"]
            if len(cl) > N and (cl[N] - t["ref"]) / t["risk"] < X:
                ex = cl[N] - SLIP
                col.append((ex - t["mkt_fill"]) - (ex + t["mkt_fill"]) * COMM)
            else:
                col.append((t["exit_px"] - t["mkt_fill"]) -
                           (t["exit_px"] + t["mkt_fill"]) * COMM)
        tr[f"pnl_ts{N}_{X}"] = col

    # ── report ───────────────────────────────────────────────────────────────
    out = REPORTS / f"execution_batch_{date.today().isoformat()}.md"
    variants = (["pnl_base", "pnl_limK1", "pnl_limK3"] +
                [f"pnl_ts{N}_{X}" for N, X in rules])
    rows = []
    for v in variants:
        full = agg(tr[v].dropna())
        a1 = agg(tr[tr.h == "H1"][v].dropna())
        a2 = agg(tr[tr.h == "H2"][v].dropna())
        rows.append({"variant": v.replace("pnl_", ""), **full,
                     "H1_net": a1["net"], "H1_pf": a1["pf"],
                     "H2_net": a2["net"], "H2_pf": a2["pf"]})
        print(f"  {v:<14} net={full['net']:>8} pf={full['pf']:>5} "
              f"H1 {a1['net']:>7}/{a1['pf']:<5} H2 {a2['net']:>7}/{a2['pf']}")
    res = pd.DataFrame(rows)
    b = res[res.variant == "base"].iloc[0]
    res["beats_base_both"] = np.where(
        (res.H1_net > b.H1_net) & (res.H2_net > b.H2_net) & (res.variant != "base"),
        "YES", "")

    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Execution batch (B: limit entries, C: time-stops) — "
                f"{date.today().isoformat()}\n\n")
        f.write(f"{len(trades)} v2.2 trades, 10 symbols, 2y. THE FINAL tests against "
                f"this dataset — the H1/H2 split is retired after this report.\n\n")
        f.write("## Results (per-trade PnL re-priced; sizing-neutral, per ~10k notional)\n\n")
        f.write(res.to_markdown(index=False) + "\n\n")
        f.write("## MAE/MFE portrait (all trades)\n\n")
        f.write(f"- Winners: median MAE {tr[tr.pnl_base > 0].mae_R.median():.2f}R, "
                f"median bars to resolve {int(tr[tr.pnl_base > 0].nbars.median())}\n")
        f.write(f"- Losers:  median MFE {tr[tr.pnl_base <= 0].mfe_R.median():.2f}R "
                f"(how close they got to winning), median bars "
                f"{int(tr[tr.pnl_base <= 0].nbars.median())}\n")
        f.write(f"- Time-stop rules derived from H1 winners' median duration "
                f"({med_bars_w} bars).\n\n")
        f.write("*Only YES rows are adoption candidates. After this: evidence comes "
                "from the forward test and the maturing options dataset, not from "
                "re-mining these two years. Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
