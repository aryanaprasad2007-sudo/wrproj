# Regime breakdown of the 2026-07-30 holdout winner — 2026-07-31

Config: `tf=3 adx_min=15 rsi_long=50 stop=1.5xATR rr=2.0` · engine `swing_pro.config_v22` · 22/22-symbol basket (`run_daily_30y.SYMBOLS`) · FULL 1995-2026 sample, no train/holdout split (descriptive only).

Momentum classifier: frozen rule from `switch_shadow.py` (registered 2026-07-11) — SPY close > rising 50d SMA, decided on the prior daily close. Reused verbatim. Vol classifier: rolling 20d SPY daily-return stdev, same prior-close lag convention, bucketed against the vol series' own full-history median. Both computed on DAILY SPY bars independent of the 3-session bars the engine trades on.

**Overall (all closed trades, unsplit): n=523 PF=3.082 win%=51.1 expR=0.6904 t=8.31**

## Two-way splits

| bucket                                     |   n |    pf |   win% |   expR |    t |
|:-------------------------------------------|----:|------:|-------:|-------:|-----:|
| Momentum (SPY above rising 50d)            | 445 | 2.797 |   49.7 | 0.6264 | 7.05 |
| Non-momentum (SPY below / 50d not rising)  |  78 | 5.075 |   59   | 1.055  | 4.64 |
| High-vol (20d SPY vol > historical median) | 187 | 3.359 |   52.9 | 0.7946 | 5.44 |
| Low-vol (20d SPY vol <= historical median) | 336 | 2.912 |   50   | 0.6323 | 6.29 |

## Four-way split (momentum x vol)

| bucket                  |   n |    pf |   win% |   expR |    t |
|:------------------------|----:|------:|-------:|-------:|-----:|
| momentum x high-vol     | 140 | 2.985 |   51.4 | 0.7078 | 4.32 |
| momentum x low-vol      | 305 | 2.706 |   48.9 | 0.5891 | 5.57 |
| non-momentum x high-vol |  47 | 4.483 |   57.4 | 1.0531 | 3.34 |
| non-momentum x low-vol  |  31 | 6.921 |   61.3 | 1.0579 | 3.3  |

## Verdict

REGIME-UNIVERSAL — PF > 1.0 in all four momentum x vol buckets (each with >=20 trades); the edge is not concentrated in one regime.

This is descriptive context on where the edge concentrates, not a reason to add regime-gating to any live config — a similar idea was already tested and rejected for single-symbol trading on 2026-07-30. No orders were placed, no broker or Pine state was touched.
