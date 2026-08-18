#!/usr/bin/env python3
"""
alpaca_stream.py — LIVE order-flow on your Mac via Alpaca's free IEX websocket.

Streams real-time trades + quotes and computes, live:
  • CVD (Cumulative Volume Delta) — buy vs sell pressure, trades classified against
    the prevailing bid/ask (quote rule). Shown as session-cumulative + a rolling window.
  • TOP-OF-BOOK IMBALANCE — from the streaming best bid/ask sizes.
  • BLOCK PRINTS — trades at/above a size threshold, alerted the instant they hit.

COST: $0. Alpaca's free market-data feed is the IEX feed and is REAL-TIME (not delayed).
HONEST LIMITS:
  • IEX is ~2–3% of total US volume, so this tape is a real-time SAMPLE, not the whole
    market. CVD direction is meaningful; absolute volume is a fraction of consolidated.
  • Quotes are IEX best bid/ask, not the full consolidated NBBO.
  • Dark-pool / off-exchange (TRF) prints are NOT on this feed at all — keep the delayed
    Polygon tool (darkpool_orderbook.py) for that context number.

DEPENDENCY: websocket-client  ->  pip install websocket-client   (see requirements.txt)
SELF-TEST (no keys, no network, no deps):  python3 alpaca_stream.py --selftest

Educational use only. Not financial advice.
"""

import argparse
import json
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone

FEED_URL = "wss://stream.data.alpaca.markets/v2"  # + /iex (free) or /sip (paid)


# ──────────────────────────────────────────────────────────────────────────────
# Analytics — pure, dependency-free, unit-testable in isolation from the socket.
# ──────────────────────────────────────────────────────────────────────────────
class FlowState:
    def __init__(self, symbol, block_size=5000, roll_seconds=60):
        self.symbol = symbol
        self.block_size = block_size
        self.roll_seconds = roll_seconds
        # quote state (top of book)
        self.bid_px = None
        self.ask_px = None
        self.bid_sz = 0
        self.ask_sz = 0
        # cvd state
        self.cvd = 0                      # session-cumulative signed volume
        self.roll = deque()               # (recv_ts, signed_volume) within window
        self.roll_sum = 0
        # totals
        self.n_trades = 0
        self.total_vol = 0
        self.buy_vol = 0
        self.sell_vol = 0
        self.blocks = []                  # (size, price, side, ts_str)

    # ---- quotes ----
    def on_quote(self, q):
        # Alpaca quote fields: bp/ap = bid/ask price, bs/as = bid/ask size (in round lots? -> shares)
        self.bid_px = q.get("bp", self.bid_px)
        self.ask_px = q.get("ap", self.ask_px)
        self.bid_sz = q.get("bs", 0) or 0
        self.ask_sz = q.get("as", 0) or 0

    def imbalance(self):
        tot = self.bid_sz + self.ask_sz
        return ((self.bid_sz - self.ask_sz) / tot) if tot else 0.0

    # ---- trades ----
    def classify(self, price):
        """Quote-rule classification: +1 buy / -1 sell, using current bid/ask."""
        if self.ask_px is not None and price >= self.ask_px:
            return 1
        if self.bid_px is not None and price <= self.bid_px:
            return -1
        if self.bid_px is not None and self.ask_px is not None:
            mid = (self.bid_px + self.ask_px) / 2.0
            return 1 if price >= mid else -1
        return 0  # no quote context yet -> neutral

    def on_trade(self, t, recv_ts=None):
        recv_ts = recv_ts if recv_ts is not None else time.monotonic()
        size = int(t.get("s", 0) or 0)
        price = float(t.get("p", 0.0) or 0.0)
        side = self.classify(price)
        signed = side * size

        self.n_trades += 1
        self.total_vol += size
        if side > 0:
            self.buy_vol += size
        elif side < 0:
            self.sell_vol += size
        self.cvd += signed

        # rolling window
        self.roll.append((recv_ts, signed))
        self.roll_sum += signed
        cutoff = recv_ts - self.roll_seconds
        while self.roll and self.roll[0][0] < cutoff:
            _, sv = self.roll.popleft()
            self.roll_sum -= sv

        is_block = size >= self.block_size
        if is_block:
            ts_str = self._ts(t.get("t"))
            self.blocks.append((size, price, side, ts_str))
        return side, size, price, is_block

    @staticmethod
    def _ts(rfc3339):
        if not rfc3339:
            return datetime.now(timezone.utc).strftime("%H:%M:%S")
        try:
            # trim nanoseconds to micros for fromisoformat compatibility
            s = rfc3339.replace("Z", "+00:00")
            if "." in s:
                head, tail = s.split(".")
                frac, tz = tail[:6], tail[len(tail.split('+')[0]):] if "+" in tail else "+00:00"
                s = f"{head}.{frac[:6]}{('+' + tail.split('+')[1]) if '+' in tail else ''}"
            return datetime.fromisoformat(s).astimezone(timezone.utc).strftime("%H:%M:%S")
        except Exception:
            return datetime.now(timezone.utc).strftime("%H:%M:%S")

    # ---- display ----
    def status_line(self):
        imb = self.imbalance()
        imb_side = "BID" if imb > 0 else "ASK"
        roll_side = "BUY " if self.roll_sum >= 0 else "SELL"
        bbo = "    --/--"
        if self.bid_px is not None and self.ask_px is not None:
            bbo = f"{self.bid_px:.2f}x{self.bid_sz:<4d} / {self.ask_px:.2f}x{self.ask_sz:<4d}"
        return (
            f"{datetime.now().strftime('%H:%M:%S')}  {self.symbol}  "
            f"CVD {self.cvd:>+8d}  "
            f"roll{self.roll_seconds}s {roll_side}{abs(self.roll_sum):>6d}  "
            f"imb {imb*100:+5.1f}%({imb_side})  "
            f"vol {self.total_vol:>8,d}  "
            f"BBO {bbo}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Self-test — proves the analytics with synthetic Alpaca-shaped messages. No deps.
# ──────────────────────────────────────────────────────────────────────────────
def run_selftest():
    print("Running analytics self-test (no network / no keys)...\n")
    fs = FlowState("AAPL", block_size=5000, roll_seconds=60)

    # Set a book: bid 100.00 x 300, ask 100.02 x 100  -> ask-heavy
    fs.on_quote({"bp": 100.00, "ap": 100.02, "bs": 300, "as": 100})
    assert fs.imbalance() > 0, "300 bid vs 100 ask should be bid-heavy (+)"

    # Trades: at-ask buy 200, at-bid sell 500, midprice 100.01 -> buy, a block buy 6000 at ask
    side, *_ = fs.on_trade({"p": 100.02, "s": 200, "t": None}); assert side == 1
    side, *_ = fs.on_trade({"p": 100.00, "s": 500, "t": None}); assert side == -1
    side, *_ = fs.on_trade({"p": 100.01, "s": 100, "t": None}); assert side == 1  # >= mid
    side, sz, px, is_block = fs.on_trade({"p": 100.02, "s": 6000, "t": None})
    assert side == 1 and is_block, "6000-share at-ask trade should be a buy block"

    expected_cvd = 200 - 500 + 100 + 6000
    assert fs.cvd == expected_cvd, f"CVD {fs.cvd} != {expected_cvd}"
    assert fs.buy_vol == 200 + 100 + 6000 and fs.sell_vol == 500
    assert len(fs.blocks) == 1

    print("  ✓ quote imbalance sign correct")
    print("  ✓ trade buy/sell classification (at-ask / at-bid / mid) correct")
    print("  ✓ CVD accumulation correct  (cvd =", fs.cvd, ")")
    print("  ✓ block detection correct   (1 block @", fs.blocks[0][0], "sh )")
    print("\n  status line preview:")
    print("    " + fs.status_line())
    print("\nAll checks passed. Plug in Alpaca keys and run live (see README).")


# ──────────────────────────────────────────────────────────────────────────────
# Live streaming (imports websocket-client lazily so --selftest needs no deps)
# ──────────────────────────────────────────────────────────────────────────────
def run_stream(args):
    try:
        import websocket  # websocket-client
    except ImportError:
        print("ERROR: this needs the 'websocket-client' package.\n"
              "  python3 -m pip install websocket-client\n"
              "(or:  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt)",
              file=sys.stderr)
        sys.exit(2)

    key = args.key or os.environ.get("APCA_API_KEY_ID")
    secret = args.secret or os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        print("ERROR: missing Alpaca keys. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY,\n"
              "       or pass --key / --secret.  Get them at app.alpaca.markets → API Keys.",
              file=sys.stderr)
        sys.exit(2)

    symbol = args.symbol.upper()
    fs = FlowState(symbol, block_size=args.block_size, roll_seconds=args.roll)
    url = f"{FEED_URL}/{args.feed}"
    state = {"authed": False, "last_status": 0.0}

    def on_open(ws):
        ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))

    def on_message(ws, message):
        try:
            msgs = json.loads(message)
        except json.JSONDecodeError:
            return
        for m in msgs:
            T = m.get("T")
            if T == "success" and m.get("msg") == "authenticated":
                state["authed"] = True
                ws.send(json.dumps({"action": "subscribe",
                                    "trades": [symbol], "quotes": [symbol]}))
                print(f"✓ authenticated — subscribed to {symbol} ({args.feed} feed). "
                      f"Streaming live...\n", file=sys.stderr)
            elif T == "error":
                print(f"✗ Alpaca error {m.get('code')}: {m.get('msg')}", file=sys.stderr)
                if m.get("code") in (402, 404, 409):  # auth failed / not found / conn limit
                    ws.close()
            elif T == "q":
                fs.on_quote(m)
            elif T == "t":
                side, sz, px, is_block = fs.on_trade(m)
                if is_block:
                    tag = "BUY " if side > 0 else ("SELL" if side < 0 else "??? ")
                    print(f"  ●● BLOCK {tag} {sz:>7,d} sh @ ${px:<.2f}   "
                          f"[{fs._ts(m.get('t'))} UTC]")
            # periodic status
            now = time.monotonic()
            if now - state["last_status"] >= args.interval:
                state["last_status"] = now
                print(fs.status_line())

    def on_error(ws, err):
        print(f"  [ws error] {err}", file=sys.stderr)

    def on_close(ws, code, msg):
        print(f"  [ws closed] {code} {msg}", file=sys.stderr)

    print(f"Connecting to {url} ...", file=sys.stderr)
    backoff = 2
    while True:
        ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message,
                                    on_error=on_error, on_close=on_close)
        ws.run_forever(ping_interval=20, ping_timeout=10)
        if args.no_reconnect:
            break
        print(f"  reconnecting in {backoff}s...", file=sys.stderr)
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)
        state["authed"] = False


def main():
    ap = argparse.ArgumentParser(description="Live order-flow via Alpaca IEX websocket.")
    ap.add_argument("symbol", nargs="?", default="AAPL", help="Symbol (default AAPL)")
    ap.add_argument("--feed", default="iex", choices=["iex", "sip"],
                    help="iex = free real-time (default); sip = paid full-market")
    ap.add_argument("--key", default=None, help="Alpaca API key id (or APCA_API_KEY_ID)")
    ap.add_argument("--secret", default=None, help="Alpaca API secret (or APCA_API_SECRET_KEY)")
    ap.add_argument("--block-size", type=int, default=5000, help="Block alert threshold (shares)")
    ap.add_argument("--roll", type=int, default=60, help="Rolling CVD window (seconds)")
    ap.add_argument("--interval", type=float, default=2.0, help="Status print interval (seconds)")
    ap.add_argument("--no-reconnect", action="store_true", help="Exit on disconnect instead of retrying")
    ap.add_argument("--selftest", action="store_true", help="Run analytics self-test (no keys/deps)")
    args = ap.parse_args()

    if args.selftest:
        run_selftest()
        return
    run_stream(args)


if __name__ == "__main__":
    main()
