# Monte Carlo variance map — 2026-07-02

857 v2.2 trades · 10,000 shuffles · flat sizing on $100k. **This maps the pain the system produces even when it is working.**

## Full record (857-trade horizon)

| metric | median | 95th pct | 99th pct |
|---|---|---|---|
| Max losing streak | 13 | 18 | 22 |
| Max drawdown | -2.24% | -3.46% | -4.31% |
| Longest underwater (trades) | 115 | 218 | 280 |

## One judgment window (50 trades ≈ 6 weeks)

| metric | 5th pct | median | 95th pct |
|---|---|---|---|
| Net P&L | $-1,030 | $1,557 | $5,055 |
| Max losing streak | 4 | 7 | 12 |
| Max drawdown | -1.91% | -0.91% | -0.45% |

**Panic thresholds (pre-registered):** a losing streak up to **12** or a window net as low as **$-1,030** is NORMAL VARIANCE for a working v2.2 — not evidence of failure. Only beyond these does the forward test say something is actually wrong. Chance a working system still loses money over 50 trades: 17.5%.

*Bootstrap assumes trade independence; real trades cluster by regime, so true tails are somewhat fatter. Not financial advice.*
