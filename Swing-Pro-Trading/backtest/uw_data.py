"""
uw_data.py — Unusual Whales API client for the iAPE project.

Activates when UW_API_TOKEN is set in the environment (Authorization: Bearer).
Get a token: unusualwhales.com/pricing?product=api — API access is a separate
paid product from the regular UW subscription.

What we pull, and why it matters to the formula:
  • Dark-pool prints per ticker  -> off-exchange %, block sizes: institutional
    participation the OHLCV proxy in iAPE_Backflow.pine can only guess at.
  • Net premium ticks            -> intraday net call/put premium: an options-flow
    CVD, orthogonal to every lagging indicator in the current entry gate.
  • Market tide                  -> market-wide options flow: a flow-based upgrade
    (or complement) to the SPY-vs-EMA50 market filter.
  • Greek exposure (GEX)         -> dealer-gamma regime: positive = mean-revert
    (pullback entries favoured), negative = trend-amplifying (momentum favoured).

First run once you have a token:   py uw_data.py --probe
It hits every endpoint with a cheap request and prints HTTP status per path, so
we correct any path drift against their docs before building on top.

Educational use only. Not financial advice.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://api.unusualwhales.com"
CACHE = Path(__file__).parent / "cache" / "uw"

# Paths per api.unusualwhales.com/docs. If --probe flags one, fix it here.
PATHS = {
    "darkpool_recent":  "/api/darkpool/recent",
    "darkpool_ticker":  "/api/darkpool/{ticker}",                # ?date=YYYY-MM-DD
    "flow_alerts":      "/api/option-trades/flow-alerts",
    "net_prem_ticks":   "/api/stock/{ticker}/net-prem-ticks",    # ?date=
    "market_tide":      "/api/market/market-tide",               # ?date=
    "greek_exposure":   "/api/stock/{ticker}/greek-exposure",    # ?date=
    "spot_gex":         "/api/stock/{ticker}/spot-exposures",
    "ohlc":             "/api/stock/{ticker}/ohlc/{candle}",
}


class UWError(RuntimeError):
    pass


def _token() -> str:
    tok = os.environ.get("UW_API_TOKEN")
    if not tok:
        raise UWError("UW_API_TOKEN not set. Get one at "
                      "unusualwhales.com/pricing?product=api, then:  "
                      '[Environment]::SetEnvironmentVariable("UW_API_TOKEN","<token>","User")')
    return tok


def get(path_key: str, ticker: str = None, candle: str = None,
        cache_key: str = None, **params) -> dict:
    """GET one endpoint, JSON out, disk-cached (historical data never changes)."""
    path = PATHS[path_key]
    if ticker:
        path = path.replace("{ticker}", ticker.upper())
    if candle:
        path = path.replace("{candle}", candle)
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})

    if cache_key:
        CACHE.mkdir(parents=True, exist_ok=True)
        f = CACHE / f"{cache_key}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json, text/plain",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise UWError(f"{e.code} on {url} — if 404, fix PATHS['{path_key}'] "
                      f"against api.unusualwhales.com/docs") from e

    if cache_key:
        f.write_text(json.dumps(payload), encoding="utf-8")
    return payload


# ── convenience fetchers (shape-agnostic: return the raw 'data' list) ─────────
def darkpool_trades(ticker: str, day: str) -> list:
    return get("darkpool_ticker", ticker=ticker, date=day, limit=500,
               cache_key=f"dp_{ticker}_{day}").get("data", [])


def net_prem_ticks(ticker: str, day: str) -> list:
    return get("net_prem_ticks", ticker=ticker, date=day,
               cache_key=f"npt_{ticker}_{day}").get("data", [])


def market_tide(day: str) -> list:
    return get("market_tide", date=day, cache_key=f"tide_{day}").get("data", [])


def greek_exposure(ticker: str, day: str) -> list:
    return get("greek_exposure", ticker=ticker, date=day,
               cache_key=f"gex_{ticker}_{day}").get("data", [])


# ── probe ─────────────────────────────────────────────────────────────────────
def probe():
    day = date.today().isoformat()
    checks = [
        ("darkpool_recent", dict(limit=1)),
        ("darkpool_ticker", dict(ticker="AAPL", limit=1)),
        ("flow_alerts", dict(limit=1)),
        ("net_prem_ticks", dict(ticker="AAPL", date=day)),
        ("market_tide", dict(date=day)),
        ("greek_exposure", dict(ticker="AAPL", date=day)),
        ("spot_gex", dict(ticker="AAPL")),
        ("ohlc", dict(ticker="AAPL", candle="5m", limit=1)),
    ]
    print(f"Probing {len(checks)} Unusual Whales endpoints...\n")
    ok = 0
    for key, kw in checks:
        try:
            payload = get(key, **kw)
            n = len(payload.get("data", payload) or [])
            print(f"  OK   {key:<17} {PATHS[key]}   ({n} rows)")
            ok += 1
        except UWError as e:
            print(f"  FAIL {key:<17} {e}")
        time.sleep(0.5)  # be polite to their rate limiter
    print(f"\n{ok}/{len(checks)} endpoints live. Fix any FAIL paths in PATHS, then "
          f"we wire features into the backtest harness.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="check every endpoint")
    args = ap.parse_args()
    if args.probe:
        probe()
    else:
        print(__doc__)
