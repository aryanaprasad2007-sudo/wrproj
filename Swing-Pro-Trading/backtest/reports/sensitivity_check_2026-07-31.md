# Parameter sensitivity check — 2026-07-31

Local robustness check around the 2026-07-30 train/holdout sweep winner (`tf=3 adx_min=15 rsi_long=50 stop=1.5xATR rr=2.0`), which sat at the edge of the tested grid on `adx_min`, `rsi_long_level` and `rr_ratio` — a known overfitting red flag. Each parameter below is varied locally while the other four are held at the winner's values, on the FULL 30-year dataset (no train/holdout split — this checks robustness, not selection).

**Read the VERDICT line.** Smooth/plateau means the winner sits on a broad region of edge — nudging the parameter barely moves performance, so it wasn't a lucky spike. Cliff means performance drops sharply right next to the winning value, which means the original grid search likely got lucky landing exactly there.

## adx_min

|   adx_min |   n |   win% |    pf |   expR |    t | breadth   |
|----------:|----:|-------:|------:|-------:|-----:|:----------|
|        10 | 541 |   50.5 | 2.968 | 0.6753 | 8.27 | 22/22     |
|        12 | 538 |   50.6 | 2.954 | 0.6755 | 8.24 | 22/22     |
|        15 | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|        18 | 489 |   51.7 | 3.112 | 0.6825 | 8.29 | 22/22     |
|        20 | 477 |   50.7 | 2.931 | 0.6447 | 7.37 | 22/22     |
|        25 | 380 |   50.5 | 3.427 | 0.7192 | 6.73 | 22/22     |

**VERDICT: smooth/plateau**  
below neighbor (adx_min=12): t 8.31->8.24 (+1%); above neighbor (adx_min=18): t 8.31->8.29 (+0%)

## rsi_long_level

|   rsi_long_level |   n |   win% |    pf |   expR |    t | breadth   |
|-----------------:|----:|-------:|------:|-------:|-----:|:----------|
|               45 | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|               48 | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|               50 | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|               52 | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|               55 | 524 |   51   | 3.072 | 0.6945 | 8.06 | 22/22     |

**VERDICT: smooth/plateau**  
below neighbor (rsi_long_level=48): t 8.31->8.31 (+0%); above neighbor (rsi_long_level=52): t 8.31->8.31 (+0%)

**Caveat:** n and every stat are bit-for-bit identical across 45–52, only moving at 55. That's not really five independent samples of a plateau — it means the long-RSI threshold almost never sits between 45 and 52 at the moment other filters (trend/MACD/ADX/market) already gate a signal, so this parameter is largely non-binding in that band on this basket/timeframe. The "plateau" verdict still holds (no cliff either way), but it's a plateau because the parameter isn't doing much work here, not because it was independently stress-tested at five points.

## atr_stop_mult

|   atr_stop_mult |   n |   win% |    pf |   expR |    t | breadth   |
|----------------:|----:|-------:|------:|-------:|-----:|:----------|
|            1    | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|            1.25 | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|            1.5  | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|            1.75 | 523 |   51.1 | 3.082 | 0.6903 | 8.31 | 22/22     |
|            2    | 523 |   51.1 | 3.082 | 0.6903 | 8.31 | 22/22     |

**VERDICT: smooth/plateau**  
below neighbor (atr_stop_mult=1.25): t 8.31->8.31 (+0%); above neighbor (atr_stop_mult=1.75): t 8.31->8.31 (+0%)

**Caveat:** virtually identical across the entire 1.0–2.0 range. Reading `swing_pro.py`: the actual stop is `max(structural_swing_stop, atr_stop_mult * atr * 0.5)` — `atr_stop_mult` only acts as a floor under the structural swing-high/low stop, and on 3-session bars the structural stop is almost always the larger of the two, so the floor essentially never binds. This parameter is close to inert in the current config, which is why it can't cliff — there isn't enough leverage on outcomes to produce one. Not evidence of robustness so much as evidence the parameter isn't load-bearing; if `use_struct_stop` is ever turned off, this would need re-checking since `atr_stop_mult` would then set the stop directly.

## rr_ratio

|   rr_ratio |   n |   win% |    pf |   expR |    t | breadth   |
|-----------:|----:|-------:|------:|-------:|-----:|:----------|
|       1.5  | 585 |   51.5 | 2.618 | 0.5194 | 8.22 | 22/22     |
|       1.75 | 555 |   50.8 | 2.817 | 0.5954 | 8.41 | 22/22     |
|       2    | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|       2.25 | 495 |   51.5 | 3.305 | 0.7447 | 8.43 | 22/22     |
|       2.5  | 482 |   50.4 | 3.489 | 0.8032 | 7.83 | 22/22     |
|       3    | 457 |   49.7 | 3.718 | 0.8663 | 7.87 | 22/22     |

**VERDICT: smooth/plateau**  
below neighbor (rr_ratio=1.75): t 8.31->8.41 (-1%); above neighbor (rr_ratio=2.25): t 8.31->8.43 (-1%)

## tf

|   tf |   n |   win% |    pf |   expR |    t | breadth   |
|-----:|----:|-------:|------:|-------:|-----:|:----------|
|    2 | 753 |   45.7 | 2.332 | 0.4674 | 7.04 | 22/22     |
|    3 | 523 |   51.1 | 3.082 | 0.6904 | 8.31 | 22/22     |
|    4 | 407 |   52.1 | 3.506 | 0.7077 | 7.83 | 22/22     |
|    5 | 340 |   55.6 | 3.84  | 0.7685 | 7.85 | 22/22     |

**VERDICT: smooth/plateau**  
below neighbor (tf=2): t 8.31->7.04 (+15%); above neighbor (tf=4): t 8.31->7.83 (+6%)

## Summary

| parameter | verdict | note |
|---|---|---|
| adx_min | smooth/plateau | genuinely tested — t-stat moves gradually 8.27→8.31→...→6.73 as adx_min rises, no cliff at 15 |
| rsi_long_level | smooth/plateau | mostly non-binding 45–52 (identical stats), only rsi_long=55 differs — plateau reflects filter not mattering here, not five independent tests |
| atr_stop_mult | smooth/plateau | non-binding across 1.0–2.0 — structural swing stop dominates the ATR floor on 3-session bars, so this parameter has little leverage on outcomes |
| rr_ratio | smooth/plateau | genuinely tested — expR/PF/t all move smoothly and monotonically-ish with rr, no cliff at 2.0 |
| tf | smooth/plateau | genuinely tested — t-stat degrades gradually moving away from tf=3 in either direction (7.04–8.43 range), no sharp drop |

**Overall: no cliffs found.** The two parameters that sat at the edge of the original grid with the most overfitting risk — `adx_min` and `rr_ratio` — are the ones most clearly, independently confirmed smooth: their t-stats change gradually across the local grid with no discontinuity at the winning value. `rsi_long_level` (also at a grid edge originally, though 50 wasn't literally the boundary tested) turns out to be largely non-binding in this band, so its plateau is real but less informative than it looks. `atr_stop_mult` is inert due to the structural-stop floor. Combined with the independent full-grid resweep (`sweep-expansion-overnight`), this is a second, different line of evidence pointing away from "the winner was a lucky spike in a jagged landscape."
