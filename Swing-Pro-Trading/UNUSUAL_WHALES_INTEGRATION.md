# Unusual Whales × iAPE — integration plan

> **STATUS (2026-07-02): DEFERRED.** Ari's call: no paid subscription until the
> orthogonal-data hypothesis shows reliable results on free data first. The $0
> substitute stack (SqueezeMetrics DIX/GEX + FINRA daily short volume + Alpaca
> options snapshots) lives in `backtest/free_data.py` and is tested by
> `backtest/run_orthogonal_test.py`. Revisit this plan only if the free stack
> proves the concept AND intraday/per-ticker resolution becomes the bottleneck.

*2026-07-01. Companion to `backtest/uw_data.py` (client, ready) and
`OrderFlow_DarkPool_Notes.md` (why Pine can't do this natively).*

## Why UW instead of more indicators

Every gate in iAPE today (MACD, Impulse, RSI, ADX, EMA trend) is computed
from the same OHLCV series — they're correlated views of one signal. The
2026-07-01 ablation showed exactly what that buys: knocking out any single
momentum gate barely moved results. UW data is **orthogonal**: options
positioning, off-exchange prints, and dealer-gamma state are information the
price bars simply don't contain. This is "Path B" from the dark-pool notes,
minus building an L2 ingest ourselves.

## What we'd pull (all confirmed in their API docs)

| Feed | Endpoint | Formula role |
|---|---|---|
| Dark-pool prints per ticker | `/api/darkpool/{ticker}?date=` | Off-exchange % + block detection → institutional-participation filter (replaces the OHLCV guesswork in `iAPE_Backflow.pine`) |
| Net premium ticks | `/api/stock/{t}/net-prem-ticks?date=` | Intraday net call/put premium = an **options-flow CVD** → candidate entry gate: longs only when net call premium is rising |
| Market tide | `/api/market/market-tide?date=` | Market-wide options flow → upgrade/complement to the SPY-vs-EMA50 market filter (which ablation says is one of the few filters that genuinely works) |
| Greek exposure / GEX | `/api/stock/{t}/greek-exposure`, `spot-exposures` | Dealer-gamma regime switch: **+GEX → mean-revert tape** (favour pullback entries, tighter targets); **−GEX → trend-amplifying** (favour momentum entries, let winners run) |
| Flow alerts | `/api/option-trades/flow-alerts` | Live confirmation layer only (not backtestable per-signal without the $250/mo historical option-trades add-on) |

Auth: `Authorization: Bearer <token>`, REST + WebSocket. API access is a
separate paid product from the normal UW subscription — check
[unusualwhales.com/pricing?product=api](https://unusualwhales.com/pricing?product=api)
for current tiers before buying. The **$250/mo full-market historical option
trades** feed is NOT needed for phases 1–2; daily-granularity historical
endpoints (dark pool by date, tide by date, GEX by date) come with standard API
access.

## Phases — each one gated on evidence, same discipline as the ablation

**Phase 1 — Validate the features (no formula changes).**
Once a token exists: `py uw_data.py --probe`, then pull ~60 days of dark-pool
ratio, net-prem ticks, and GEX for the basket, align them to the 5m bars, and
run the SAME ablation harness **in reverse**: instead of removing filters,
ADD each UW gate to v2-long and measure Δexpectancy. A UW feature earns a
place in the formula exactly the way the old filters had to defend theirs.
Candidate gates to test:
  1. `net_prem_rising` — net call premium above its 30-min average at entry
  2. `dp_ratio_ok` — dark-pool % of volume below/above its 20-day mean (test both signs — heavy off-exchange can be accumulation *or* distribution)
  3. `tide_aligned` — market tide net-call-premium slope agrees with trade direction
  4. `gex_regime` — only take pullback entries when GEX > 0, only momentum entries when GEX < 0

**Phase 2 — Wire the survivors into the formula.**
Python harness first (walk-forward proof), then live: UW WebSocket/poller →
small local service → webhook → TradingView alert or straight to the
`iAPE` chart via a companion indicator's "wire-in" inputs (the
`useExtConfirm` sources in `SWING_PRO_strategy.pine` were built for exactly
this). Merges cleanly with `alpaca_stream.py`'s CVD — equities tape from
Alpaca, options tape from UW, one confirmation service.

**Phase 3 — (optional, later) historical flow-alerts backtest** if phases 1–2
show edge and the $250/mo add-on justifies itself.

## Cost reality check

Standard API access is the only prerequisite for phases 1–2. Before
subscribing, confirm on the pricing page that it includes: dark pool by date,
market tide by date, net-prem-ticks by date, greek-exposure by date. If a
sales chat is needed, that's the exact question list.

*Educational use only. Not financial advice.*
