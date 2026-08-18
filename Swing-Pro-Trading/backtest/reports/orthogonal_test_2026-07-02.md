# Free orthogonal-data test — 2026-07-02

504 v2-long trades tagged with prior-day DIX / GEX / FINRA short-ratio features. Same single-shot H1→H2 protocol as the regime autopsy.

**Gate derived on H1: `dix_high == False`** (spread -0.248R)

## Verdict

| set                  |   n |   net_usd |   exp_R |   win_% |   pf |
|:---------------------|----:|----------:|--------:|--------:|-----:|
| H1 all (derivation)  | 281 |      -251 |  -0.068 |    45.9 | 0.98 |
| H1 gated             | 124 |      1752 |   0.071 |    53.2 | 1.32 |
| H2 all (validation)  | 223 |      1957 |  -0.009 |    49.3 | 1.26 |
| H2 GATED  <- verdict | 135 |      1049 |   0.044 |    51.9 | 1.24 |
| H2 blocked           |  88 |       908 |  -0.09  |    45.5 | 1.28 |

## H1 buckets (derivation)

| feature   | state   |   n |   net_usd |   exp_R |   win_% |   pf |
|:----------|:--------|----:|----------:|--------:|--------:|-----:|
| dix_high  | True    | 157 |     -2003 |  -0.177 |    40.1 | 0.76 |
| dix_high  | False   | 124 |      1752 |   0.071 |    53.2 | 1.32 |
| gex_low   | True    |  72 |       800 |  -0.049 |    47.2 | 1.24 |
| gex_low   | False   | 209 |     -1050 |  -0.074 |    45.5 | 0.9  |
| gex_neg   | False   | 281 |      -251 |  -0.068 |    45.9 | 0.98 |
| srat_high | True    | 178 |      -806 |  -0.094 |    44.9 | 0.91 |
| srat_high | False   | 103 |       556 |  -0.021 |    47.6 | 1.11 |

## H2 buckets (reference, post-hoc)

| feature   | state   |   n |   net_usd |   exp_R |   win_% |     pf |
|:----------|:--------|----:|----------:|--------:|--------:|-------:|
| dix_high  | True    |  88 |       908 |  -0.09  |    45.5 |   1.28 |
| dix_high  | False   | 135 |      1049 |   0.044 |    51.9 |   1.24 |
| gex_low   | True    |  65 |       465 |  -0.015 |    47.7 |   1.2  |
| gex_low   | False   | 158 |      1492 |  -0.006 |    50   |   1.28 |
| gex_neg   | True    |   1 |        66 |   0.486 |   100   | inf    |
| gex_neg   | False   | 222 |      1890 |  -0.011 |    49.1 |   1.25 |
| srat_high | True    | 137 |      1350 |  -0.012 |    50.4 |   1.3  |
| srat_high | False   |  86 |       607 |  -0.005 |    47.7 |   1.2  |

*Data: SqueezeMetrics DIX/GEX (free), FINRA daily short volume (free). If this fails too, daily-granularity orthogonal data is insufficient and the next test needs intraday flow. Not financial advice.*
