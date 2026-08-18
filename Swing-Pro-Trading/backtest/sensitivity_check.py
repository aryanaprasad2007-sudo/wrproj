"""
sensitivity_check.py — local parameter-sensitivity check around the
2026-07-30 train/holdout sweep winner.

The winner (tf=3, adx_min=15, rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0)
sat at the EDGE of the tested grid on adx_min, rsi_long_level and rr_ratio —
a classic overfitting red flag. This script does not re-run the search. It
holds the winner fixed on four of five parameters, nudges the fifth across a
small local grid, and asks one question per parameter: does performance move
SMOOTHLY as the parameter changes (a plateau — the winner is one point on a
broad region of edge, not a lucky spike), or does it fall off a CLIFF right
next to the winning value (the original grid search likely got lucky at that
exact point)?

Uses the FULL 30-year dataset (1995-2026, no train/holdout split) — this is
about local robustness, not selection, so there is nothing to protect by
holding out data.

Usage:  py sensitivity_check.py
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

WINNER = {"tf": 3, "adx_min": 15, "rsi_long_level": 50,
          "atr_stop_mult": 1.5, "rr_ratio": 2.0}

# param -> local grid to sweep, holding the other four at the WINNER values
PARAM_GRIDS = {
    "adx_min":        [10, 12, 15, 18, 20, 25],
    "rsi_long_level": [45, 48, 50, 52, 55],
    "atr_stop_mult":  [1.0, 1.25, 1.5, 1.75, 2.0],
    "rr_ratio":       [1.5, 1.75, 2.0, 2.25, 2.5, 3.0],
    "tf":             [2, 3, 4, 5],
}

# cliff-detection thresholds
T_SIG = 2.0            # |t| below this is "not distinguishable from zero"
REL_DROP_CLIFF = 0.40  # >40% relative drop in t-stat between adjacent grid points = cliff


def stats(trades: list) -> dict:
    p = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    R = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    if not len(p):
        return {"n": 0, "pf": np.nan, "win%": np.nan, "expR": np.nan, "t": np.nan, "net": 0.0}
    w, l = p[p > 0], p[p <= 0]
    t = (float(R.mean()) / (float(R.std(ddof=1)) / np.sqrt(len(R)))
         if len(R) > 2 and R.std(ddof=1) > 0 else np.nan)
    return {"n": int(len(p)),
            "pf": round(float(w.sum() / -l.sum()), 3) if len(l) and l.sum() < 0 else np.nan,
            "win%": round(100 * len(w) / len(p), 1),
            "expR": round(float(R.mean()), 4) if len(R) else np.nan,
            "t": round(t, 2) if t == t else np.nan,
            "net": round(float(p.sum()))}


def run_config(dfs: dict, spy: pd.DataFrame, params: dict) -> dict:
    cfg = config_v22(trade_dir="long", use_htf_trend=False,
                      adx_min=params["adx_min"],
                      rsi_long_level=params["rsi_long_level"],
                      atr_stop_mult=params["atr_stop_mult"],
                      rr_ratio=params["rr_ratio"])
    all_tr, tested, profitable = [], 0, 0
    for sym, df in dfs.items():
        if len(df) < MIN_BARS:
            continue
        try:
            r = run(df, spy, cfg)
        except Exception:
            continue
        tested += 1
        tr = [t for t in r["trades"] if t.get("pnl") is not None]
        all_tr += tr
        if sum(t["pnl"] for t in tr) > 0:
            profitable += 1
    s = stats(all_tr)
    s["breadth"] = f"{profitable}/{tested}"
    return s


def classify(param: str, values: list, s_by_value: dict) -> tuple[str, str]:
    """Compare the winner's t-stat to its immediate grid neighbors."""
    win_val = WINNER[param]
    if win_val not in values:
        return "n/a", "winning value not in local grid"
    idx = values.index(win_val)
    win_t = s_by_value[win_val]["t"]
    if win_t != win_t:  # nan
        return "n/a", "winner has no valid t-stat here"

    notes = []
    cliff = False
    for nb_idx in (idx - 1, idx + 1):
        if not (0 <= nb_idx < len(values)):
            continue
        nb_val = values[nb_idx]
        nb_t = s_by_value[nb_val]["t"]
        side = "below" if nb_val < win_val else "above"
        if nb_t != nb_t:
            notes.append(f"{side} neighbor ({param}={nb_val}) has no valid t-stat")
            continue
        rel_drop = (win_t - nb_t) / abs(win_t) if win_t else np.nan
        crossed_sig = win_t >= T_SIG and nb_t < T_SIG
        if (rel_drop == rel_drop and rel_drop > REL_DROP_CLIFF) or crossed_sig:
            cliff = True
            notes.append(f"{side} neighbor ({param}={nb_val}): t {win_t}->{nb_t} "
                         f"({rel_drop*100:+.0f}%){' — crosses significance' if crossed_sig else ''}")
        else:
            notes.append(f"{side} neighbor ({param}={nb_val}): t {win_t}->{nb_t} "
                         f"({rel_drop*100:+.0f}%)" if rel_drop == rel_drop else
                         f"{side} neighbor ({param}={nb_val}): t stable")
    verdict = "cliff — treat the original winner with more caution" if cliff else "smooth/plateau"
    return verdict, "; ".join(notes)


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

    # pre-group bars for every tf value this sweep will need
    needed_tfs = sorted(set(PARAM_GRIDS["tf"]) | {WINNER["tf"]})
    grouped = {n: ({s: group_bars(df, n) for s, df in data.items()},
                   group_bars(spy_d, n)) for n in needed_tfs}
    print(f"grouped bars for tf {needed_tfs}\n")

    report_sections = []
    for param, values in PARAM_GRIDS.items():
        print(f"=== {param} ===")
        s_by_value = {}
        rows = []
        for v in values:
            params = dict(WINNER)
            params[param] = v
            n = params["tf"]
            dfs, spy = grouped[n]
            s = run_config(dfs, spy, params)
            s_by_value[v] = s
            marker = "  <- winner" if v == WINNER[param] else ""
            rows.append({param: v, "n": s["n"], "win%": s["win%"], "pf": s["pf"],
                         "expR": s["expR"], "t": s["t"], "breadth": s["breadth"]})
            print(f"  {param}={v:<6} n={s['n']:>4}  win {s['win%']:>5}%  "
                  f"PF {s['pf']:>6}  expR {s['expR']:>7}  t={s['t']:>6}  "
                  f"breadth {s['breadth']}{marker}")
        verdict, note = classify(param, values, s_by_value)
        print(f"  VERDICT: {verdict}  ({note})\n")
        df_out = pd.DataFrame(rows)
        report_sections.append((param, df_out, verdict, note))

    stamp = date.today().isoformat()
    f = REPORTS / f"sensitivity_check_{stamp}.md"
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(f"# Parameter sensitivity check — {stamp}\n\n")
        fh.write("Local robustness check around the 2026-07-30 train/holdout sweep winner "
                 "(`tf=3 adx_min=15 rsi_long=50 stop=1.5xATR rr=2.0`), which sat at the edge "
                 "of the tested grid on `adx_min`, `rsi_long_level` and `rr_ratio` — a known "
                 "overfitting red flag. Each parameter below is varied locally while the "
                 "other four are held at the winner's values, on the FULL 30-year dataset "
                 "(no train/holdout split — this checks robustness, not selection).\n\n")
        fh.write("**Read the VERDICT line.** Smooth/plateau means the winner sits on a broad "
                 "region of edge — nudging the parameter barely moves performance, so it "
                 "wasn't a lucky spike. Cliff means performance drops sharply right next to "
                 "the winning value, which means the original grid search likely got lucky "
                 "landing exactly there.\n\n")
        for param, df_out, verdict, note in report_sections:
            fh.write(f"## {param}\n\n")
            fh.write(df_out.to_markdown(index=False))
            fh.write(f"\n\n**VERDICT: {verdict}**  \n{note}\n\n")
        fh.write("## Summary\n\n")
        fh.write("| parameter | verdict |\n|---|---|\n")
        for param, _, verdict, _ in report_sections:
            fh.write(f"| {param} | {verdict} |\n")
    print(f"-> {f}")


if __name__ == "__main__":
    main()
