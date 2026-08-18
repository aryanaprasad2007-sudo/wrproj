# Execution batch (B: limit entries, C: time-stops) — 2026-07-02

857 v2.2 trades, 10 symbols, 2y. THE FINAL tests against this dataset — the H1/H2 split is retired after this report.

## Results (per-trade PnL re-priced; sizing-neutral, per ~10k notional)

| variant   |   n |   net |   pf |   H1_net |   H1_pf |   H2_net |   H2_pf | beats_base_both   |
|:----------|----:|------:|-----:|---------:|--------:|---------:|--------:|:------------------|
| base      | 857 |   687 | 1.53 |      509 |    1.73 |      177 |    1.29 |                   |
| limK1     | 832 |   686 | 1.55 |      502 |    1.76 |      184 |    1.32 |                   |
| limK3     | 841 |   669 | 1.53 |      488 |    1.72 |      181 |    1.31 |                   |
| ts85_0.0  | 857 |   686 | 1.55 |      518 |    1.77 |      168 |    1.29 |                   |
| ts85_0.5  | 857 |   620 | 1.5  |      468 |    1.71 |      152 |    1.26 |                   |
| ts170_0.5 | 857 |   694 | 1.54 |      504 |    1.72 |      190 |    1.32 |                   |

## MAE/MFE portrait (all trades)

- Winners: median MAE -0.34R, median bars to resolve 82
- Losers:  median MFE 0.47R (how close they got to winning), median bars 22
- Time-stop rules derived from H1 winners' median duration (85 bars).

*Only YES rows are adoption candidates. After this: evidence comes from the forward test and the maturing options dataset, not from re-mining these two years. Not financial advice.*
