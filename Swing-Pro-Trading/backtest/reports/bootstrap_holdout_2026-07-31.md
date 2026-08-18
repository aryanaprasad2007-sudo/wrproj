# Bootstrap CI on the holdout winner — 2026-07-31

Reproduces the 2015-2026 holdout trade set for the train-sweep winner from 2026-07-30 (`run_holdout_sweep.py`) and bootstraps it 10,000 times (resample-with-replacement) to put an uncertainty band on the point-estimate expectancy and profit factor.

**Config:** 3-trading-session bars, adx_min=15, rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0, trade_dir="long", use_htf_trend=False

## Reproduced holdout sample

- Trades (entry_time >= 2015-01-01): **n=210**
- Point-estimate expectancy: **0.6484R**
- Point-estimate profit factor: **2.803**

## Bootstrap (10,000 resamples, resample-with-replacement, n=210 per resample)

| metric | 5th pct | median | 95th pct |
|---|---|---|---|
| Expectancy (mean R) | 0.4518 | 0.6475 | 0.8514 |
| Profit factor | 2.133 | 2.800 | 3.666 |

**P(expectancy <= 0) = 0.00%** — the fraction of resamples where the edge would have been zero or negative.

**Zero/negative expectancy is OUTSIDE the 90% confidence interval.**

The bootstrap does not overlap zero at the 90% level — under this resampling, the edge on the holdout sample looks real, not noise.

*Bootstrap assumes trade independence; real trades cluster by regime and symbol, so true tails are somewhat fatter than shown here. Not financial advice. No trades were placed in producing this report.*
