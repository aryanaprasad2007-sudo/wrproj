#!/usr/bin/env python3
"""
darkpool_orderbook.py — local order-flow / dark-pool analyzer for US equities.

Runs entirely on your machine. Standard library only (no pip install needed).
Data comes from Polygon.io's REST API; analysis happens locally.

WHAT IT MEASURES (honestly):
  • DARK-POOL / OFF-EXCHANGE VOLUME — Polygon tags every trade with the venue that
    reported it. Trades reported to a FINRA TRF (Trade Reporting Facility) executed
    off-exchange. That bucket = dark pools + wholesaler/retail internalization. The
    public tape CANNOT fully separate "true dark pool" from internalized retail flow,
    so treat this as "off-exchange %", which is the honest, standard definition.
  • BLOCK PRINTS — individual trades at/above a size threshold (institutional size).
  • TOP-OF-BOOK IMBALANCE — Polygon's quote feed gives the NBBO (best bid/ask) and
    their sizes. That's TOP of book, not the full Level-2 depth ladder (full multi-
    level depth is a separate, pricier Polygon product). Imbalance = bid vs ask size.
  • TRADE-SIDE PRESSURE — classifies each trade as buy/sell vs the prevailing quote
    midpoint when quotes are available, else by uptick/downtick.

PLAN NOTE: the tick-level /v3/trades and /v3/quotes endpoints generally require at
least Polygon's "Starter" plan. On the free "Basic" plan you may get a NOT_AUTHORIZED
error — the script detects this and tells you exactly what's missing, so the code is
ready the moment your key has access.

Educational use only. Not financial advice.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

API_BASE = "https://api.polygon.io"


# ──────────────────────────────────────────────────────────────────────────────
# HTTP (stdlib only) with rate-limit + auth handling
# ──────────────────────────────────────────────────────────────────────────────
class PolygonError(Exception):
    pass


class NotAuthorized(PolygonError):
    pass


def get_json(path_or_url, api_key, params=None, req_delay=0.0, max_retries=4):
    """GET a Polygon endpoint and return parsed JSON. Handles 429 (rate limit) with
    backoff and surfaces 401/403 as NotAuthorized with a clear message."""
    if path_or_url.startswith("http"):
        url = path_or_url
        # next_url pagination links need the key re-appended
        if "apiKey=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}apiKey={api_key}"
    else:
        p = dict(params or {})
        p["apiKey"] = api_key
        url = f"{API_BASE}{path_or_url}?{urllib.parse.urlencode(p)}"

    for attempt in range(max_retries):
        if req_delay:
            time.sleep(req_delay)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "local-orderflow/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code in (401, 403):
                raise NotAuthorized(
                    f"HTTP {e.code} from Polygon. Your API key likely lacks access to this "
                    f"endpoint.\n  Endpoint: {url.split('?')[0]}\n  Response: {body[:300]}\n"
                    f"  → Tick trades/quotes usually need at least the Polygon 'Starter' plan."
                )
            if e.code == 429:
                wait = 2 ** attempt * 15  # free tier is 5 calls/min; back off hard
                print(f"  [rate-limited] waiting {wait}s (attempt {attempt+1}/{max_retries})...",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            raise PolygonError(f"HTTP {e.code}: {body[:300]}")
        except urllib.error.URLError as e:
            raise PolygonError(f"Network error: {e.reason}")
    raise PolygonError("Exceeded max retries (rate limited).")


# ──────────────────────────────────────────────────────────────────────────────
# Reference data: which exchange IDs are off-exchange (TRF) venues
# ──────────────────────────────────────────────────────────────────────────────
def fetch_exchanges(api_key, req_delay):
    """Returns {id: {'name', 'type', 'mic'}} and the set of off-exchange (TRF) ids."""
    data = get_json("/v3/reference/exchanges", api_key,
                    params={"asset_class": "stocks"}, req_delay=req_delay)
    by_id, trf_ids = {}, set()
    for ex in data.get("results", []):
        eid = ex.get("id")
        by_id[eid] = {"name": ex.get("name", "?"),
                      "type": ex.get("type", "?"),
                      "mic": ex.get("mic", "")}
        # TRF = Trade Reporting Facility = off-exchange (dark pools + internalizers).
        if ex.get("type") == "TRF":
            trf_ids.add(eid)
    return by_id, trf_ids


# ──────────────────────────────────────────────────────────────────────────────
# Fetch trades / quotes for a day (paginated)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_all(start_path, api_key, params, req_delay, max_pages):
    """Follow next_url pagination, accumulating 'results'."""
    out = []
    data = get_json(start_path, api_key, params=params, req_delay=req_delay)
    out.extend(data.get("results", []) or [])
    pages = 1
    while data.get("next_url") and pages < max_pages:
        data = get_json(data["next_url"], api_key, req_delay=req_delay)
        out.extend(data.get("results", []) or [])
        pages += 1
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────────────────────────────────────
def analyze_trades(trades, by_id, trf_ids, block_size):
    total_vol = 0
    total_notional = 0.0
    off_vol = 0
    off_notional = 0.0
    per_venue = defaultdict(lambda: {"vol": 0, "trades": 0})
    blocks = []

    for t in trades:
        size = t.get("size", 0) or 0
        price = t.get("price", 0.0) or 0.0
        eid = t.get("exchange")
        notional = size * price
        total_vol += size
        total_notional += notional
        per_venue[eid]["vol"] += size
        per_venue[eid]["trades"] += 1
        if eid in trf_ids:
            off_vol += size
            off_notional += notional
        if size >= block_size:
            blocks.append((size, price, eid, t.get("sip_timestamp")))

    return {
        "n_trades": len(trades),
        "total_vol": total_vol,
        "total_notional": total_notional,
        "off_vol": off_vol,
        "off_notional": off_notional,
        "off_ratio": (off_vol / total_vol) if total_vol else 0.0,
        "per_venue": per_venue,
        "blocks": sorted(blocks, reverse=True),
    }


def analyze_quotes(quotes):
    """Average top-of-book imbalance from a sample of NBBO quotes."""
    bid_sz = ask_sz = 0
    spreads = []
    for q in quotes:
        bs = q.get("bid_size", 0) or 0
        a_s = q.get("ask_size", 0) or 0
        bid_sz += bs
        ask_sz += a_s
        bp, ap = q.get("bid_price"), q.get("ask_price")
        if bp and ap and ap > bp:
            spreads.append(ap - bp)
    tot = bid_sz + ask_sz
    return {
        "n_quotes": len(quotes),
        "bid_size": bid_sz,
        "ask_size": ask_sz,
        "imbalance": ((bid_sz - ask_sz) / tot) if tot else 0.0,  # +ve = bid-heavy
        "avg_spread": (sum(spreads) / len(spreads)) if spreads else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────────────────
def fmt_int(n):
    return f"{n:,}"


def bar(frac, width=30):
    fill = int(round(frac * width))
    return "█" * fill + "░" * (width - fill)


def report(ticker, date, ta, qa, by_id, trf_ids):
    print()
    print("═" * 64)
    print(f"  ORDER-FLOW / DARK-POOL REPORT — {ticker}   {date}")
    print("═" * 64)

    print("\n  OFF-EXCHANGE (dark pool + internalized) ACTIVITY")
    print(f"    Total volume        : {fmt_int(ta['total_vol'])} sh "
          f"(${ta['total_notional']/1e6:,.1f}M)")
    print(f"    Off-exchange volume : {fmt_int(ta['off_vol'])} sh "
          f"(${ta['off_notional']/1e6:,.1f}M)")
    r = ta["off_ratio"]
    print(f"    Off-exchange ratio  : {r*100:5.1f}%  [{bar(r)}]")
    print(f"    (Trades analyzed    : {fmt_int(ta['n_trades'])})")

    print("\n  VENUE BREAKDOWN (top 8 by volume)")
    ranked = sorted(ta["per_venue"].items(), key=lambda kv: kv[1]["vol"], reverse=True)
    for eid, d in ranked[:8]:
        info = by_id.get(eid, {})
        tag = "  ⟵ OFF-EXCH" if eid in trf_ids else ""
        share = d["vol"] / ta["total_vol"] if ta["total_vol"] else 0
        print(f"    {info.get('type','?'):9s} {info.get('name','id '+str(eid))[:34]:34s} "
              f"{share*100:5.1f}%{tag}")

    print("\n  BLOCK PRINTS (largest)")
    if ta["blocks"]:
        for size, price, eid, ts in ta["blocks"][:8]:
            info = by_id.get(eid, {})
            tag = "OFF-EXCH" if eid in trf_ids else info.get("type", "?")
            when = ""
            if ts:
                try:
                    when = datetime.fromtimestamp(ts / 1e9, timezone.utc).strftime("%H:%M:%S")
                except Exception:
                    when = ""
            print(f"    {fmt_int(size):>9s} sh @ ${price:<9.2f} {when} UTC  [{tag}]")
    else:
        print("    (none above the block threshold)")

    if qa:
        print("\n  TOP-OF-BOOK IMBALANCE (NBBO sample)")
        print(f"    Quotes sampled : {fmt_int(qa['n_quotes'])}")
        print(f"    Bid size total : {fmt_int(qa['bid_size'])}")
        print(f"    Ask size total : {fmt_int(qa['ask_size'])}")
        imb = qa["imbalance"]
        side = "BID-heavy (buy pressure)" if imb > 0 else "ASK-heavy (sell pressure)"
        print(f"    Imbalance      : {imb*100:+5.1f}%  {side}")
        if qa["avg_spread"] is not None:
            print(f"    Avg spread     : ${qa['avg_spread']:.4f}")

    print("\n" + "─" * 64)
    print("  NOTE: 'off-exchange' = dark pools + retail internalization; the public")
    print("  tape can't fully separate them. Top-of-book ≠ full L2 depth. Delayed")
    print("  data on lower Polygon tiers. Educational use only — not financial advice.")
    print("─" * 64 + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def default_date():
    """Most recent weekday (UTC). Avoids weekends with no trades."""
    d = datetime.now(timezone.utc).date()
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d -= timedelta(days=1)
    return d.isoformat()


def main():
    ap = argparse.ArgumentParser(description="Local order-flow / dark-pool analyzer (Polygon).")
    ap.add_argument("ticker", nargs="?", default="AAPL", help="Symbol (default AAPL)")
    ap.add_argument("--date", default=None, help="Trading day YYYY-MM-DD (default: last weekday)")
    ap.add_argument("--api-key", default=os.environ.get("POLYGON_API_KEY"),
                    help="Polygon API key (or set POLYGON_API_KEY env var)")
    ap.add_argument("--block-size", type=int, default=10000,
                    help="Block-print size threshold in shares (default 10000)")
    ap.add_argument("--max-trade-pages", type=int, default=4,
                    help="Max trade pages to pull (each up to 50k). Keep low on free tier.")
    ap.add_argument("--quotes", action="store_true",
                    help="Also sample quotes for top-of-book imbalance (extra API calls)")
    ap.add_argument("--free-tier", action="store_true",
                    help="Throttle to ~5 calls/min (sleeps between requests) for the free plan.")
    args = ap.parse_args()

    if not args.api_key:
        print("ERROR: no API key. Set POLYGON_API_KEY or pass --api-key.\n"
              "Get a free key at https://polygon.io/ (Dashboard → API Keys).", file=sys.stderr)
        sys.exit(2)

    date = args.date or default_date()
    req_delay = 13.0 if args.free_tier else 0.0  # ~4.6 calls/min, safely under the 5/min cap
    ticker = args.ticker.upper()

    try:
        print(f"Fetching exchange reference map...", file=sys.stderr)
        by_id, trf_ids = fetch_exchanges(args.api_key, req_delay)
        print(f"  {len(by_id)} venues, {len(trf_ids)} off-exchange (TRF).", file=sys.stderr)

        print(f"Fetching trades for {ticker} on {date}...", file=sys.stderr)
        trades = fetch_all(f"/v3/trades/{ticker}", args.api_key,
                           params={"timestamp": date, "limit": 50000, "order": "asc",
                                   "sort": "timestamp"},
                           req_delay=req_delay, max_pages=args.max_trade_pages)
        if not trades:
            print(f"  No trades returned for {ticker} on {date}. "
                  f"Check the date is a trading day and your plan covers tick trades.",
                  file=sys.stderr)
        ta = analyze_trades(trades, by_id, trf_ids, args.block_size)

        qa = None
        if args.quotes:
            print(f"Sampling quotes for {ticker}...", file=sys.stderr)
            quotes = fetch_all(f"/v3/quotes/{ticker}", args.api_key,
                               params={"timestamp": date, "limit": 50000, "order": "asc",
                                       "sort": "timestamp"},
                               req_delay=req_delay, max_pages=1)
            qa = analyze_quotes(quotes)

        report(ticker, date, ta, qa, by_id, trf_ids)

    except NotAuthorized as e:
        print(f"\nNOT AUTHORIZED:\n  {e}\n", file=sys.stderr)
        sys.exit(1)
    except PolygonError as e:
        print(f"\nERROR: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
