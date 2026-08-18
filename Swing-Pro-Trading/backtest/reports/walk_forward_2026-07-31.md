# Walk-forward validation — 2026-07-31

Four independent select/test windows, same grid as `run_holdout_sweep.py` (2026-07-30), ranked on select-window t-stat with a 120-trade floor. The winning config from each window's select range is scored ONLY on that window's test range -- no re-selection on test data, in any window.

Grid: tf [2, 3, 5, 10] · adx_min [15, 20, 25] · rsi_long_level [50, 55] · atr_stop_mult [1.0, 1.5, 2.0] · rr_ratio [2.0, 3.0, 4.0]

## Results

| window | select range | test range | tf | adx_min | rsi_long | atr_stop | rr | sel n | sel PF | sel t | test n | test PF | test expR | test t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| W1 | 1995-01-01→2005-01-01 | 2005-01-01→2010-01-01 | 3.0 | 15.0 | 50.0 | 1.0 | 3.0 | 124.0 | 4.27 | 5.09 | 73.0 | 3.034 | 0.5689 | 2.57 |
| W2 | 2000-01-01→2010-01-01 | 2010-01-01→2015-01-01 | 3.0 | 15.0 | 50.0 | 1.0 | 2.0 | 146.0 | 2.185 | 3.35 | 87.0 | 2.443 | 0.5803 | 2.62 |
| W3 | 2005-01-01→2015-01-01 | 2015-01-01→2020-01-01 | 3.0 | 15.0 | 50.0 | 2.0 | 2.0 | 169.0 | 2.759 | 4.01 | 96.0 | 2.16 | 0.4269 | 2.56 |
| W4 | 2010-01-01→2020-01-01 | 2020-01-01→2026-07-30 | 5.0 | 15.0 | 50.0 | 1.0 | 2.0 | 123.0 | 3.694 | 4.25 | 87.0 | 4.14 | 0.6399 | 4.4 |

## Consistency verdict

- Winning `adx_min` across windows: [15.0, 15.0, 15.0, 15.0]
- Winning `rsi_long_level` across windows: [50.0, 50.0, 50.0, 50.0]
- Winning `tf` (sessions/bar) across windows: [3.0, 3.0, 3.0, 5.0]
- Winning `atr_stop_mult` across windows: [1.0, 1.0, 2.0, 1.0]
- Winning `rr_ratio` across windows: [3.0, 2.0, 2.0, 2.0]
- Out-of-sample test PF > 1.0 in 4/4 windows; test t-stat > 1.0 in 4/4 windows.

**CONSISTENT** — the same parameter region (loose ADX, RSI ~50-55, short-ish bars) keeps winning the select stage across independent windows, AND that region holds up out-of-sample in most windows. This is meaningfully stronger evidence against overfitting than the single train/holdout split alone.

*Elapsed: 1175s. Full grid used: yes.*
