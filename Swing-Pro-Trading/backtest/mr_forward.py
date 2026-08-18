"""
mr_forward.py — MR-1 SHADOW forward audition (Chat C). No orders, ever.

Why shadow, not paper orders: MR-1's validated 22-name universe overlaps BOTH
live order tracks in the shared Alpaca paper account (all 13 daily-track
control names, plus AAPL/NVDA/MSFT/ORCL from the intraday 10). Real MR orders
would fight two reconcilers. Shadow keeps the validated universe intact; the
promotion path to real paper orders is a symbol-ownership partition, decided
at graduation.

Design: DETERMINISTIC DAILY RECOMPUTE. No persisted engine state — every run
re-executes mean_rev.run_portfolio from AUDITION_START on freshly fetched
bars (warmup bars before the start only feed indicators; `start=` blocks
entries). The tracker can therefore never drift from the validated engine.
Outputs are rewritten wholesale each run (idempotent):
  reports/mr_forward.md      — audition dashboard
  mr_forward_trades.csv      — closed shadow trades
  mr_forward_equity.csv      — daily shadow equity curve
Caveat accepted: yfinance may retro-adjust bars on splits/dividends, which can
re-decide a marginal past signal; tolerable for a shadow audition and visible
in the trades CSV diff if it ever happens.

BENCHMARK (pre-registered from the modern decade of the validated baseline,
reports/mr_baseline_2026-07-05.md, D3 2015-2026): PF 1.21, ~1.8 trades/wk,
+0.34%/trade, 64% win. Judge at >= 30 closed shadow trades (house rule 3).

Scheduled: SwingPro_MR_Shadow, daily 13:40 PT (after the close; after every
other SwingPro task). Weekend/holiday runs are harmless no-ops.
Usage:  py mr_forward.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from mean_rev import MRConfig, run_portfolio, curve_stats
from run_daily_30y import SYMBOLS

HERE = Path(__file__).parent
REPORTS = HERE / "reports"
AUDITION_START = pd.Timestamp("2026-07-06")   # first live signal date
FETCH_START = "2025-05-01"                    # ~290 sessions of SMA200 warmup
BENCH = {"pf": 1.21, "trades_per_wk": 1.8, "exp_pct": 0.34, "win_pct": 64.0}


def fetch_all() -> dict[str, pd.DataFrame]:
    import yfinance as yf
    raw = yf.download(" ".join(SYMBOLS), start=FETCH_START, interval="1d",
                      auto_adjust=False, progress=False, group_by="ticker",
                      threads=True)
    dfs = {}
    for s in SYMBOLS:
        try:
            df = raw[s].rename(columns=str.lower)[
                ["open", "high", "low", "close", "volume"]].dropna(
                subset=["open", "high", "low", "close"])
            df.index = pd.DatetimeIndex(df.index).tz_localize(None)
            if len(df) >= 220:                # enough warmup to trade
                dfs[s] = df
            else:
                print(f"  {s}: only {len(df)} bars — skipped this run")
        except Exception as e:
            print(f"  {s}: fetch failed ({e}) — skipped this run")
    return dfs


def main():
    REPORTS.mkdir(exist_ok=True)
    dfs = fetch_all()
    if not dfs:
        print("no data at all — aborting without touching outputs")
        return
    last_bar = max(d.index[-1] for d in dfs.values())
    cfg = MRConfig()
    res = run_portfolio(dfs, cfg, start=AUDITION_START)
    closed = [t for t in res["trades"] if t["reason"] != "end_of_data"]
    eq = res["equity"][res["equity"].index >= AUDITION_START]

    # ── outputs (deterministic, rewritten wholesale) ─────────────────────────
    pd.DataFrame(closed).to_csv(HERE / "mr_forward_trades.csv", index=False)
    eq.rename("equity").to_csv(HERE / "mr_forward_equity.csv")

    live = last_bar >= AUDITION_START
    weeks = max(((last_bar - AUDITION_START).days + 1) / 7.0, 1e-9)
    p = np.array([t["pnl"] for t in closed])
    w, l = (p[p > 0], p[p <= 0]) if len(p) else (np.array([]), np.array([]))
    pf = float(w.sum() / -l.sum()) if len(l) and l.sum() < 0 else np.nan
    stats = {
        "closed": len(p), "net": round(float(p.sum())) if len(p) else 0,
        "pf": round(pf, 2) if not np.isnan(pf) else "n/a",
        "win%": round(100 * len(w) / len(p), 1) if len(p) else "n/a",
        "exp%": round(float(np.mean([t["pct"] for t in closed])), 3) if closed else "n/a",
        "trades/wk": round(len(p) / weeks, 2) if live else 0.0,
    }
    judged = len(p) >= 30
    reasons = pd.Series([t["reason"] for t in closed]).value_counts().to_dict() \
        if closed else {}

    out = REPORTS / "mr_forward.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# MR-1 shadow forward audition — refreshed {date.today().isoformat()}\n\n")
        f.write(f"Status: **{'LIVE' if live else 'ARMED'}** · audition start "
                f"{AUDITION_START.date()} · last completed bar {last_bar.date()} · "
                f"{len(dfs)}/{len(SYMBOLS)} symbols loaded · SHADOW ONLY — no orders.\n\n")
        f.write(f"Benchmark (pre-registered, D3 of the validated baseline): "
                f"PF {BENCH['pf']}, ~{BENCH['trades_per_wk']}/wk, "
                f"+{BENCH['exp_pct']}%/trade, {BENCH['win_pct']}% win. "
                f"Judge at ≥30 closed — {'REACHED' if judged else f'{len(p)}/30'}.\n\n")
        f.write("## Shadow book vs benchmark\n\n")
        f.write(pd.DataFrame([{"": "shadow", **stats},
                              {"": "benchmark", "closed": "≥30", "net": "—",
                               "pf": BENCH["pf"], "win%": BENCH["win_pct"],
                               "exp%": BENCH["exp_pct"],
                               "trades/wk": BENCH["trades_per_wk"]}])
                .to_markdown(index=False))
        if reasons:
            f.write(f"\n\nExit mix: {reasons}")
        if live and len(eq):
            cs = curve_stats(eq, cfg.initial_capital) if len(eq) > 1 else {}
            f.write(f"\n\nShadow equity: ${eq.iloc[-1]:,.0f} (start $100,000)"
                    + (f" · max DD {cs.get('max_dd%', 'n/a')}%" if cs else ""))
        f.write("\n\n## Open shadow positions\n\n")
        f.write(pd.DataFrame(res["open_at_end"]).to_markdown(index=False)
                if res["open_at_end"] else "*(none)*")
        f.write("\n\n## Queued for next open\n\n")
        entries = pd.DataFrame(res["queued_at_end"])
        f.write(entries.to_markdown(index=False) if len(entries) else "*(no entries)*")
        if res["exits_queued_at_end"]:
            f.write(f"\n\nExits queued: {res['exits_queued_at_end']}")
        f.write("\n\n*Deterministic recompute from audition start each run; "
                "engine = mean_rev.py exactly as validated. Not financial advice.*\n")

    print(f"MR shadow: {'LIVE' if live else 'ARMED'} · last bar {last_bar.date()} · "
          f"{stats['closed']} closed (PF {stats['pf']}) · "
          f"{len(res['open_at_end'])} open · {len(res['queued_at_end'])} queued")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
