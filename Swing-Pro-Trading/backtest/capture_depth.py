"""
capture_depth.py — Level-2 depth-of-book capture + microstructure features.

WHY THIS EXISTS (the free-first plan): real NASDAQ equity L2 (TotalView depth)
is not available on Alpaca and the raw ITCH feed is license-gated to business
entities — the practical retail path is the IBKR API (~$0.50/mo non-pro; see
../L2_NASDAQ_INTEGRATION.md). Rather than pay before a strategy needs it, this
module proves the ENTIRE pipeline — capture → normalize → microstructure
features → storage — for FREE against Alpaca's crypto L2 orderbook (free, 24/7,
uses the keys you already have). The feature math is feed-agnostic: book
imbalance / microprice / depth are computed identically whether the book is
BTC/USD or AAPL. The day you subscribe to IBKR TotalView, only the FEED ADAPTER
changes; book_features() and the storage layer are unchanged.

Adapters:
  • alpaca-crypto  — REST latest-orderbook, FREE, works today (default).
  • ibkr           — Nasdaq TotalView L2 via ib_insync reqMktDepth; stub here,
                     full drop-in code lives in ../L2_NASDAQ_INTEGRATION.md.

Storage: one row per snapshot -> cache/depth/depth_<feed>_<date>.csv
Usage:
  py capture_depth.py --symbol BTC/USD --snaps 10 --interval 2   # bounded test
  py capture_depth.py --symbol ETH/USD --minutes 5               # timed capture

NOT scheduled and NOT a production daemon: this is a proving harness. It graduates
to a scheduled capture only once a pre-registered intraday strategy needs L2
features AND the forward test is healthy (house-rule gating).
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from data import _env

DATA = "https://data.alpaca.markets"
OUT_DIR = Path(__file__).parent / "cache" / "depth"
FIELDS = ["ts", "feed", "symbol", "best_bid", "best_ask", "mid", "microprice",
          "spread", "spread_bps", "bid_sz", "ask_sz", "imb_top",
          "bid_depth", "ask_depth", "imb_depth", "n_bid", "n_ask"]


# ── feed-agnostic microstructure features ───────────────────────────────────
def book_features(bids, asks, depth_levels=None):
    """Compute microstructure features from a normalized book.

    bids: [(price, size), ...] sorted best (highest) first
    asks: [(price, size), ...] sorted best (lowest) first
    depth_levels: cap the depth sums to top-K levels (None = all returned)

    Identical for any venue/asset — this is the whole point of the adapter
    seam. Returns None if either side is empty (crossed/one-sided book)."""
    if not bids or not asks:
        return None
    bb, bsz = bids[0]
    ba, asz = asks[0]
    mid = (bb + ba) / 2.0
    spread = ba - bb
    # microprice: each side's price weighted by the OPPOSITE side's size — leans
    # toward the heavier queue, a classic short-horizon fair-value estimate.
    tot_top = bsz + asz
    micro = (bb * asz + ba * bsz) / tot_top if tot_top > 0 else mid
    imb_top = (bsz - asz) / tot_top if tot_top > 0 else 0.0

    bl = bids[:depth_levels] if depth_levels else bids
    al = asks[:depth_levels] if depth_levels else asks
    bid_depth = sum(s for _, s in bl)
    ask_depth = sum(s for _, s in al)
    tot_depth = bid_depth + ask_depth
    imb_depth = (bid_depth - ask_depth) / tot_depth if tot_depth > 0 else 0.0

    return {
        "best_bid": bb, "best_ask": ba, "mid": mid, "microprice": micro,
        "spread": spread, "spread_bps": (spread / mid * 1e4) if mid else 0.0,
        "bid_sz": bsz, "ask_sz": asz, "imb_top": imb_top,
        "bid_depth": bid_depth, "ask_depth": ask_depth, "imb_depth": imb_depth,
        "n_bid": len(bids), "n_ask": len(asks),
    }


# ── feed adapters (only this layer changes per venue) ───────────────────────
class AlpacaCryptoBook:
    """FREE Alpaca crypto L2 orderbook via REST latest-orderbook. Proves the
    plumbing today with the keys already in the registry. 24/7 — no market
    hours to wait for."""
    feed = "alpaca-crypto"

    def __init__(self):
        self.headers = {"APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
                        "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY")}

    def snapshot(self, symbol):
        q = urllib.parse.urlencode({"symbols": symbol})
        url = f"{DATA}/v1beta3/crypto/us/latest/orderbooks?{q}"
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            ob = json.loads(r.read().decode()).get("orderbooks", {}).get(symbol)
        if not ob:
            return None, None
        bids = [(float(x["p"]), float(x["s"])) for x in ob.get("b", [])]
        asks = [(float(x["p"]), float(x["s"])) for x in ob.get("a", [])]
        bids.sort(key=lambda x: -x[0])
        asks.sort(key=lambda x: x[0])
        return bids, asks


class IBKRDepthBook:
    """Nasdaq TotalView L2 via ib_insync reqMktDepth (MPID market-maker rows).
    Drop-in replacement for AlpacaCryptoBook — implement snapshot() to return
    the SAME (bids, asks) shape and book_features()/storage work unchanged.
    Full working code + subscription steps: ../L2_NASDAQ_INTEGRATION.md."""
    feed = "ibkr-totalview"

    def __init__(self):
        raise NotImplementedError(
            "IBKR feed pending a TotalView subscription — see "
            "L2_NASDAQ_INTEGRATION.md for the ib_insync drop-in.")


class WebullDepthBook:
    """Nasdaq-grade equity L2 via Webull OpenAPI Market Data (Advanced tier:
    order-book depth). Drop-in replacement for the other adapters — implement
    snapshot() to return the SAME (bids, asks) shape and book_features()/storage
    are unchanged. Needs WEBULL_APP_KEY / WEBULL_APP_SECRET in the environment +
    the Advanced Market Data entitlement. Full setup + the gated-execution design
    for the Trading API: ../WEBULL_INTEGRATION.md."""
    feed = "webull-l2"

    def __init__(self):
        raise NotImplementedError(
            "Webull feed pending App Key/Secret + Advanced Market Data "
            "entitlement — see WEBULL_INTEGRATION.md.")


ADAPTERS = {"alpaca-crypto": AlpacaCryptoBook, "ibkr": IBKRDepthBook,
            "webull": WebullDepthBook}


# ── capture loop ────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default="alpaca-crypto", choices=list(ADAPTERS))
    ap.add_argument("--symbol", default="BTC/USD")
    ap.add_argument("--snaps", type=int, default=10, help="number of snapshots")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between snaps")
    ap.add_argument("--minutes", type=float, default=None,
                    help="run for N minutes instead of a fixed count")
    ap.add_argument("--depth-levels", type=int, default=None)
    args = ap.parse_args()

    adapter = ADAPTERS[args.feed]()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_f = OUT_DIR / f"depth_{adapter.feed}_{datetime.now():%Y%m%d}.csv"
    new = not out_f.exists()
    fh = open(out_f, "a", newline="", encoding="utf-8")
    wr = csv.DictWriter(fh, fieldnames=FIELDS)
    if new:
        wr.writeheader()

    deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
    n = spreads = imbs = 0
    i = 0
    while True:
        try:
            bids, asks = adapter.snapshot(args.symbol)
            feats = book_features(bids, asks, args.depth_levels)
            if feats:
                row = {"ts": datetime.now().isoformat(timespec="seconds"),
                       "feed": adapter.feed, "symbol": args.symbol}
                row.update({k: round(v, 6) if isinstance(v, float) else v
                            for k, v in feats.items()})
                wr.writerow(row)
                fh.flush()
                n += 1
                spreads += feats["spread_bps"]
                imbs += feats["imb_top"]
        except Exception as e:
            print(f"[snap {i}] error: {str(e)[:100]}")
        i += 1
        done = (deadline is not None and time.monotonic() >= deadline) or \
               (deadline is None and i >= args.snaps)
        if done:
            break
        time.sleep(args.interval)

    fh.close()
    if n:
        print(f"captured {n} book snapshots -> {out_f}")
        print(f"  {args.symbol} [{adapter.feed}]  avg spread {spreads/n:.2f} bps"
              f"  avg top-imbalance {imbs/n:+.3f}")
    else:
        print(f"no valid snapshots captured (feed={adapter.feed}, symbol={args.symbol})")


if __name__ == "__main__":
    main()
