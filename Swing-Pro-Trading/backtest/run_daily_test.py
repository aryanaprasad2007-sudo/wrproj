"""
run_daily_test.py — SWING_PRO-D: the v2.2 engine on DAILY bars, validated on a
DECADE of never-mined data (2016-2026).

Why this is a legitimate new experiment (not re-mining the retired well):
  • Fresh data: the retired split covered 2024-07 -> 2026-07 intraday. This uses
    ~10 years of DAILY bars — the 2018 crash, COVID, the 2022 bear, two bulls.
  • The cost thesis: $0.01 slippage + 0.01% commission are near-invisible against
    multi-dollar daily ranges — the drag that hurt every intraday variant ~vanishes.
  • Config: v2.2 exits (pure stop + 3R), long-only, LOCAL daily trend regime
    (EMA50 + ATR-slope on daily bars; no intraday HTF machinery), same 7 gates.

Pre-registered bar: PF > 1.15 in BOTH halves (split 2021-07-01), decent samples.
Usage:  py run_daily_test.py     (first run fetches ~10y of daily bars — fast)
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import config_v22, run

import sys

SYMBOLS = ["AAPL", "NVDA", "TSLA", "MSFT", "META",
           "MSTR", "ORCL", "NFLX", "AVGO", "CRWD"]
# survivorship control: boring non-darlings — if the engine only works on
# hindsight-picked decade winners, it will fail here
CONTROL = ["JPM", "GS", "XOM", "CVX", "CAT", "DE", "BA", "WMT", "COST", "HD",
           "UNH", "DIS", "KO"]
if "--control" in sys.argv:
    SYMBOLS = CONTROL
REPORTS = Path(__file__).parent / "reports"
DAYS = 3650
SPLIT = pd.Timestamp("2021-07-01")


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
    print(f"Loading ~10y of DAILY bars: SPY + {', '.join(SYMBOLS)} ...")
    spy = load_bars("SPY", DAYS, interval="1d")
    cfg = config_v22(trade_dir="long", use_htf_trend=False)

    rows, all_tr = [], []
    for s in SYMBOLS:
        df = load_bars(s, DAYS, interval="1d")
        r = run(df, spy, cfg)
        tr = r["trades"]
        all_tr += tr
        st = r["stats"]
        rows.append({"symbol": s, "bars": len(df),
                     "since": str(df.index[0].date()),
                     "trades": st["trades"], "net": round(st["net_profit"], 0),
                     "win%": round(st["win_rate"], 1),
                     "pf": round(st["profit_factor"], 2),
                     "maxDD%": round(st["max_dd_pct"], 2)})
        print(f"  {s}: {len(df)} bars since {df.index[0].date()}  "
              f"n={st['trades']} net={st['net_profit']:.0f} pf={st['profit_factor']:.2f}")

    h1 = [t for t in all_tr if pd.Timestamp(t["entry_time"]).tz_localize(None) < SPLIT]
    h2 = [t for t in all_tr if pd.Timestamp(t["entry_time"]).tz_localize(None) >= SPLIT]
    f_, a1, a2 = agg(all_tr), agg(h1), agg(h2)
    passed = (not np.isnan(a1["pf"])) and (not np.isnan(a2["pf"])) \
        and a1["pf"] > 1.15 and a2["pf"] > 1.15
    print(f"\nFULL: {f_}\nH1 (2016-2021): {a1}\nH2 (2021-2026): {a2}")
    print(f"VALIDATED (PF>1.15 both halves): {passed}")

    out = REPORTS / f"daily_test_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# SWING_PRO-D — daily-bar validation on a decade — "
                f"{date.today().isoformat()}\n\n")
        f.write("v2.2 exits, long-only, local daily EMA50 regime, same 7 gates. "
                "FRESH data (2016-2026 daily — never mined by any prior test). "
                "Pre-registered bar: PF > 1.15 in both halves (split 2021-07-01).\n\n")
        f.write(f"**VALIDATED: {'YES' if passed else 'NO'}**\n\n")
        f.write("## Aggregate\n\n")
        f.write(pd.DataFrame([{"set": "FULL decade", **f_},
                              {"set": "H1 2016-2021", **a1},
                              {"set": "H2 2021-2026", **a2}]).to_markdown(index=False) + "\n\n")
        f.write("## Per symbol (note IPO-truncated histories)\n\n")
        f.write(pd.DataFrame(rows).to_markdown(index=False) + "\n\n")
        f.write("*Positions can gap overnight on daily bars — stops fill at the stop "
                "price in this model but can slip through gaps in reality; treat PF "
                "as slightly optimistic. Not financial advice.*\n")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
