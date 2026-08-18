# NASDAQ Level-2 (depth-of-book) integration plan

**Status (2026-07-06):** plumbing built & proven for free; real Nasdaq feed is a
paid subscription away and **deliberately not yet purchased** — see "Discipline
gate" below. The capture/feature/storage code (`backtest/capture_depth.py`) is
live and verified against a free book; only the *feed adapter* is missing for
Nasdaq equities.

---

## 1. The access reality (researched 2026-07-06)

There is **no free, open, real-time NASDAQ depth-of-book** for an individual.

| Source | Gives you | Cost / catch |
|---|---|---|
| **Alpaca** (current broker) | Equities: **L1 only** (trades + NBBO), even on paid SIP. Crypto: free L2 orderbook. | No equity depth at any tier — dead end for Nasdaq L2. |
| **IBKR API** — `reqMktDepth` → `updateMktDepthL2` | Live Nasdaq **TotalView** depth (aggregated price levels; MPID market-maker rows available), pullable in Python (`ib_insync`) | **~$0.50/mo non-professional** exchange fee (vs $13.50 pro). Needs an IBKR account + the "NASDAQ TotalView-OpenView EDS" market-data subscription enabled for API/off-platform use. **← the practical retail path.** |
| **Databento** `XNAS.ITCH` | Full ITCH: MBO (every order add/cancel/execute), MBP-10 depth, historical + live | **Historical** = accessible pay-as-you-go for research/backtests. **Live real-time** is gated by a Nasdaq license restricted to business entities (~$15/mo non-pro *if* you qualify). |
| IEX DEEP | Real depth-of-book — but **IEX's book only** (~2–3% of consolidated volume) | Not a Nasdaq substitute; usable only to prototype plumbing. |
| Nasdaq direct feed / NCDS (Kafka) / co-lo | The raw source | Enterprise pricing + business-entity license. Not retail. |

**Conclusion:** for live Nasdaq equity L2, **IBKR TotalView via the API is the
only affordable, individual-accessible route** (~$0.50/mo). Databento is the tool
for *historical* ITCH research if we ever want to backtest microstructure edges.

Sources: [Alpaca Data](https://alpaca.markets/data) · [Databento XNAS.ITCH](https://databento.com/datasets/XNAS.ITCH) · [IBKR TWS API — Market Depth](https://interactivebrokers.github.io/tws-api/market_depth.html) · [IBKR Market Data Subscriptions](https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/) · [Nasdaq US Equities Price List](https://www.nasdaqtrader.com/content/ProductsServices/PriceList/Nasdaq_US_Equities_Price_List_2025.pdf)

---

## 2. What's already built (free, verified)

`backtest/capture_depth.py` — a feed-agnostic L2 capture harness:

- **`book_features(bids, asks)`** — pure, venue-independent microstructure math:
  mid, **microprice**, spread (abs + bps), top-of-book sizes, **top-level
  imbalance**, N-level **depth imbalance**, book widths. Identical output for a
  BTC/USD book or an AAPL book.
- **`AlpacaCryptoBook`** adapter — FREE, 24/7, uses your existing keys. Proven
  2026-07-06 on BTC/USD: 100×63 levels, ~10 bps spread, coherent imbalance.
- **`IBKRDepthBook`** adapter — stub today; the drop-in is section 4.
- Storage: `cache/depth/depth_<feed>_<date>.csv` (schema = `FIELDS`).

**The seam:** swapping crypto → Nasdaq changes ONLY the adapter class. Everything
downstream (features, CSV schema, any future backtest that reads `cache/depth/`)
is unchanged.

---

## 3. Subscription steps (one-time, when a strategy justifies it)

1. Open & fund an **Interactive Brokers** account (IBKR Lite is fine for data).
2. Client Portal → **Settings → Market Data Subscriptions** → add
   **"NASDAQ TotalView-OpenView (Network C/UTP)"**. Certify **Non-Professional**
   to get the ~$0.50/mo rate. Enable it for **API/off-platform** use.
3. Install **IB Gateway** (headless) or **TWS**; enable *API → Socket clients*,
   note the port (7497 TWS-paper / 4001 Gateway-live / 4002 Gateway-paper).
4. `pip install ib_insync`.
5. Start IB Gateway (must stay running — it holds the market-data session).

---

## 4. Drop-in IBKR adapter (replaces the stub in `capture_depth.py`)

```python
class IBKRDepthBook:
    """Nasdaq TotalView L2 via ib_insync reqMktDepth. Same (bids, asks) shape
    as AlpacaCryptoBook, so book_features()/storage are unchanged."""
    feed = "ibkr-totalview"

    def __init__(self, host="127.0.0.1", port=7497, client_id=7, rows=10):
        from ib_insync import IB
        self.ib = IB()
        self.ib.connect(host, port, clientId=client_id)
        self.rows = rows
        self._tickers = {}

    def _ticker(self, symbol):
        from ib_insync import Stock
        if symbol not in self._tickers:
            c = Stock(symbol, "ISLAND", "USD")      # ISLAND = Nasdaq book direct
            self.ib.qualifyContracts(c)
            # isSmartDepth=False => single-venue (Nasdaq) TotalView depth
            self._tickers[symbol] = self.ib.reqMktDepth(
                c, numRows=self.rows, isSmartDepth=False)
            self.ib.sleep(1.0)                       # let the book populate
        return self._tickers[symbol]

    def snapshot(self, symbol):
        t = self._ticker(symbol)
        self.ib.sleep(0)                             # drain pending L2 updates
        bids = [(lvl.price, lvl.size) for lvl in t.domBids]
        asks = [(lvl.price, lvl.size) for lvl in t.domAsks]
        return bids, asks
```

Then: `py capture_depth.py --feed ibkr --symbol AAPL --minutes 30`
(equity symbols use a plain ticker, no `/`). Note: IBKR sizes are in **round
lots (×100 shares)** — normalize if you want share-equivalent depth vs the
crypto book's native units.

---

## 5. Discipline gate — do NOT buy the feed ahead of the strategy

Per the house rules ([[swing-pro-roadmap]]) and the measured record:

- **None of the three validated systems use L2.** SP-D (flagship) and MR-1 are
  **daily** — depth is irrelevant. v2.2 is 5m, and the MTF study already found
  **1m data helped execution, not selection**, with tight stops dying to
  sub-minute noise. L2 is a finer *execution/microstructure* input for a
  strategy that does not exist in the suite yet.
- **Live flow capture is gated on forward-test health** (same rule that governs
  `capture_flow.py`). L2 inherits that gate.

**Therefore the sequence is:**
1. (Done) Build & prove the pipeline for free. ✅
2. Design a *specific* intraday hypothesis that needs depth (e.g. an execution
   layer for variant B: enter on the passive side when `imb_depth` favors us;
   or a microprice-vs-mid entry-timing filter).
3. Pre-register a test of that hypothesis on **fresh** intraday data (never the
   retired 2y well). For live L2 that means: subscribe, run `capture_depth.py`
   scheduled for a few weeks to accrue `cache/depth/`, THEN test.
4. Only if it validates (≥ its pre-registered bar) does it earn a shadow
   audition; only if the audition passes does it touch real orders.

Databento historical ITCH is the shortcut for step 3 if we want to skip the
weeks of live accrual for an initial read (pay-as-you-go, research-licensed).

---

## 6. When it's live — how it plugs into the cockpit

An L2-driven execution layer or strategy scores through the same referee as
everything else: reconstruct round-trips in `forward_review.py`, and the
combined [cockpit](Swing-Pro-Trading/cockpit.html) gains a 4th sleeve card with
win rate / PF / expectancy vs a pre-registered benchmark. No special-casing.
