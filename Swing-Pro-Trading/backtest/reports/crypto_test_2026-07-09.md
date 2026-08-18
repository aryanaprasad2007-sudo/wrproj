# Crypto generalization test — 2026-07-09

**Pre-registered** out-of-sample test of the UNCHANGED live stock engine (SWING_PRO-D: config_v22, use_htf_trend=False, long-only, pure stop + 3R) on 24/7 daily crypto bars. No parameters tuned.

## Verdict: DOES NOT GENERALIZE (as-is)

Basket PF **H1 0.55 / H2 1.30** (full 0.87, 96 trades). Pre-registered bar = PF > 1.15 in BOTH halves → **FAIL**. Symbols positive in both halves: 1/8.

| symbol | trades | PF H1 | PF H2 | PF full | net (2k book) |
|---|---|---|---|---|---|
| BTC/USD | 18 | 0.74 | 2.57 | 1.61 | $149 |
| ETH/USD | 14 | 0.35 | 3.74 | 1.72 | $196 |
| SOL/USD | 11 | 2.20 | 0.00 | 1.25 | $92 |
| LTC/USD | 9 | 0.05 | 0.00 | 0.03 | $-266 |
| DOGE/USD | 12 | 0.24 | 0.69 | 0.41 | $-322 |
| LINK/USD | 13 | 0.00 | 1.83 | 0.83 | $-66 |
| BCH/USD | 9 | 1.11 | 2.17 | 1.58 | $134 |
| UNI/USD | 10 | 0.00 | 0.75 | 0.29 | $-259 |

**What this means for STOCKS:** the engine does not carry an edge to crypto as-is. Either the edge is equity-specific, or crypto needs its own (separately validated) parameters — it does NOT retroactively weaken the stock result, but it is weak generalization evidence.

Caveats: crypto is one correlated beta (all names track BTC), so the basket is less independent than it looks; 2021-present is a single boom→bust→recovery macro cycle; fractional sizing (PF is size-invariant). Not financial advice.
