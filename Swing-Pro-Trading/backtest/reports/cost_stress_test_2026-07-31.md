# Cost stress test — 2026-07-31

Winner from `backtest/reports/holdout_sweep_2026-07-30.md`: `tf=3 adx_min=15 rsi_long=50 stop=1.5xATR rr=2.0`, engine `swing_pro.config_v22(trade_dir="long", use_htf_trend=False, ...)`. 22-symbol basket (`run_daily_30y.SYMBOLS`), full 1995-2026 daily history grouped to 3-session bars.

The 2026-07-30 backtest used `swing_pro.Config`'s baked-in defaults (commission_pct=0.01, slippage_ticks=1) — an idealized cost assumption. Real fills on a small Robinhood account (fractional shares, market orders, regular hours only, wide bid/ask on thin names) will be worse. This reruns the identical config at increasing commission/slippage overrides to find where the edge actually breaks.

| Level | commission_pct | slippage_ticks | n | PF | win% | expR | t-stat | net$ |
|---|---|---|---|---|---|---|---|---|
| 0 | 0.01 | 1 | 523 | 3.082 | 51.1 | 0.6904 | 8.31 | 666,865 |
| 1 | 0.02 | 2 | 523 | 2.984 | 50.7 | 0.6783 | 8.17 | 647,339 |
| 2 | 0.05 | 3 | 523 | 2.879 | 50.7 | 0.663 | 7.99 | 625,791 |
| 3 | 0.1 | 5 | 523 | 2.698 | 50.1 | 0.634 | 7.63 | 586,427 |
| 4 | 0.2 | 8 | 523 | 2.451 | 50.1 | 0.5864 | 7.02 | 529,141 |

**Breakeven (PF crosses 1.0):** ~7.88x the Level-4 cost pair -> commission_pct~1.58, slippage_ticks~63.0 (~158x baseline commission, ~63x baseline slippage)

Level 0 reproduces the 2026-07-30 backtest's cost assumption exactly (the reported PF here should match that report's full-history PF for this config). Level 4 is deliberately extreme and not a realistic execution estimate — it exists only to bound the search for the breaking point.

## Extended search — PF never dropped below 1.0 through Level 4

The five required levels above (up to 20x baseline commission, 8x baseline slippage) all still cleared PF 1.0, so the search was extended by scaling the Level-4 commission/slippage pair (0.20%, 8 ticks) up by a multiplier `m`, to actually locate where the edge dies.

| m (x Level 4) | commission_pct | slippage_ticks | n | PF | win% | expR | t-stat | net$ |
|---|---|---|---|---|---|---|---|---|
| 1.00 | 0.200 | 8.0 | 523 | 2.451 | 50.1 | 0.5864 | 7.02 | 529,141 |
| 2.00 | 0.400 | 16.0 | 523 | 2.008 | 48.9 | 0.4704 | 5.46 | 409,630 |
| 4.00 | 0.800 | 32.0 | 523 | 1.487 | 46.5 | 0.2378 | 2.43 | 235,555 |
| 6.00 | 1.200 | 48.0 | 523 | 1.191 | 44.4 | 0.0044 | 0.04 | 104,390 |
| 7.00 | 1.400 | 56.0 | 523 | 1.082 | 43.6 | -0.1126 | -0.89 | 46,987 |
| 7.50 | 1.500 | 60.0 | 523 | 1.033 | 42.6 | -0.1713 | -1.3 | 19,686 |
| 7.75 | 1.550 | 62.0 | 523 | 1.011 | 42.4 | -0.2006 | -1.49 | 6,338 |
| 7.88 | 1.575 | 63.0 | 523 | 1.0 | 42.4 | -0.2153 | -1.59 | -264 |
| 7.94 | 1.588 | 63.5 | 523 | 0.994 | 42.3 | -0.2226 | -1.63 | -3,548 |
| 8.00 | 1.600 | 64.0 | 523 | 0.989 | 42.3 | -0.23 | -1.68 | -6,821 |

**Actual breakeven:** ~7.88x the Level-4 cost pair -> commission_pct~1.58, slippage_ticks~63.0 (~158x baseline commission, ~63x baseline slippage)

**Note:** the t-stat (edge distinguishable from zero, |t|>2) drops below significance between m=4.00 (t=2.43) and m=6.00 (t=0.04) — well *before* PF nominally crosses 1.0 at m~7.88. Past that point the edge is not reliably distinguishable from noise even though PF still reads >1.
