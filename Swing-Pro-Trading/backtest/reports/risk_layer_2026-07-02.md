# Risk & sizing layer study — 2026-07-02

857 v2.2 trades, 10 symbols, 2y. Signals frozen; only money management varies. Metric: MAR = net% / |maxDD%|.

Baseline (current live config): flat 10%, no cap, no day-stop -> net 32.74%, DD -2.24%, MAR 14.65

| rule                  |   net% |   maxDD% |   MAR |   taken |   skipped |   H1_MAR |   H2_MAR |   H1_net% |   H2_net% | beats_base_both_halves   |
|:----------------------|-------:|---------:|------:|--------:|----------:|---------:|---------:|----------:|----------:|:-------------------------|
| flat_capinf_ds0       |  32.74 |    -2.24 | 14.65 |     857 |         0 |    11.78 |     3.58 |     22.9  |      8.01 |                          |
| flat_capinf_ds1       |  32.74 |    -2.24 | 14.65 |     857 |         0 |    11.78 |     3.58 |     22.9  |      8.01 |                          |
| flat_cap5_ds0         |  30.72 |    -2.21 | 13.92 |     794 |        63 |    10.99 |     3.49 |     21.37 |      7.71 |                          |
| flat_cap5_ds1         |  30.72 |    -2.21 | 13.92 |     794 |        63 |    10.99 |     3.49 |     21.37 |      7.71 |                          |
| eqrisk0.5_capinf_ds0  |  65.22 |    -5.33 | 12.25 |     857 |         0 |     8.19 |     3.16 |     41.46 |     16.8  |                          |
| eqrisk0.5_capinf_ds1  |  65.32 |    -5.58 | 11.71 |     839 |        18 |     9.36 |     2.96 |     41.93 |     16.49 |                          |
| flat_cap3_ds0         |  23.1  |    -2.07 | 11.18 |     646 |       211 |     7.51 |     3.34 |     15.53 |      6.56 |                          |
| flat_cap3_ds1         |  23.1  |    -2.07 | 11.18 |     646 |       211 |     7.51 |     3.34 |     15.53 |      6.56 |                          |
| eqrisk0.5_cap5_ds0    |  57.3  |    -5.21 | 11    |     794 |        63 |     7.69 |     3.04 |     35.78 |     15.86 |                          |
| eqrisk0.5_cap5_ds1    |  57.4  |    -5.46 | 10.51 |     776 |        81 |     8.5  |     2.85 |     36.24 |     15.54 |                          |
| eqrisk0.5_cap3_ds1    |  44.12 |    -4.99 |  8.83 |     636 |       221 |     5.51 |     2.98 |     25.43 |     14.9  |                          |
| eqrisk0.5_cap3_ds0    |  42.83 |    -5.06 |  8.47 |     646 |       211 |     5.01 |     2.8  |     25.31 |     13.99 |                          |
| eqrisk0.25_capinf_ds0 |  35.53 |    -4.21 |  8.43 |     857 |         0 |     5.32 |     2.91 |     22.41 |     10.72 |                          |
| eqrisk0.25_capinf_ds1 |  34.92 |    -4.21 |  8.29 |     854 |         3 |     5.19 |     2.91 |     21.86 |     10.72 |                          |
| eqrisk0.25_cap5_ds0   |  30.78 |    -3.8  |  8.1  |     794 |        63 |     5.01 |     2.76 |     19.06 |      9.85 |                          |
| eqrisk0.25_cap5_ds1   |  30.19 |    -3.8  |  7.94 |     791 |        66 |     4.87 |     2.76 |     18.52 |      9.85 |                          |
| eqrisk0.25_cap3_ds0   |  25.99 |    -3.88 |  6.71 |     646 |       211 |     4    |     2.95 |     15.5  |      9.09 |                          |
| eqrisk0.25_cap3_ds1   |  25.43 |    -3.88 |  6.56 |     643 |       214 |     3.86 |     2.95 |     14.98 |      9.09 |                          |

*Rules marked YES beat the baseline MAR in both halves — only those are adoption candidates. Equity marked at trade events (approx DD). Not financial advice.*
