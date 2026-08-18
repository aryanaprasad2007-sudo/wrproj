# TF3 shadow forward audition — refreshed 2026-07-31

Status: **ARMED** · audition start 2026-07-31 · last completed bar 2026-07-30 · 22/22 symbols loaded · SHADOW ONLY — no orders.

Config: `swing_pro.config_v22(trade_dir="long", use_htf_trend=False, adx_min=15, rsi_long_level=50, atr_stop_mult=1.5, rr_ratio=2.0)` on 3-trading-session bars (`run_timeframe_scan.group_bars`), 22-symbol basket — the train/holdout sweep winner (reports/holdout_sweep_2026-07-30.md).

Benchmark (pre-registered, holdout 2015-2026, n=210): PF 2.99, win 51.4%, expR 0.648R, t=5.36. Judge at ≥30 closed shadow trades — 0/30.

## Shadow book vs benchmark

|                     |   closed | net   | pf   | win%   | expR   | t    |
|:--------------------|---------:|:------|:-----|:-------|:-------|:-----|
| shadow              |        0 | 0     | n/a  | n/a    | n/a    | n/a  |
| benchmark (holdout) |      210 | —     | 2.99 | 51.4   | 0.648  | 5.36 |

## Open shadow positions

*(none)*

*Deterministic recompute from audition start each run; engine = swing_pro.py config_v22 exactly as validated in the holdout sweep. Not financial advice.*
