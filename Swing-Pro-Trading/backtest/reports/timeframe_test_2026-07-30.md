# Timeframe test — does a longer chart actually help? — 2026-07-30

Same engine + config as the 30-year deep test (config_v22, long-only, use_htf_trend=False), same 22-symbol basket, daily bars resampled to each timeframe. SPY resampled identically so the market filter stays honest.

**Read BREADTH, not profit factor.** Aggregate PF can be carried by one monster trade; breadth (how many of the 22 symbols are individually profitable) cannot. Longer timeframes mechanically produce fewer trades, and fewer trades produce more extreme numbers in BOTH directions — that is variance, not edge.

| timeframe   |   trades |   win% |   pf |   expR |    net | symbols_profitable   |   breadth% |   trades_per_symbol |
|:------------|---------:|-------:|-----:|-------:|-------:|:---------------------|-----------:|--------------------:|
| 1D          |     1090 |   42.1 | 1.96 |  0.426 | 478666 | 22/22                |      100   |                49.5 |
| 1W          |      267 |   55.8 | 5.23 |  1.109 | 815569 | 22/22                |      100   |                12.1 |
| 2W          |      148 |   60.1 | 6.15 |  1.45  | 628764 | 20/22                |       90.9 |                 6.7 |
| 3W          |       99 |   58.6 | 7.25 |  1.797 | 655840 | 20/22                |       90.9 |                 4.5 |
| 1M          |       82 |   62.2 | 8.57 |  1.738 | 607054 | 21/22                |       95.5 |                 3.7 |
