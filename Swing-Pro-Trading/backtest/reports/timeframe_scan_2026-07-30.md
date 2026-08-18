# Timeframe scan — 2026-07-30

Same engine/config as the 30y deep test, 22-symbol basket, daily bars grouped into N-session bars. **Cannot scan below 1 day** — the dataset is daily and resampling only goes coarser.

**Read `t_stat`, not `net$`.** t = mean(R)/(std(R)/sqrt(n)) — it asks whether expectancy is distinguishable from zero, and it penalises small samples automatically. Raw PnL and profit factor do not: both rise as the sample shrinks, because fewer trades means more extreme outcomes in BOTH directions. Choosing the timeframe with the biggest PnL is choosing the luckiest sample.

| tf   |   sessions/bar |   trades |   per_symbol |   win% |    pf |   expR |   t_stat |   net$ | breadth   |   breadth% |
|:-----|---------------:|---------:|-------------:|-------:|------:|-------:|---------:|-------:|:----------|-----------:|
| 1D   |              1 |     1090 |         49.5 |   42.1 |  1.96 |  0.426 |     5.97 | 478666 | 22/22     |      100   |
| 2D   |              2 |      597 |         27.1 |   46.6 |  2.99 |  0.656 |     6.24 | 674531 | 21/22     |       95.5 |
| 3D   |              3 |      418 |         19   |   50   |  3.65 |  0.846 |     7.43 | 713225 | 22/22     |      100   |
| 1W   |              5 |      262 |         11.9 |   56.9 |  6.23 |  1.135 |     6.49 | 921414 | 20/22     |       90.9 |
| 2W   |             10 |      140 |          6.4 |   61.4 |  5.74 |  1.393 |     6.23 | 634133 | 21/22     |       95.5 |
| 3W   |             15 |      101 |          4.6 |   62.4 | 10.01 |  2.17  |     4.36 | 784625 | 21/22     |       95.5 |
| 1M   |             21 |       75 |          3.4 |   65.3 | 11.19 |  2.133 |     4.45 | 678114 | 21/22     |       95.5 |

- Highest net PnL: **1W** (n=262, t=6.49)
- Highest profit factor: **1M** (n=75, t=4.45)
- Most statistically reliable: **3D** (t=7.43, n=418)
