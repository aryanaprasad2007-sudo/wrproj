# Local Dark-Pool / Order-Flow Analyzer — setup

A self-contained Python tool that runs **on your Mac**, pulls trade & quote data from
Polygon.io, and analyzes off-exchange (dark-pool) activity, block prints, and
top-of-book imbalance. **No `pip install` needed** — it uses only the Python standard
library (works with the system `python3` you already have, 3.9.6).

## 1. Get a Polygon API key (free)
1. Sign up at <https://polygon.io/> → **Dashboard → API Keys** → copy your key.
2. The free **Basic** plan gives delayed data and 5 calls/min. The tick-level
   `trades`/`quotes` endpoints this tool uses generally need the **Starter** plan
   (~$29/mo). If your key isn't authorized, the tool prints a clear message saying so —
   the code still works, you just need a plan that includes tick data.

## 2. Set your key
```bash
export POLYGON_API_KEY="your_key_here"
```
(or pass `--api-key your_key_here` on the command line)

## 3. Run it
```bash
cd "<this folder>"

# Most recent weekday, AAPL, dark-pool + block analysis:
python3 darkpool_orderbook.py AAPL

# A specific day, and also sample top-of-book imbalance:
python3 darkpool_orderbook.py AAPL --date 2024-06-26 --quotes

# On the FREE plan, throttle to stay under 5 calls/min:
python3 darkpool_orderbook.py AAPL --free-tier --max-trade-pages 1
```

## 4. What you'll see
- **Off-exchange ratio** — % of volume printed to FINRA TRFs (dark pools + retail
  internalization). A rising ratio is the headline "dark-pool activity" number.
- **Venue breakdown** — where volume traded, off-exchange venues flagged.
- **Block prints** — the largest individual trades (default ≥10,000 shares).
- **Top-of-book imbalance** (with `--quotes`) — bid vs ask size at the NBBO.

## Flags
| Flag | Purpose |
|---|---|
| `--date YYYY-MM-DD` | Pick the trading day (default: last weekday) |
| `--quotes` | Also pull NBBO quotes for imbalance (more API calls) |
| `--block-size N` | Block threshold in shares (default 10000) |
| `--max-trade-pages N` | Cap pages pulled (each ≤50k trades); keep at 1 on free tier |
| `--free-tier` | Sleep between calls to respect the 5/min free limit |

## Honest limitations
- **"Off-exchange" ≠ pure dark pool.** TRF prints bundle dark pools *and* wholesaler
  internalization of retail orders. The public tape can't fully separate them.
- **Top-of-book ≠ full L2 depth.** Polygon's standard quotes give the best bid/ask
  only. Full multi-level depth (the actual DOM ladder) is a separate premium product.
- **Delayed data** on lower tiers — fine for end-of-day analysis, not for live trading.

## Where this goes next
- Add **real-time** mode via Polygon's websocket (needs a paid real-time plan) so it
  streams live instead of pulling a day at a time.
- Add **CVD over the day** from the trade tape (buy/sell classification) to line up
  with the `iAPE_Backflow.pine` CVD on your TradingView chart.
- Wire alerts (e.g. off-exchange ratio spike) to a webhook / push notification.

*Educational use only. Not financial advice.*
