# Whipsaw-fix test â€” 2026-07-02

Failure mode targeted: late extension-chasing entries + stop-out churn during counter-trend rips (META 5m screenshot, 2026-07-02).

Bar for adoption: improves the full-2y result AND both halves AND keeps a sane trade count â€” separately per side.

| side   | variant     |   n |    net |   expR |   win% |   pf |   H1_net |   H1_pf |   H2_net |   H2_pf | both_halves_up   |
|:-------|:------------|----:|-------:|-------:|-------:|-----:|---------:|--------:|---------:|--------:|:-----------------|
| long   | base_v2     | 504 |   1706 | -0.042 |   47.4 | 1.08 |     -251 |    0.98 |     1957 |    1.26 |                  |
| long   | M1_ext1.0   | 306 |  -1827 | -0.121 |   44.4 | 0.84 |    -1801 |    0.76 |      -26 |    0.99 |                  |
| long   | M1_ext2.0   | 463 |    -30 | -0.071 |   44.9 | 1    |     -335 |    0.97 |      305 |    1.05 |                  |
| long   | M2_pullback | 184 |   -593 | -0.094 |   45.7 | 0.93 |     -730 |    0.85 |      138 |    1.05 |                  |
| long   | M3_cool10   | 494 |   1698 | -0.049 |   47.4 | 1.08 |     -240 |    0.98 |     1938 |    1.26 |                  |
| long   | M1+M3       | 304 |  -1963 | -0.136 |   44.4 | 0.82 |    -1866 |    0.75 |      -97 |    0.97 |                  |
| short  | base_v2     | 443 | -10850 | -0.084 |   41.8 | 0.65 |    -6263 |    0.67 |    -4586 |    0.64 |                  |
| short  | M1_ext1.0   | 255 |  -6395 | -0.101 |   45.9 | 0.58 |    -4273 |    0.54 |    -2122 |    0.64 | YES              |
| short  | M1_ext2.0   | 408 |  -6295 | -0.062 |   42.9 | 0.75 |    -2244 |    0.84 |    -4051 |    0.63 | YES              |
| short  | M2_pullback | 161 |  -4875 | -0.081 |   46   | 0.55 |    -3073 |    0.56 |    -1802 |    0.54 | YES              |
| short  | M3_cool10   | 435 | -10352 | -0.082 |   41.8 | 0.66 |    -6593 |    0.64 |    -3759 |    0.68 |                  |
| short  | M1+M3       | 254 |  -6264 | -0.097 |   46.1 | 0.59 |    -4273 |    0.54 |    -1991 |    0.66 | YES              |

*Variants marked YES beat base in both halves (net). Not financial advice.*
