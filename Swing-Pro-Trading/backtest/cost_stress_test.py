"""
cost_stress_test.py — how much real-world friction can the 2026-07-30 winner
absorb before the edge disappears?

WINNER (backtest/reports/holdout_sweep_2026-07-30.md):
    tf=3 sessions/bar · adx_min=15 · rsi_long=50 · stop=1.5xATR · rr=2.0
    engine: swing_pro.config_v22(trade_dir="long", use_htf_trend=False, ...)

That result was backtested with swing_pro.Config's defaults baked in:
commission_pct=0.01 (0.01%/side) and slippage_ticks=1 ($0.01/share). Real
fills on a small Robinhood account — fractional shares, market orders,
regular hours only — will be worse than that. This script reruns the exact
same config across increasing cost levels and reports where the edge
actually breaks (PF crosses below 1.0), interpolating between tested points.

Usage:  py cost_stress_test.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from run_daily_30y import SYMBOLS, fetch_daily
from run_timeframe_scan import group_bars
from swing_pro import config_v22, run

REPORTS = Path(__file__).parent / "reports"
MIN_BARS = 260
TF_SESSIONS = 3  # the winning timeframe

# (level, commission_pct, slippage_ticks)
LEVELS = [
    (0, 0.01, 1),   # baseline — the assumption baked into the 2026-07-30 backtest
    (1, 0.02, 2),
    (2, 0.05, 3),
    (3, 0.10, 5),
    (4, 0.20, 8),   # deliberately extreme, to find the actual breaking point
]


def stats(trades: list) -> dict:
    p = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    R = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    if not len(p):
        return {"n": 0, "pf": np.nan, "win%": np.nan, "expR": np.nan,
                "t": np.nan, "net": 0.0}
    w, l = p[p > 0], p[p <= 0]
    t = (float(R.mean()) / (float(R.std(ddof=1)) / np.sqrt(len(R)))
         if len(R) > 2 and R.std(ddof=1) > 0 else np.nan)
    return {"n": int(len(p)),
            "pf": round(float(w.sum() / -l.sum()), 3) if len(l) and l.sum() < 0 else np.nan,
            "win%": round(100 * len(w) / len(p), 1),
            "expR": round(float(R.mean()), 4) if len(R) else np.nan,
            "t": round(t, 2) if t == t else np.nan,
            "net": round(float(p.sum()))}


def run_level(grouped: dict, spy: pd.DataFrame, commission_pct: float, slippage_ticks: float) -> dict:
    cfg = config_v22(trade_dir="long", use_htf_trend=False,
                      adx_min=15, rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0,
                      commission_pct=commission_pct, slippage_ticks=slippage_ticks)
    all_tr, tested = [], 0
    for sym, df in grouped.items():
        if len(df) < MIN_BARS:
            continue
        try:
            r = run(df, spy, cfg)
        except Exception:
            continue
        tested += 1
        all_tr += [t for t in r["trades"] if t.get("pnl") is not None]
    return {"commission_pct": commission_pct, "slippage_ticks": slippage_ticks,
            "tested": tested, **stats(all_tr)}


def find_breakeven(grouped: dict, spy: pd.DataFrame, base_row: dict) -> tuple[list, str, float]:
    """Level 4 (comm=0.20%, slip=8) is nowhere near breakeven for this edge.
    Scale both commission_pct and slippage_ticks together as a multiplier `m`
    on the Level-4 pair, doubling m until PF<1, then binary-search m to
    pin the crossing. Returns the extra probe rows (for the report) and a
    human-readable summary of where PF actually crosses 1.0."""
    base_comm, base_slip = 0.20, 8.0
    extra_rows = []

    def probe(m):
        row = run_level(grouped, spy, base_comm * m, base_slip * m)
        row["m"] = m
        extra_rows.append(row)
        return row

    m = 1.0
    last_ok = probe(m)
    if last_ok["pf"] != last_ok["pf"] or last_ok["pf"] < 1.0:
        return extra_rows, "at or below Level 4 already", 1.0

    m_hi = None
    while m_hi is None:
        m *= 2
        if m > 64:  # safety backstop — should never trigger for this edge
            return extra_rows, f"not reached even at {m/2:.0f}x Level-4 cost", m / 2
        row = probe(m)
        if row["pf"] != row["pf"] or row["pf"] < 1.0:
            m_hi = m
        else:
            last_ok = row
    m_lo = m_hi / 2

    for _ in range(6):
        m_mid = (m_lo + m_hi) / 2
        row = probe(m_mid)
        if row["pf"] != row["pf"] or row["pf"] < 1.0:
            m_hi = m_mid
        else:
            m_lo = m_mid

    comm_be = base_comm * m_lo
    slip_be = base_slip * m_lo
    summary = (f"~{m_lo:.2f}x the Level-4 cost pair -> commission_pct~{comm_be:.2f}, "
               f"slippage_ticks~{slip_be:.1f} (~{m_lo * 20:.0f}x baseline commission, "
               f"~{m_lo * 8:.0f}x baseline slippage)")
    return extra_rows, summary, m_lo


def interpolate_breakeven(rows: list) -> str:
    """Find where PF crosses 1.0, interpolating linearly between the two
    tested levels that straddle it. Levels are on an irregular grid (cost
    roughly doubles each step), so report both the level index (fractional)
    and the underlying commission_pct/slippage_ticks it implies."""
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a["pf"] != a["pf"] or b["pf"] != b["pf"]:
            continue
        if a["pf"] >= 1.0 and b["pf"] < 1.0:
            frac = (a["pf"] - 1.0) / (a["pf"] - b["pf"])
            comm = a["commission_pct"] + frac * (b["commission_pct"] - a["commission_pct"])
            slip = a["slippage_ticks"] + frac * (b["slippage_ticks"] - a["slippage_ticks"])
            return (f"between Level {a['level']} and Level {b['level']} "
                    f"(~{frac:.2f} of the way), interpolating to roughly "
                    f"commission_pct~{comm:.3f}, slippage_ticks~{slip:.1f}")
    if all((r["pf"] == r["pf"] and r["pf"] >= 1.0) for r in rows):
        return "not reached within the tested range - PF stayed >= 1.0 through Level 4"
    if rows[0]["pf"] != rows[0]["pf"] or rows[0]["pf"] < 1.0:
        return "at or below Level 0 — the edge is not positive even at baseline cost"
    return "could not be determined (non-monotonic or missing PF values)"


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Loading 30y daily bars (cached)...")
    spy_d = fetch_daily("SPY")
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = fetch_daily(s)
        except Exception:
            pass
    print(f"{len(data)} symbols\n")

    spy = group_bars(spy_d, TF_SESSIONS)
    grouped = {s: group_bars(df, TF_SESSIONS) for s, df in data.items()}

    rows = []
    for level, commission_pct, slippage_ticks in LEVELS:
        cfg = config_v22(trade_dir="long", use_htf_trend=False,
                          adx_min=15, rsi_long_level=50, atr_stop_mult=1.5,
                          rr_ratio=2.0,
                          commission_pct=commission_pct, slippage_ticks=slippage_ticks)
        all_tr, tested = [], 0
        for sym, df in grouped.items():
            if len(df) < MIN_BARS:
                continue
            try:
                r = run(df, spy, cfg)
            except Exception:
                continue
            tested += 1
            all_tr += [t for t in r["trades"] if t.get("pnl") is not None]
        S = stats(all_tr)
        row = {"level": level, "commission_pct": commission_pct,
               "slippage_ticks": slippage_ticks, "tested": tested, **S}
        rows.append(row)
        print(f"Level {level}  comm={commission_pct:>5.2f}%  slip={slippage_ticks} ticks  "
              f"n={S['n']:>4}  PF {S['pf']:>6}  win {S['win%']:>5}%  "
              f"expR {S['expR']:>7}  t={S['t']:>6}  net ${S['net']:>10,.0f}")

    breakeven = interpolate_breakeven(rows)
    print(f"\nBreakeven within required levels (PF crosses 1.0): {breakeven}")

    extra_rows = []
    m_lo_report = None
    if all((r["pf"] == r["pf"] and r["pf"] >= 1.0) for r in rows):
        print("\nPF never dropped below 1.0 across the required levels -- "
              "extending the search past Level 4 to find the actual breakeven...")
        extra_rows, extended_summary, m_lo_report = find_breakeven(grouped, spy, rows[-1])
        for r in sorted(extra_rows, key=lambda x: x["m"]):
            print(f"  {r['m']:>6.2f}x L4  comm={r['commission_pct']:>5.2f}%  "
                  f"slip={r['slippage_ticks']:>5.1f} ticks  n={r['n']:>4}  "
                  f"PF {r['pf']:>7}  net ${r['net']:>10,.0f}")
        breakeven = extended_summary
        print(f"\nActual breakeven: {breakeven}")

    stamp = date.today().isoformat()
    out_path = REPORTS / f"cost_stress_test_{stamp}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Cost stress test — {stamp}\n\n")
        f.write("Winner from `backtest/reports/holdout_sweep_2026-07-30.md`: "
                "`tf=3 adx_min=15 rsi_long=50 stop=1.5xATR rr=2.0`, engine "
                "`swing_pro.config_v22(trade_dir=\"long\", use_htf_trend=False, ...)`. "
                "22-symbol basket (`run_daily_30y.SYMBOLS`), full 1995-2026 daily history "
                "grouped to 3-session bars.\n\n")
        f.write("The 2026-07-30 backtest used `swing_pro.Config`'s baked-in defaults "
                "(commission_pct=0.01, slippage_ticks=1) — an idealized cost assumption. "
                "Real fills on a small Robinhood account (fractional shares, market orders, "
                "regular hours only, wide bid/ask on thin names) will be worse. This reruns "
                "the identical config at increasing commission/slippage overrides to find "
                "where the edge actually breaks.\n\n")
        f.write("| Level | commission_pct | slippage_ticks | n | PF | win% | expR | t-stat | net$ |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['level']} | {r['commission_pct']} | {r['slippage_ticks']} | "
                    f"{r['n']} | {r['pf']} | {r['win%']} | {r['expR']} | {r['t']} | "
                    f"{r['net']:,.0f} |\n")
        f.write(f"\n**Breakeven (PF crosses 1.0):** {breakeven}\n\n")
        f.write("Level 0 reproduces the 2026-07-30 backtest's cost assumption exactly "
                "(the reported PF here should match that report's full-history PF for this "
                "config). Level 4 is deliberately extreme and not a realistic execution "
                "estimate — it exists only to bound the search for the breaking point.\n")
        if extra_rows:
            f.write("\n## Extended search — PF never dropped below 1.0 through Level 4\n\n")
            f.write("The five required levels above (up to 20x baseline commission, 8x "
                    "baseline slippage) all still cleared PF 1.0, so the search was extended "
                    "by scaling the Level-4 commission/slippage pair (0.20%, 8 ticks) up by a "
                    "multiplier `m`, to actually locate where the edge dies.\n\n")
            f.write("| m (x Level 4) | commission_pct | slippage_ticks | n | PF | win% | expR | t-stat | net$ |\n")
            f.write("|---|---|---|---|---|---|---|---|---|\n")
            for r in sorted(extra_rows, key=lambda x: x["m"]):
                f.write(f"| {r['m']:.2f} | {r['commission_pct']:.3f} | {r['slippage_ticks']:.1f} | "
                        f"{r['n']} | {r['pf']} | {r['win%']} | {r['expR']} | {r['t']} | "
                        f"{r['net']:,.0f} |\n")
            f.write(f"\n**Actual breakeven:** {breakeven}\n")
            sig_rows = sorted(extra_rows, key=lambda x: x["m"])
            lost_sig = next((r for r in sig_rows if r["t"] == r["t"] and abs(r["t"]) < 2.0), None)
            last_sig = next((r for r in reversed(sig_rows) if r["t"] == r["t"] and abs(r["t"]) >= 2.0), None)
            if lost_sig and last_sig:
                f.write(f"\n**Note:** the t-stat (edge distinguishable from zero, |t|>2) drops below "
                        f"significance between m={last_sig['m']:.2f} (t={last_sig['t']}) and "
                        f"m={lost_sig['m']:.2f} (t={lost_sig['t']}) — well *before* PF nominally "
                        f"crosses 1.0 at m~{m_lo_report:.2f}. Past that point the edge is not "
                        f"reliably distinguishable from noise even though PF still reads >1.\n")
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    main()
