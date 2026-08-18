# Switch vs Parallel — momentum × mean-reversion — 2026-07-09

**Pre-registered question:** should the bot SWITCH between the momentum and mean-reversion engines by regime, or run them in PARALLEL? Decision rule fixed before running: SWITCH wins only if its MAR (CAGR/|maxDD|) beats PARALLEL's by >10%.

**VERDICT: SWITCH**  ·  switch MAR 0.369 vs parallel MAR 0.231 (+59.7%, needed >+10%). Robust: SWITCH>PARALLEL on 4/4 trend classifiers.

**Surprise finding — the premise was wrong.** Momentum↔MR daily-return correlation is **+0.461** — moderately POSITIVE, not the anti-correlation the roadmap assumed. So the switch does NOT win by 'stacking uncorrelated edges' (that was the case FOR parallel, and it's weaker than believed). It wins by **regime-timed drawdown avoidance**: momentum's edge is real (trade PF 2.3) but it bleeds -47.05% in bad regimes; stepping to MR when SPY isn't trending keeps momentum-like CAGR while nearly halving the drawdown. The classifier held momentum 59.4% of days.

|                 |   CAGR% |   maxDD% |   MAR |   vol% |   Sharpe |   tradePF |           final$ |
|:----------------|--------:|---------:|------:|-------:|---------:|----------:|-----------------:|
| Momentum only   |    8.95 |   -47.05 | 0.19  |   13.1 |     0.72 |      2.3  |      1.48756e+06 |
| MR only         |    4.04 |   -14.96 | 0.27  |    7.3 |     0.58 |      1.25 | 348468           |
| PARALLEL 50/50  |    6.65 |   -28.81 | 0.231 |    8.9 |     0.77 |    nan    | 759690           |
| SWITCH (regime) |    9.11 |   -24.67 | 0.369 |   12.3 |     0.77 |    nan    |      1.5576e+06  |

### Robustness — SWITCH MAR across trend classifiers

| Regime rule (hold momentum when…) | MAR |
|---|---|
| SPY>rising 50d (primary) | 0.369 |
| SPY>50d | 0.308 |
| SPY>200d | 0.363 |
| 50d>200d (golden cross) | 0.416 |
| *PARALLEL 50/50 (baseline)* | *0.231* |

All four trend rules beat parallel — the result is not an artifact of the one classifier chosen.

### Caveats before this drives a dollar

1. **In-sample.** 30y, one dataset. Robust to *rule choice*, but not yet forward-validated — it must run as a pre-registered shadow before it touches capital (house rule #2/#3).
2. **Both engines are 0/30.** Neither momentum nor MR has closed a single live audition trade. A switcher on top of two unproven engines is gated behind their auditions first.
3. **Regime-timing risk.** The switch adds a model (the classifier) that can be wrong exactly at turns; the drawdown benefit assumes it calls regimes about as well as it did in-sample.

22-symbol 30y daily basket (incl. era losers GE/IBM/INTC), shared SPY filter, 10% sizing / max 10 concurrent / one cash pool for each engine. Momentum wrapped in a daily-marked shared-capital portfolio to match MR's native portfolio curve. PARALLEL = 50/50 daily rebalance; SWITCH = 100% momentum when SPY is above a rising 50d SMA (decided on the prior close, no lookahead), else 100% MR.

*Backtest on survivor-biased free daily data; overnight gaps can slip stops in reality. Not financial advice.*
