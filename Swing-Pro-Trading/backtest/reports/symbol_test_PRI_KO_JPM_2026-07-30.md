# Single-symbol test — live daily config — 2026-07-30

Engine + config identical to the live daily track (config_v22, long-only, use_htf_trend=False, pure stop + 3R). yfinance daily bars.

**Read this as a sanity check, not a validation.** One symbol is a small sample, the portfolio logic does nothing at n=1, and the registered PF 1.72 benchmark belongs to the 13-name control basket, not to any single name.

| symbol   | since      |   years |   trades_per_yr |   full_n |   full_net |   full_win% |   full_pf |   full_expR |   h1_n |   h1_net |   h1_win% |   h1_pf |   h1_expR |   h2_n |   h2_net |   h2_win% |   h2_pf |   h2_expR |     px |   vol60d |   dollar_vol_m |   range_pct |
|:---------|:-----------|--------:|----------------:|---------:|-----------:|------------:|----------:|------------:|-------:|---------:|----------:|--------:|----------:|-------:|---------:|----------:|--------:|----------:|-------:|---------:|---------------:|------------:|
| PRI      | 2010-04-01 |    16.3 |            1.84 |       30 |      13079 |        50   |      2.88 |       0.362 |     12 |     6017 |      66.7 |    6.27 |     0.455 |     18 |     7062 |      38.9 |    2.22 |     0.301 | 323.32 |   194721 |           55.6 |        2.15 |
| KO       | 2010-01-04 |    16.6 |            1.51 |       25 |       3805 |        44   |      1.69 |       0.478 |     14 |      416 |      35.7 |    1.13 |     0.364 |     11 |     3388 |      54.5 |    2.41 |     0.624 |  88.49 | 17803543 |         1453.6 |        1.83 |
| JPM      | 2010-01-04 |    16.6 |            1.75 |       29 |       7877 |        44.8 |      2.17 |       0.204 |     17 |     1393 |      47.1 |    1.32 |     0.17  |     12 |     6483 |      41.7 |    3.81 |     0.252 | 350.85 |  9465333 |         3060.2 |        2.09 |
