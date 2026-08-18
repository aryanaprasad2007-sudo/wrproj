# Order Book & Dark Pool — what's possible, and how to use the proxy

Companion notes for `iAPE_Backflow.pine` and the `Swing1m_PRO` system.

---

## 1. The hard constraint (why we can't just "add it" to Pine)

Pine Script (TradingView) only receives **OHLCV bar data**. It has **no access** to:

- **The Level-2 order book / DOM** — no bid/ask ladder, no resting order sizes, no order-flow imbalance. TradingView renders a DOM widget in its UI, but that data never reaches a Pine script.
- **Dark-pool prints** — off-exchange (FINRA TRF/ADF) executions. These are not exposed to Pine, and they are **not even part of the on-exchange volume bars** Pine sees. So you can't reconstruct them from volume.

Anything claiming to show "order book" or "dark pool" *inside a Pine indicator* is showing a **proxy estimated from OHLCV**, not the real thing. `iAPE_Backflow.pine` is honest about being exactly that.

---

## 2. What the proxy gives you today (Path A — free, in TradingView)

`iAPE_Backflow.pine` adds a lower pane with four order-flow approximations:

| Signal | Proxy for | How it's built |
|---|---|---|
| **CVD line** (teal/red) | Net buying vs selling pressure | Splits each *intrabar* candle into buy/sell volume and accumulates it |
| **Bear/Bull "div" labels** | Hidden distribution / accumulation (the dark-pool *behaviour*) | Price makes a new swing high but CVD doesn't (and mirror) |
| **Blue triangles** | Block / institutional participation | Relative volume ≥ threshold (default 2× average) |
| **Orange squares** | Iceberg / absorption | Volume spike **with** an unusually small price range |

**How to read it alongside SWING1_PRO:** treat the proxy as a *confirmation filter*, not a trigger.
- A `Swing1m_PRO` **BUY** is stronger when CVD is rising and/or a **bull div** just printed.
- A **BUY** into a **bear divergence** or **absorption at the highs** is a warning — flow is fighting the entry.
- Mirror everything for SELLs.

### Setup
1. Pine Editor → new tab → paste `iAPE_Backflow.pine` → Save → **Add to chart**. It opens in its own pane below price.
2. Keep `Swing1m_PRO.pine` on the chart as your overlay.
3. On a 1m chart, leave "Auto-pick intrabar timeframe" ON (it uses ~5-second intrabars).

> ⚠️ Intrabar accuracy: TradingView limits how far back `request.security_lower_tf` data goes, so CVD on old history may be approximate or blank. It's accurate on recent/live bars — which is what matters for trading.

---

## 3. Optional: fold the proxy into the entry gate

If you want the *strategy* to actually require order-flow agreement (not just eyeball it), the CVD logic can be merged directly into `Swing1m_PRO_strategy.pine`. The change is small:

```pine
// add near the other filters
[buyV, sellV, barDelta] = request.security_lower_tf(...)   // (port f_delta from the proxy)
cvdRising = cvd >= nz(cvd[1])
// then AND it into the entry intents:
goLong  := goLong  and cvdRising
goShort := goShort and not cvdRising
```

This is a real change to your tested logic, so I'd do it as a separate variant file and re-backtest it head-to-head against the current one rather than overwrite what you have. Say the word and I'll build `Swing1m_PRO_strategy_OF.pine`.

---

## 4. Path B — real order book + dark pool data (when you're ready)

This requires a **paid data feed** and lives **outside Pine** (Python). High-level scope:

### Data providers
| Need | Options | Notes |
|---|---|---|
| **Order book (L2/depth)** | Polygon.io, Databento, Alpaca (L2), IEX Cloud, Nasdaq TotalView | Real-time L2 needs a websocket + usually exchange data fees |
| **Dark pool / off-exchange** | Unusual Whales, Cheddar Flow, SqueezeMetrics (DIX/GEX), FINRA ADF | Most expose REST/websocket APIs; coverage & latency vary a lot |

### Architecture (typical)
```
[Data API websocket] → [Python ingest] → [feature engine: book imbalance,
   dark-pool % of volume, CVD] → [signal logic] → either:
       (a) execute/paper-trade via broker API, or
       (b) POST a webhook alert that TradingView/your phone receives
```

### Realistic effort
- A focused proof-of-concept (one symbol, one provider, compute book-imbalance + dark-pool-ratio, log signals) is a **few days** of work once API keys exist.
- A robust, multi-symbol, live system with execution is a **multi-week** project (reliability, reconnects, rate limits, cost controls, backtest harness on tick data).

### Recommended first step when you get a feed
Pick **one** provider with a free trial (Polygon and Alpaca both have free tiers for delayed/limited L2), and I'll build a small Python script that pulls the book for AAPL, computes top-of-book imbalance + a dark-pool-volume ratio, and prints/plots it. That validates the data quality before you commit to a paid plan or a big build.

---

*Educational use only. Not financial advice.*
