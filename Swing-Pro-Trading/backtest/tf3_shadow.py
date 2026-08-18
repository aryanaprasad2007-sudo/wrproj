"""
tf3_shadow.py — TF3 (3-session bar) SHADOW forward audition. No orders, ever.

What this tracks: the train/holdout sweep winner from run_holdout_sweep.py
(2026-07-30) — 3-trading-session bars, adx_min=15, rsi_long_level=50,
atr_stop_mult=1.5, rr_ratio=2.0, on the same validated engine as the daily
flagship (swing_pro.config_v22, trade_dir="long", use_htf_trend=False).
Holdout 2015-2026 (untouched during the sweep): n=210 closed trades, PF 2.99,
win 51.4%, expR 0.648R, t=5.36. Train 1995-2015: n=313, PF 3.15, t=6.37.

Design: DETERMINISTIC DAILY RECOMPUTE (same architecture as mr_forward.py /
switch_shadow.py). Every run fetches fresh daily bars, groups them into
3-session bars with run_timeframe_scan.group_bars (imported, not
reimplemented — the exact grouping the sweep was scored on), and re-runs
swing_pro.run as a 22-symbol portfolio from AUDITION_START. No persisted
engine state, so the tracker can never drift from the validated config.
Outputs are rewritten wholesale each run (idempotent):
  reports/tf3_shadow.md      — audition dashboard
  tf3_shadow_trades.csv      — closed shadow trades
  tf3_shadow_equity.csv      — daily shadow equity curve
Sizing contract: $100k pool, 10% per position, max 10 concurrent — identical
to switch_shadow.py. Caveat as the other shadows: yfinance may retro-adjust
bars on splits/dividends, which can re-decide a marginal past signal;
tolerable for a shadow audition and visible in the trades CSV diff if it
ever happens.

BENCHMARK (pre-registered from the holdout window, run_holdout_sweep.py
2026-07-30): PF 2.99, win 51.4%, expR 0.648R, t=5.36, n=210. Judge at >=30
closed shadow trades (house rule 3 — this floor is NOT one of the rules Ari
asked to loosen for research exploration; it stays put).

THIS SCRIPT MUST NEVER PLACE A REAL OR PAPER ORDER. Shadow-only, same as
mr_forward.py and switch_shadow.py — no broker calls of any kind.

Scheduled: not yet registered — see reports/tf3_shadow_setup_note.md for the
schtasks command to run.
Usage:  py tf3_shadow.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from run_timeframe_scan import group_bars
from swing_pro import config_v22, run
from run_daily_30y import SYMBOLS

HERE = Path(__file__).parent
REPORTS = HERE / "reports"
AUDITION_START = pd.Timestamp("2026-07-31")   # first live signal date
FETCH_START = "2023-01-01"                    # ~3.5y raw sessions -> ample warmup once grouped
TF_SESSIONS = 3                               # the sweep winner's timeframe
MIN_GROUPED_BARS = 60                         # safety floor above trend_len=50 / imp_len=34
INIT, ALLOC_PCT, MAX_POS = 100_000.0, 10.0, 10   # same sizing contract as switch_shadow
BENCH = {"pf": 2.99, "win_pct": 51.4, "expR": 0.648, "t": 5.36, "n": 210}


def fetch_all() -> tuple[dict[str, pd.DataFrame], pd.DataFrame | None]:
    import yfinance as yf
    raw = yf.download(" ".join(SYMBOLS + ["SPY"]), start=FETCH_START,
                      interval="1d", auto_adjust=False, progress=False,
                      group_by="ticker", threads=True)
    dfs, spy = {}, None
    for s in SYMBOLS + ["SPY"]:
        try:
            df = raw[s].rename(columns=str.lower)[
                ["open", "high", "low", "close", "volume"]].dropna(
                subset=["open", "high", "low", "close"])
            df.index = pd.DatetimeIndex(df.index).tz_localize(None)
            if len(df) < 220:
                print(f"  {s}: only {len(df)} bars — skipped this run")
                continue
            if s == "SPY":
                spy = df
            else:
                dfs[s] = df
        except Exception as e:
            print(f"  {s}: fetch failed ({e}) — skipped this run")
    return dfs, spy


def _naive(t):
    ts = pd.Timestamp(t)
    return ts.tz_localize(None) if ts.tzinfo else ts


def tf3_portfolio(dfs: dict, spy: pd.DataFrame, cfg,
                  start: pd.Timestamp) -> tuple[pd.Series, list, list]:
    """Re-run the validated engine on 3-session bars per symbol, gate entries
    to `start`, and replay the closed trades through a shared 10%/10-position
    pool — same portfolio contract as switch_shadow.momentum_portfolio."""
    g_spy = group_bars(spy, TF_SESSIONS)
    grouped = {s: group_bars(df, TF_SESSIONS) for s, df in dfs.items()}

    trades, open_now = [], []
    for sym, gdf in grouped.items():
        if len(gdf) < MIN_GROUPED_BARS:
            continue
        try:
            r = run(gdf, g_spy, cfg)
        except Exception as e:
            print(f"  {sym}: engine failed on grouped bars ({e}) — skipped")
            continue
        for t in r["trades"]:
            entry = _naive(t["entry_time"])
            if entry < start:
                continue
            if t.get("pnl") is None or not t.get("qty"):
                open_now.append({"symbol": sym, "side": t.get("side"),
                                 "entry": entry.date().isoformat(),
                                 "entry_fill": t.get("entry_fill")})
                continue
            notional = float(t["entry_fill"]) * float(t["qty"])
            if notional <= 0:
                continue
            reason = t["exits"][-1][3] if t.get("exits") else None
            trades.append({"symbol": sym, "entry": entry,
                           "exit": _naive(t["exit_time"]),
                           "entry_fill": float(t["entry_fill"]),
                           "pnl": float(t["pnl"]),
                           "r": float(t["r"]) if t["r"] == t["r"] else np.nan,
                           "pct": float(t["pnl"]) / notional,
                           "reason": reason})

    entries_by, exits_by = {}, {}
    for i, t in enumerate(trades):
        entries_by.setdefault(t["entry"], []).append(i)
        exits_by.setdefault(t["exit"], []).append(i)

    calendar = sorted(d for d in set().union(
        *[set(df.index) for df in grouped.values()]) if d >= start) \
        if grouped else []
    closes = {s: df["close"] for s, df in grouped.items()}

    def mark(sym, ts, fallback):
        try:
            return float(closes[sym].loc[ts])
        except KeyError:
            return fallback

    cash, open_pos = INIT, {}
    eq_vals, eq_dates = [], []
    for ts in calendar:
        for i in exits_by.get(ts, []):
            if i in open_pos:
                p = open_pos.pop(i)
                notional = p["entry_fill"] * p["qshares"]
                cash += notional + notional * trades[i]["pct"]
        marked = cash + sum(p["qshares"] * mark(p["symbol"], ts, p["entry_fill"])
                            for p in open_pos.values())
        for i in sorted(entries_by.get(ts, []), key=lambda k: trades[k]["symbol"]):
            if len(open_pos) >= MAX_POS:
                break
            notional = (ALLOC_PCT / 100.0) * marked
            if notional <= 0 or notional > cash:
                continue
            cash -= notional
            open_pos[i] = {"symbol": trades[i]["symbol"],
                           "qshares": notional / max(trades[i]["entry_fill"], 1e-9),
                           "entry_fill": trades[i]["entry_fill"]}
        mv = sum(p["qshares"] * mark(p["symbol"], ts, p["entry_fill"])
                 for p in open_pos.values())
        eq_vals.append(cash + mv)
        eq_dates.append(ts)
    eq = pd.Series(eq_vals, index=pd.DatetimeIndex(eq_dates), name="equity")
    return eq, trades, open_now


def main():
    REPORTS.mkdir(exist_ok=True)
    dfs, spy = fetch_all()
    if not dfs or spy is None:
        print("no data — aborting without touching outputs")
        return
    last_bar = max(d.index[-1] for d in dfs.values())
    cfg = config_v22(trade_dir="long", use_htf_trend=False, adx_min=15,
                     rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0)
    eq, closed, open_now = tf3_portfolio(dfs, spy, cfg, AUDITION_START)

    pd.DataFrame(closed).to_csv(HERE / "tf3_shadow_trades.csv", index=False)
    eq.to_csv(HERE / "tf3_shadow_equity.csv")

    live = last_bar >= AUDITION_START
    p = np.array([t["pnl"] for t in closed])
    r = np.array([t["r"] for t in closed if t["r"] == t["r"]])
    w, l = (p[p > 0], p[p <= 0]) if len(p) else (np.array([]), np.array([]))
    pf = float(w.sum() / -l.sum()) if len(l) and l.sum() < 0 else np.nan
    t_stat = (float(r.mean()) / (float(r.std(ddof=1)) / np.sqrt(len(r)))
              if len(r) > 2 and r.std(ddof=1) > 0 else np.nan)
    stats = {
        "closed": len(p), "net": round(float(p.sum())) if len(p) else 0,
        "pf": round(pf, 2) if not np.isnan(pf) else "n/a",
        "win%": round(100 * len(w) / len(p), 1) if len(p) else "n/a",
        "expR": round(float(r.mean()), 3) if len(r) else "n/a",
        "t": round(t_stat, 2) if t_stat == t_stat else "n/a",
    }
    judged = len(p) >= 30
    reasons = pd.Series([t["reason"] for t in closed if t["reason"]]) \
        .value_counts().to_dict() if closed else {}

    out = REPORTS / "tf3_shadow.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# TF3 shadow forward audition — refreshed {date.today().isoformat()}\n\n")
        f.write(f"Status: **{'LIVE' if live else 'ARMED'}** · audition start "
                f"{AUDITION_START.date()} · last completed bar {last_bar.date()} · "
                f"{len(dfs)}/{len(SYMBOLS)} symbols loaded · SHADOW ONLY — no orders.\n\n")
        f.write("Config: `swing_pro.config_v22(trade_dir=\"long\", use_htf_trend=False, "
                "adx_min=15, rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0)` on "
                "3-trading-session bars (`run_timeframe_scan.group_bars`), 22-symbol "
                "basket — the train/holdout sweep winner "
                "(reports/holdout_sweep_2026-07-30.md).\n\n")
        f.write(f"Benchmark (pre-registered, holdout 2015-2026, n={BENCH['n']}): "
                f"PF {BENCH['pf']}, win {BENCH['win_pct']}%, expR {BENCH['expR']}R, "
                f"t={BENCH['t']}. Judge at ≥30 closed shadow trades — "
                f"{'REACHED' if judged else f'{len(p)}/30'}.\n\n")
        f.write("## Shadow book vs benchmark\n\n")
        f.write(pd.DataFrame([{"": "shadow", **stats},
                              {"": "benchmark (holdout)", "closed": BENCH["n"],
                               "net": "—", "pf": BENCH["pf"], "win%": BENCH["win_pct"],
                               "expR": BENCH["expR"], "t": BENCH["t"]}])
                .to_markdown(index=False))
        if reasons:
            f.write(f"\n\nExit mix: {reasons}")
        if live and len(eq):
            peak = eq.cummax()
            dd = float(((eq - peak) / peak).min() * 100) if len(eq) > 1 else 0.0
            f.write(f"\n\nShadow equity: ${eq.iloc[-1]:,.0f} (start $100,000)"
                    f" · max DD {dd:.1f}%")
        f.write("\n\n## Open shadow positions\n\n")
        f.write(pd.DataFrame(open_now).to_markdown(index=False)
                if open_now else "*(none)*")
        f.write("\n\n*Deterministic recompute from audition start each run; engine = "
                "swing_pro.py config_v22 exactly as validated in the holdout sweep. "
                "Not financial advice.*\n")

    print(f"TF3 shadow: {'LIVE' if live else 'ARMED'} · last bar {last_bar.date()} · "
          f"{stats['closed']} closed (PF {stats['pf']}, t={stats['t']}) · "
          f"{len(open_now)} open")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
