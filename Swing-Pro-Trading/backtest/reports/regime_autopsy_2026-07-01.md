# Regime autopsy — 2026-07-01

v2-long, 2y Alpaca 5m, 504 regime-tagged trades. All features prior-day-observable (shifted 1 day; no lookahead).

**Protocol:** gate derived on H1 (< 2025-07-02) only, applied once to H2. No iteration.

**H1-derived gate: trade only when `sym_above_50d == True`** (H1 expectancy spread +0.127R)

## Verdict table

| set                      |   n |   net_usd |   exp_R |   win_% |   pf |
|:-------------------------|----:|----------:|--------:|--------:|-----:|
| H1 all (derivation set)  | 281 |      -251 |  -0.068 |    45.9 | 0.98 |
| H1 gated                 | 208 |       -27 |  -0.035 |    47.6 | 1    |
| H2 all (validation set)  | 223 |      1957 |  -0.009 |    49.3 | 1.26 |
| H2 GATED  <- the verdict | 191 |       704 |  -0.039 |    48.2 | 1.11 |
| H2 blocked by gate       |  32 |      1253 |   0.171 |    56.2 | 2.25 |

## H1 buckets (derivation set)

| feature           | state   |   n |   net_usd |   exp_R |   win_% |   pf |
|:------------------|:--------|----:|----------:|--------:|--------:|-----:|
| spy_above_50d     | True    | 214 |       151 |  -0.05  |    46.3 | 1.01 |
| spy_above_50d     | False   |  67 |      -402 |  -0.124 |    44.8 | 0.88 |
| spy_50d_rising    | True    | 182 |       200 |  -0.045 |    46.2 | 1.02 |
| spy_50d_rising    | False   |  99 |      -451 |  -0.108 |    45.5 | 0.91 |
| spy_near_20d_high | True    | 258 |     -1211 |  -0.093 |    43.8 | 0.91 |
| spy_near_20d_high | False   |  23 |       960 |   0.221 |    69.6 | 3.93 |
| spy_5d_ret_pos    | True    | 218 |       -30 |  -0.088 |    45   | 1    |
| spy_5d_ret_pos    | False   |  63 |      -221 |   0.004 |    49.2 | 0.94 |
| vol_calm          | True    | 123 |        54 |  -0.031 |    46.3 | 1.01 |
| vol_calm          | False   | 158 |      -305 |  -0.097 |    45.6 | 0.96 |
| sym_above_50d     | True    | 208 |       -27 |  -0.035 |    47.6 | 1    |
| sym_above_50d     | False   |  73 |      -223 |  -0.162 |    41.1 | 0.93 |

## H2 buckets (shown AFTER the gate was fixed — reference only)

| feature           | state   |   n |   net_usd |   exp_R |   win_% |   pf |
|:------------------|:--------|----:|----------:|--------:|--------:|-----:|
| spy_above_50d     | True    | 214 |      1545 |  -0.012 |    49.1 | 1.21 |
| spy_above_50d     | False   |   9 |       412 |   0.075 |    55.6 | 2.82 |
| spy_50d_rising    | True    | 206 |       597 |  -0.053 |    47.6 | 1.08 |
| spy_50d_rising    | False   |  17 |      1360 |   0.52  |    70.6 | 3.73 |
| spy_near_20d_high | True    | 220 |      2002 |  -0.002 |    49.5 | 1.27 |
| spy_near_20d_high | False   |   3 |       -45 |  -0.542 |    33.3 | 0.59 |
| spy_5d_ret_pos    | True    | 187 |      1745 |  -0.02  |    48.7 | 1.27 |
| spy_5d_ret_pos    | False   |  36 |       212 |   0.047 |    52.8 | 1.2  |
| vol_calm          | True    | 144 |       427 |  -0.041 |    47.9 | 1.09 |
| vol_calm          | False   |  79 |      1530 |   0.049 |    51.9 | 1.59 |
| sym_above_50d     | True    | 191 |       704 |  -0.039 |    48.2 | 1.11 |
| sym_above_50d     | False   |  32 |      1253 |   0.171 |    56.2 | 2.25 |

*If 'H2 GATED' does not clearly beat 'H2 all', regime conditioning on these features is dead too, and the honest conclusion stands: the edge must come from orthogonal data, not OHLCV geometry. Not financial advice.*
