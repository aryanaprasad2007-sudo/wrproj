"""
run_tf1h_test.py — does v2.2 clear costs better on 1-HOUR bars?

Motivation: cost drag has been the recurring killer (3x costs sank the 1m
theory; $0.01 slippage taxes every 5m trade). Identical v2.2 logic on 1h bars
makes each trade's expected move much larger relative to fixed costs, and the
HTF regime anchor becomes the DAILY trend — a true swing configuration.

1h bars are resampled from the cached 5m Alpaca data (RTH 09:30-anchored, so
bars are 9:30-10:30 ... 15:30-16:00 — same as a TradingView RTH hourly chart).

Same H1/H2 discipline. Usage:  py run_tf1h_test.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars, _clean_rth
from swing_pro import config_v22, run

BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]
REPORTS = Path(__file__).parent / "reports"
SPLIT = pd.Timestamp("2025-07-02")


def resample_1h(df5: pd.DataFrame) -> pd.DataFrame:
    g = df5.resample("60min", offset="570min", label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last(),
                        "volume": g["volume"].sum()}).dropna(subset=["open", "close"])
    return _clean_rth(out)


def agg(trades):
    pnls = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    rs = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls <= 0] if len(pnls) else np.array([])
    return {"n": len(pnls), "net": round(float(pnls.sum()), 0) if len(pnls) else 0,
            "expR": round(float(rs.mean()), 3) if len(rs) else np.nan,
            "win%": round(float(len(wins) / len(pnls) * 100), 1) if len(pnls) else np.nan,
            "pf": round(float(wins.sum() / -losses.sum()), 2)
                  if len(losses) and losses.sum() < 0 else np.nan}


def main():
    REPORTS.mkdir(exist_ok=True)
    spy5 = load_bars("SPY", 730)
    spy1h = resample_1h(spy5)
    cfg = config_v22(trade_dir="long", bar_minutes=60)

    rows, all_tr = [], []
    for s in BASKET:
        df1h = resample_1h(load_bars(s, 730))
        r = run(df1h, spy1h, cfg)
        all_tr += r["trades"]
        st = r["stats"]
        rows.append({"symbol": s, "trades": st["trades"],
                     "net": round(st["net_profit"], 0),
                     "expR": round(st["expectancy_r"], 3),
                     "win%": round(st["win_rate"], 1),
                     "pf": round(st["profit_factor"], 2),
                     "maxDD%": round(st["max_dd_pct"], 2)})

    h1 = [t for t in all_tr if pd.Timestamp(t["entry_time"]).tz_localize(None) < SPLIT]
    h2 = [t for t in all_tr if pd.Timestamp(t["entry_time"]).tz_localize(None) >= SPLIT]
    f, a1, a2 = agg(all_tr), agg(h1), agg(h2)

    per = pd.DataFrame(rows)
    print(per.to_string(index=False))
    print(f"\nFULL: {f}   H1: {a1}   H2: {a2}")

    out = REPORTS / f"tf1h_test_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f"# v2.2 on 1-hour bars — {date.today().isoformat()}\n\n")
        fh.write("Same engine, same config, 1h bars (daily regime anchor). "
                 "Reference: v2.2 on 5m = +$6,835 / PF 1.30 (H1 1.27, H2 1.35).\n\n")
        fh.write("## Aggregate\n\n")
        fh.write(pd.DataFrame([{"set": "FULL 2y", **f}, {"set": "H1", **a1},
                               {"set": "H2", **a2}]).to_markdown(index=False) + "\n\n")
        fh.write("## Per symbol\n\n" + per.to_markdown(index=False) + "\n\n")
        fh.write("*Fewer trades on 1h — judge PF/expectancy, not net alone. "
                 "Not financial advice.*\n")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
