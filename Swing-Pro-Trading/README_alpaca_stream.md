# Live Order-Flow Stream (Alpaca IEX) — setup

Real-time CVD, top-of-book imbalance, and block-print alerts on your Mac, streaming
from Alpaca's **free IEX websocket feed**. Cost: **$0**.

## 1. Create a free Alpaca account & get keys
1. Sign up at <https://alpaca.markets> (a **paper-trading** account is fine — no deposit).
2. In the dashboard (<https://app.alpaca.markets>) → **API Keys** → **Generate**.
3. Copy the **Key ID** and **Secret Key** (the secret is shown once — save it).

## 2. Install the one dependency
The system `python3` has no websocket client, so install `websocket-client`. Use a
virtual environment so nothing touches system Python:
```bash
cd "<this folder>"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
(Or just: `python3 -m pip install --user websocket-client`)

## 3. Set your keys
```bash
export APCA_API_KEY_ID="your_key_id"
export APCA_API_SECRET_KEY="your_secret"
```
(or pass `--key ... --secret ...` on the command line)

## 4. Run it (during US market hours for live trades)
```bash
python3 alpaca_stream.py AAPL                 # live CVD / imbalance / blocks
python3 alpaca_stream.py TSLA --block-size 2000 --roll 120 --interval 1
```
You'll see a status line a few times a second plus instant `●● BLOCK` alerts:
```
14:31:02  AAPL  CVD   +12400  roll60s BUY  3100  imb +18.4%(BID)  vol  742,300  BBO 211.04x500 / 211.05x300
  ●● BLOCK BUY   8,000 sh @ $211.05   [18:31:04 UTC]
```

### What each field means
| Field | Meaning |
|---|---|
| `CVD` | Session-cumulative signed volume (buys − sells). Rising = net buying pressure. |
| `roll60s` | Same, but only the last 60s — short-term flow direction for scalp timing. |
| `imb` | Top-of-book size imbalance: `+` = more size on the bid (buy pressure). |
| `vol` | Total shares seen this session (IEX sample). |
| `BBO` | Best bid/ask price × size. |
| `●● BLOCK` | A trade ≥ your `--block-size`, classified buy/sell, alerted immediately. |

## 5. Verify the math anytime (no keys, no deps, no network)
```bash
python3 alpaca_stream.py --selftest
```

## Flags
| Flag | Default | Purpose |
|---|---|---|
| `--feed iex\|sip` | `iex` | `iex` = free real-time; `sip` = paid full-market feed |
| `--block-size N` | 5000 | Block alert threshold (shares) |
| `--roll N` | 60 | Rolling-CVD window (seconds) |
| `--interval N` | 2.0 | How often the status line prints (seconds) |
| `--no-reconnect` | off | Exit on disconnect instead of auto-retrying |

## Honest limitations (read these)
- **IEX ≈ 2–3% of US volume.** This is a real-time *sample*. CVD/imbalance *direction*
  is meaningful; absolute volume is a fraction of the consolidated market. Upgrade path:
  `--feed sip` with Alpaca's paid real-time SIP add-on (~$99/mo) for full-market coverage.
- **No dark-pool data here.** Off-exchange (TRF) prints are not on this feed. Keep
  `darkpool_orderbook.py` (delayed Polygon) running alongside for the dark-pool ratio —
  that's your slow *context* signal; this stream is your fast *timing* signal.
- **Latency:** event → your Mac is typically tens to a few hundred ms (your internet),
  with local compute negligible. Genuinely "reasonably close" to live.

## How this fits the SWING1_PRO system
- This stream = **fast timing layer** (real-time, free): is flow confirming a BUY *right now*?
- `darkpool_orderbook.py` = **slow context layer** (delayed, cheap): is institutional /
  off-exchange flow accumulating or distributing today?
- `iAPE_Backflow.pine` = the same ideas drawn **on your TradingView chart** for visual confluence.

*Educational use only. Not financial advice.*
