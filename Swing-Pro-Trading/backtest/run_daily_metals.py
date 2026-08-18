"""
run_daily_metals.py — does SWING_PRO-D work on METALS? (Ari has it on a GOLD chart.)

Same daily engine validated on equities (decade, PF 2.2-2.7), pointed at
GLD / GDX / SLV daily bars, 2016-2026. SPY market filter OFF — the S&P is the
wrong compass for metals. Single shot, same H1/H2 split (2021-07-01).
"""
import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import config_v22, run

SPLIT = pd.Timestamp("2021-07-01")
spy = load_bars("SPY", 3650, interval="1d")
cfg = config_v22(trade_dir="long", use_htf_trend=False, use_market_filter=False)

allt = []
for s in ["GLD", "GDX", "SLV"]:
    df = load_bars(s, 3650, interval="1d")
    r = run(df, spy, cfg)
    st = r["stats"]
    allt += r["trades"]
    print(f"{s}: {len(df)} bars  n={st['trades']}  net={st['net_profit']:.0f}  "
          f"win%={st['win_rate']:.1f}  pf={st['profit_factor']:.2f}  "
          f"maxDD%={st['max_dd_pct']:.2f}")


def agg(tr):
    p = np.array([t["pnl"] for t in tr])
    w, l = p[p > 0], p[p <= 0]
    pf = round(float(w.sum() / -l.sum()), 2) if len(l) and l.sum() < 0 else float("nan")
    return {"n": len(p), "net": round(float(p.sum())), "pf": pf,
            "win%": round(100 * len(w) / len(p), 1) if len(p) else float("nan")}


h1 = [t for t in allt if pd.Timestamp(t["entry_time"]).tz_localize(None) < SPLIT]
h2 = [t for t in allt if pd.Timestamp(t["entry_time"]).tz_localize(None) >= SPLIT]
print("FULL:", agg(allt))
print("H1 2016-2021:", agg(h1))
print("H2 2021-2026:", agg(h2))
