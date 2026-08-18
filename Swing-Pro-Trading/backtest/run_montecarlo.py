"""
run_montecarlo.py — the variance map: what does v2.2 look like when it's
WORKING and you're just unlucky?

Takes the 857-trade v2.2 record (10 symbols, 2y), shuffles/bootstraps it
10,000 times, and maps the distribution of pain that pure sequencing produces:
max losing streaks, drawdowns, time underwater — full-sample AND for 50-trade
windows (≈ one 6-week forward-test judgment period).

This is a legitimate use of retired data: it characterizes VARIANCE, it does
not select edge. Payoff is behavioral — when the forward test hits a losing
streak, these numbers say whether that's normal weather or a broken system.

Usage:  py run_montecarlo.py     (also prints the thresholds to embed in the
                                  Friday review)
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import config_v22, run

SYMBOLS = ["AAPL", "NVDA", "TSLA", "MSFT", "META",
           "MSTR", "ORCL", "NFLX", "AVGO", "CRWD"]
REPORTS = Path(__file__).parent / "reports"
N_SIM = 10_000
WINDOW = 50           # ≈ 6 weeks at ~8.4 trades/week
START_EQ = 100_000.0
rng = np.random.default_rng(7)


def max_losing_streak(wins: np.ndarray) -> int:
    worst = cur = 0
    for w in wins:
        cur = 0 if w else cur + 1
        worst = max(worst, cur)
    return worst


def dd_stats(pnls: np.ndarray):
    eq = START_EQ + np.cumsum(pnls)
    peak = np.maximum.accumulate(np.concatenate(([START_EQ], eq)))
    dd = (np.concatenate(([START_EQ], eq)) - peak) / peak
    # time underwater: longest run of bars below prior peak
    under = dd < 0
    worst = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        worst = max(worst, cur)
    return float(dd.min() * 100), worst


def main():
    REPORTS.mkdir(exist_ok=True)
    print("Collecting v2.2 trade record (cached) ...")
    spy = load_bars("SPY", 730)
    cfg = config_v22(trade_dir="long")
    pnls = []
    for s in SYMBOLS:
        pnls += [t["pnl"] for t in run(load_bars(s, 730), spy, cfg)["trades"]]
    pnls = np.array(pnls)
    wins = pnls > 0
    print(f"  {len(pnls)} trades, win rate {wins.mean() * 100:.1f}%, "
          f"net ${pnls.sum():,.0f}")

    # ── full-record shuffles ──────────────────────────────────────────────────
    streaks, dds, unders = [], [], []
    for _ in range(N_SIM):
        idx = rng.permutation(len(pnls))
        streaks.append(max_losing_streak(wins[idx]))
        d, u = dd_stats(pnls[idx])
        dds.append(d)
        unders.append(u)
    streaks, dds, unders = map(np.array, (streaks, dds, unders))

    # ── 50-trade bootstrap windows (one judgment period) ─────────────────────
    w_net, w_streak, w_dd = [], [], []
    for _ in range(N_SIM):
        idx = rng.integers(0, len(pnls), WINDOW)
        p = pnls[idx]
        w_net.append(p.sum())
        w_streak.append(max_losing_streak(p > 0))
        d, _ = dd_stats(p)
        w_dd.append(d)
    w_net, w_streak, w_dd = map(np.array, (w_net, w_streak, w_dd))

    def pct(a, q):
        return float(np.percentile(a, q))

    out = REPORTS / f"montecarlo_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Monte Carlo variance map — {date.today().isoformat()}\n\n")
        f.write(f"{len(pnls)} v2.2 trades · {N_SIM:,} shuffles · flat sizing on "
                f"$100k. **This maps the pain the system produces even when it is "
                f"working.**\n\n")
        f.write("## Full record (857-trade horizon)\n\n")
        f.write("| metric | median | 95th pct | 99th pct |\n|---|---|---|---|\n")
        f.write(f"| Max losing streak | {pct(streaks, 50):.0f} | {pct(streaks, 95):.0f} "
                f"| {pct(streaks, 99):.0f} |\n")
        f.write(f"| Max drawdown | {pct(dds, 50):.2f}% | {pct(dds, 5):.2f}% "
                f"| {pct(dds, 1):.2f}% |\n")
        f.write(f"| Longest underwater (trades) | {pct(unders, 50):.0f} | "
                f"{pct(unders, 95):.0f} | {pct(unders, 99):.0f} |\n\n")
        f.write(f"## One judgment window ({WINDOW} trades ≈ 6 weeks)\n\n")
        f.write("| metric | 5th pct | median | 95th pct |\n|---|---|---|---|\n")
        f.write(f"| Net P&L | ${pct(w_net, 5):,.0f} | ${pct(w_net, 50):,.0f} | "
                f"${pct(w_net, 95):,.0f} |\n")
        f.write(f"| Max losing streak | {pct(w_streak, 5):.0f} | {pct(w_streak, 50):.0f} "
                f"| {pct(w_streak, 95):.0f} |\n")
        f.write(f"| Max drawdown | {pct(w_dd, 5):.2f}% | {pct(w_dd, 50):.2f}% | "
                f"{pct(w_dd, 95):.2f}% |\n\n")
        f.write(f"**Panic thresholds (pre-registered):** a losing streak up to "
                f"**{pct(w_streak, 95):.0f}** or a window net as low as "
                f"**${pct(w_net, 5):,.0f}** is NORMAL VARIANCE for a working v2.2 — "
                f"not evidence of failure. Only beyond these does the forward test "
                f"say something is actually wrong. Chance a working system still "
                f"loses money over {WINDOW} trades: "
                f"{float((w_net < 0).mean() * 100):.1f}%.\n\n")
        f.write("*Bootstrap assumes trade independence; real trades cluster by "
                "regime, so true tails are somewhat fatter. Not financial advice.*\n")
    print(f"\nPanic thresholds -> streak {pct(w_streak, 95):.0f}, "
          f"window net 5th pct ${pct(w_net, 5):,.0f}, "
          f"P(losing 50-trade window) {float((w_net < 0).mean() * 100):.1f}%")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
