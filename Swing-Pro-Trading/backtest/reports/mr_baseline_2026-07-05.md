# MR-1 baseline — pre-registered one-shot — 2026-07-05

Spec + bars frozen in `run_mr_baseline.py` before the run. Long-only daily mean reversion: close>200d SMA, RSI(3)<15, next-open entry, exit first close>10d SMA, 10-session time stop, 3×ATR disaster stop, flat 10%/max 10 concurrent.

## VERDICT: MARGINAL — decision tree says: run the ONE pre-declared 8-cell grid (derive 1995-2015, confirm once on 2015-2026)

| bar | result |
|---|---|
| B1 PF>1.15 all decades | PASS |
| B2 n>=500 | PASS |
| B3 >=17/22 profitable (got 18/22) | PASS |
| B4 corr<0.30 (got +0.462) | FAIL |
| B5 combo MAR beats both (combo 0.3 vs MR 0.27 / SP-D 0.18) | PASS |

## By era

| era          |    n |    net |   exp% |   expR |   win% |   avg_hold |   pf |
|:-------------|-----:|-------:|-------:|-------:|-------:|-----------:|-----:|
| FULL 30y     | 2809 | 249870 |  0.482 |  0.06  |   66   |        5.5 | 1.25 |
| D1 1995-2005 |  821 |  90860 |  0.846 |  0.084 |   68.5 |        5.4 | 1.36 |
| D2 2005-2015 |  940 |  60776 |  0.321 |  0.055 |   66.3 |        5.5 | 1.22 |
| D3 2015-2026 | 1048 |  98233 |  0.341 |  0.046 |   63.7 |        5.5 | 1.21 |

Exit reasons: {'mean_touch': 2128, 'disaster_stop': 407, 'time_stop': 274} · max concurrent positions: 10

## Curves

| curve                  |   cagr% |   max_dd% |   mar |
|:-----------------------|--------:|----------:|------:|
| MR-1 portfolio         |    4.04 |    -14.96 |  0.27 |
| SWING_PRO-D aggregate  |    0.63 |     -3.4  |  0.18 |
| 50/50 daily-rebalanced |    2.38 |     -7.84 |  0.3  |

Daily-P&L correlation MR-1 vs SWING_PRO-D: **+0.462**

## Per symbol

| symbol   |   n |    net |   exp% |   expR |   win% |   avg_hold |   pf |
|:---------|----:|-------:|-------:|-------:|-------:|-----------:|-----:|
| AAPL     | 154 | -15094 | -0.681 | -0.037 |   54.5 |        5.6 | 0.82 |
| AMD      | 104 |  17484 |  1.003 |  0.05  |   66.3 |        5.6 | 1.24 |
| BA       | 140 |   6647 |  0.433 |  0.068 |   65.7 |        5.1 | 1.12 |
| CAT      | 132 |  28472 |  0.987 |  0.111 |   69.7 |        5.4 | 1.71 |
| COST     | 145 |  24260 |  1.06  |  0.133 |   73.8 |        5   | 1.64 |
| CVX      | 113 |  -1032 |  0.063 |  0.006 |   60.2 |        6   | 0.97 |
| DE       | 145 |  31019 |  0.899 |  0.122 |   71   |        5.5 | 1.85 |
| DIS      | 105 |   -318 |  0.084 |  0.029 |   63.8 |        5.9 | 0.99 |
| GE       | 127 |  23983 |  1.063 |  0.128 |   72.4 |        5.6 | 1.74 |
| GS       | 108 |   7375 |  0.399 |  0.031 |   66.7 |        5.3 | 1.16 |
| HD       | 155 |  23808 |  0.901 |  0.106 |   66.5 |        5   | 1.6  |
| IBM      | 135 |  17705 |  0.674 |  0.074 |   68.1 |        5.9 | 1.51 |
| INTC     | 113 |  15847 |  0.749 |  0.069 |   63.7 |        5.7 | 1.38 |
| JPM      | 128 |  18813 |  0.748 |  0.1   |   65.6 |        5.7 | 1.53 |
| KO       | 132 |   4811 |  0.055 |  0.012 |   62.9 |        5.5 | 1.15 |
| MSFT     | 127 |  14112 |  0.512 |  0.088 |   67.7 |        5.5 | 1.41 |
| NKE      | 122 |  16281 |  0.694 |  0.101 |   68   |        5   | 1.39 |
| NVDA     | 118 | -60015 | -2.571 | -0.259 |   44.9 |        6   | 0.54 |
| ORCL     | 122 |  28371 |  1.353 |  0.112 |   68   |        5.8 | 1.75 |
| UNH      | 145 |  27792 |  0.961 |  0.136 |   73.8 |        5.2 | 1.69 |
| WMT      | 123 |   7074 |  0.444 |  0.032 |   67.5 |        5.9 | 1.23 |
| XOM      | 116 |  12474 |  0.526 |  0.052 |   67.2 |        5.5 | 1.45 |

*Same caveats as the 30y flagship test: survivors-only universe, split-adjusted yfinance bars, stops assume fill at the stop price (gaps can slip). Not financial advice.*

## Addendum — same-day correlation decomposition (diagnostic, no parameter selection)

The B4 failure needed a diagnosis before acting on the decision tree: is +0.462
shared market beta (both systems are long-only in the same 22 names) or signal
overlap (the two systems taking the same trades)?

| measure | value |
|---|---|
| raw corr(MR-1, SP-D) | +0.462 |
| corr(MR-1, SPY) | +0.450 |
| corr(SP-D, SPY) | +0.594 |
| **partial corr(MR-1, SP-D \| SPY)** | **+0.271** |
| MR-1 active days | 71.3% |
| SP-D active days | 95.3% |

Reading: the raw correlation is dominated by shared long-only beta; the
signal-level overlap after removing the market is +0.271 — under the 0.30 bar.
B4 as registered still FAILED (the bar was written beta-blind); recorded
honestly rather than rewritten. NOTE on the header verdict: the "MARGINAL →
grid" branch was pre-defined on PF (1.00–1.15 or 2/3 decades); PF passed all
three decades, so the grid is NOT triggered — the runner's else-branch
over-reached.

**FINAL DISPOSITION (Ari, 2026-07-05): ADOPTED WITH FOOTNOTE** — B4 scored
failed-as-registered / passed beta-adjusted (+0.271); future diversification
bars are to be written as partial correlation controlling for market. Next
step executed: shadow forward audition (`mr_forward.py`, SwingPro_MR_Shadow).

Character notes (no action taken): NVDA is the catastrophic outlier (−$60k,
PF 0.54) and AAPL mildly negative — MR dies precisely on the strongest
momentum names, which is the anti-correlation thesis showing up at symbol
level. No post-hoc symbol dropping (that would be mining). Disaster stop fired
on 14.5% of trades — more "trade management" than "disaster"; the concurrency
cap binds (hit 10).
