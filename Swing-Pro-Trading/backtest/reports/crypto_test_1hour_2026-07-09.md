# Crypto generalization test (1Hour) — 2026-07-09

Pre-registered OOS test of the UNCHANGED engine (config_v22, use_htf_trend=False, long-only, pure stop + 3R) on 1Hour crypto bars, 2021-01-01→now, realistic **0.15%/side** taker fee.

## Verdict: DOES NOT GENERALIZE (as-is)

Basket PF **H1 0.63 / H2 0.72** (full 0.67, **1854 trades** — large sample). Bar = PF>1.15 both halves → **FAIL**. Both-halves-positive: 1/7.

| symbol | bars | trades | PF H1 | PF H2 | PF full | net (2k) |
|---|---|---|---|---|---|---|
| BTC/USD | 48364 | 278 | 0.87 | 0.78 | 0.83 | $-166 |
| ETH/USD | 48362 | 278 | 1.29 | 1.02 | 1.15 | $177 |
| LTC/USD | 48360 | 266 | 0.51 | 0.63 | 0.56 | $-541 |
| DOGE/USD | 48354 | 247 | 0.12 | 0.06 | 0.12 | $-1,973 |
| LINK/USD | 48352 | 278 | 0.90 | 0.57 | 0.73 | $-399 |
| BCH/USD | 48241 | 245 | 1.09 | 0.53 | 0.80 | $-242 |
| UNI/USD | 48294 | 262 | 0.82 | 0.98 | 0.90 | $-156 |

Costs are decisive at this trade count: 0.15%/side = 0.30% round-trip. Crypto is one correlated beta (all names track BTC). Not financial advice.
