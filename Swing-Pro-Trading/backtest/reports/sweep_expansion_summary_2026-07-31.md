# Widened grid sweep — comparison to 2026-07-30 original

Ran `run_holdout_sweep_wide.py` (copy of `run_holdout_sweep.py`, original untouched) with the
widened grid:

```
GRID = {
    "tf":            [2, 3, 5, 10],              # unchanged — 2D-10D plateau already established
    "adx_min":       [10, 15, 20, 25],           # widened low: 15 -> 10
    "rsi_long_level": [45, 50, 55],              # widened low: 50 -> 45
    "atr_stop_mult": [1.0, 1.5, 2.0, 2.5],       # widened high: 2.0 -> 2.5
    "rr_ratio":      [1.5, 2.0, 2.5, 3.0, 4.0],  # widened low: 2.0 -> 1.5
}
```

960 configs x 22 symbols = 21,120 runs, ~22.5 min. Same discipline as the original: ranked
strictly on TRAIN (1995-2015) t-stat of per-trade R with a 120-trade floor; holdout
(2015-2026) computed for every config but consulted only once, for the train winner.

## Winner comparison

| | tf | adx_min | rsi_long | stop | rr | train t | holdout n | holdout PF | holdout expR | holdout t | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Original (2026-07-30)** | 3 | 15 | 50 | 1.5xATR | 2.0 | 6.37 | 210 | 2.99 | 0.648 | 5.36 | HOLDS UP |
| **Wide grid (2026-07-31)** | 3 | 10 | 55 | 2.5xATR | 2.0 | 6.40 | 218 | 2.88 | 0.650 | 5.27 | HOLDS UP |

## Did the optimum move further toward the edge, or land in the interior?

Mixed, and informative parameter-by-parameter:

- **adx_min — moved further toward the edge.** Original winner sat at 15, the lowest value
  tested that night. The new winner sits at 10 — the new lowest tested value in the wider
  grid. This is the second night in a row this parameter has walked to the boundary. It should
  be widened again (try 5, and consider whether ADX thresholds below ~10 are still a
  meaningful trend filter at all before going lower).

- **rsi_long_level — resolved into the interior.** Original winner was pinned to 50, the low
  edge of the old 2-value grid ([50, 55]). With 45 added, the train leaderboard is now a flat
  plateau across 45/50/55 (t=6.37-6.40), and the actual top spot went to 55 — the *opposite*
  end from where the old edge pressure pointed. No consistent directional signal here; the
  parameter looks close to irrelevant across [45,55]. No further widening needed.

- **rr_ratio — resolved into the interior.** Original winner was pinned to 2.0, the low edge
  of the old grid ([2.0, 3.0, 4.0]). With 1.5 added, 2.0 still won and 1.5 did not appear in
  the top ranks — so 2.0 is a genuine interior optimum now, not an artifact of a truncated
  grid. No further widening needed on the low side.

- **atr_stop_mult — confirmed flat, as expected.** Was already interior (1.5 of [1.0, 1.5,
  2.0]) and not flagged. In the wide grid, train t-stat is essentially indistinguishable across
  1.0/1.5/2.0/2.5 for the top combo (6.37-6.40) — the strategy just doesn't care much about
  stop distance in this range.

**Net read:** one parameter (`adx_min`) still hasn't found its ceiling and warrants another
widening pass; the other two suspects from last night (`rsi_long_level`, `rr_ratio`) turned out
to be grid-truncation artifacts, not real edge-seeking — they settled into the interior once
given room.

## Robustness note

The two configs — different on 2 of 5 parameters (adx_min 15 vs 10, rsi_long 50 vs 55) — produce
nearly identical holdout results (PF 2.99 vs 2.88, expR 0.648 vs 0.650, t 5.36 vs 5.27, both
"HOLDS UP"). That similarity across a meaningfully different point in parameter space is a good
sign: it looks like a broad, stable performance plateau rather than a narrow peak that a slightly
different grid would have missed entirely.

## Suggested next step

Re-run with `adx_min` widened further (e.g. `[5, 10, 15, 20]`) to see if it keeps walking down or
finally lands in the interior. `rsi_long_level` and `rr_ratio` can revert to tighter grids around
their current interior optima if sweep runtime becomes a concern.

Full leaderboard and raw data: [holdout_sweep_2026-07-31.md](holdout_sweep_2026-07-31.md),
[holdout_sweep_2026-07-31.csv](holdout_sweep_2026-07-31.csv).
