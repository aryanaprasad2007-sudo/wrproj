# SWING_PRO-D — daily-bar validation on a decade — 2026-07-03

v2.2 exits, long-only, local daily EMA50 regime, same 7 gates. FRESH data (2016-2026 daily — never mined by any prior test). Pre-registered bar: PF > 1.15 in both halves (split 2021-07-01).

**VALIDATED: YES**

## Aggregate

| set          |   n |   net |   expR |   win% |   pf |
|:-------------|----:|------:|-------:|-------:|-----:|
| FULL decade  | 197 | 75189 |  0.463 |   44.2 | 2.24 |
| H1 2016-2021 |  95 | 49489 |  0.632 |   45.3 | 2.88 |
| H2 2021-2026 | 102 | 25701 |  0.305 |   43.1 | 1.74 |

## Per symbol (note IPO-truncated histories)

| symbol   |   bars | since      |   trades |   net |   win% |    pf |   maxDD% |
|:---------|-------:|:-----------|---------:|------:|-------:|------:|---------:|
| JPM      |   2511 | 2016-07-07 |       16 |  6341 |   43.8 |  2.7  |    -3.51 |
| GS       |   2511 | 2016-07-07 |       16 |  7662 |   43.8 |  2.81 |    -3.73 |
| XOM      |   2511 | 2016-07-07 |       13 |  2943 |   46.2 |  1.6  |    -3.52 |
| CVX      |   2511 | 2016-07-07 |       13 |  3347 |   23.1 |  1.67 |    -3.13 |
| CAT      |   2511 | 2016-07-07 |       13 | 23242 |   69.2 | 10.68 |    -3.24 |
| DE       |   2511 | 2016-07-07 |       13 | 13755 |   38.5 |  3.29 |    -5.75 |
| BA       |   2511 | 2016-07-07 |       15 | -4042 |   20   |  0.6  |   -10.43 |
| WMT      |   2511 | 2016-07-07 |       18 |  3801 |   61.1 |  2.86 |    -2.71 |
| COST     |   2511 | 2016-07-07 |       20 |  8472 |   50   |  2.69 |    -3.56 |
| HD       |   2511 | 2016-07-07 |       19 |  3005 |   52.6 |  1.69 |    -2.62 |
| UNH      |   2511 | 2016-07-07 |       18 |  4190 |   38.9 |  1.64 |    -4.35 |
| DIS      |   2511 | 2016-07-07 |       10 | -2140 |   20   |  0.46 |    -4.42 |
| KO       |   2511 | 2016-07-07 |       13 |  4612 |   53.8 |  2.79 |    -2.07 |

*Positions can gap overnight on daily bars — stops fill at the stop price in this model but can slip through gaps in reality; treat PF as slightly optimistic. Not financial advice.*
