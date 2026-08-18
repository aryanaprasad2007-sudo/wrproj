# Forward-test weekly review — 2026-07-31

Venue: **Webull PAPER (UAT)**

## Verdict

**TOO EARLY TO JUDGE (2/30 closed trades). Keep running.**

Variance context (Monte Carlo): current losing streak 1 (normal up to 12); a window net down to $-1,030 is normal; 17.5% of 6-week windows lose money even when the system works.

| metric | actual | benchmark |
|---|---|---|
| Equity | $2,000 sim book | scored from fills/levels — the shared Webull UAT balance is not meaningful |
| Closed trades | 2 | judge at ≥30 |
| Win rate | 0.0% | ~48% |
| Profit factor | 0.00 | 1.3 |
| Trades/week | 0.6 | ~8.4 |
| Median slippage/share | $0.2800 | $0.01 assumed in backtest |

## Basket vs basket (the universe-scan question)

| basket | closed | net | PF | benchmark PF |
|---|---|---|---|---|
| current | 1 | $0 | inf | 1.3 |
| candidate | 1 | $-6 | 0.00 | 1.4 |

## Closed round-trips

| symbol   | entry_ts            | exit_ts             |   qty |    pnl | events          |
|:---------|:--------------------|:--------------------|------:|-------:|:----------------|
| NVDA     | 2026-07-14T10:00:12 | 2026-07-15T09:33:14 |     2 | nan    | ['BUY', 'STOP'] |
| MSTR     | 2026-07-21T12:40:14 | 2026-07-22T11:17:30 |     4 |  -6.03 | ['BUY', 'STOP'] |

## Still open: NVDA, AAPL

## DAILY track — iAPE-D on the control basket

Queued signals to date: 5 · fills: 3 · expired/skipped: 1 · still open: UNH, JPM, CVX

No closed daily trades yet — at ~0.4/wk that is expected for the first weeks.

## STRICT shadow track (same 7 indicators, tighter gates — hypothetical, not traded)

1 closed shadow trades · win rate 0.0% · net -2.81 per share-unit. Promotion bar: beat live v2.2 on BOTH win rate and per-share expectancy over ≥30 shadow trades — judged on live prices, never on the retired backtest data.

*Benchmark pre-registered 2026-07-02 from the 2y variant-B backtest. Not financial advice.*
