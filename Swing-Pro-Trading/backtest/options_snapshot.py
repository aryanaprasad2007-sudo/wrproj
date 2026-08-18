"""
options_snapshot.py — daily per-ticker options-chain accumulator (the free,
build-it-yourself Unusual Whales). Part of the iAPE toolkit.

Once per trading day (scheduled ~12:45 PT), snapshots each basket symbol's
option chain from Alpaca's free indicative feed and distills it to one row:

  put/call VOLUME ratio, total call & put volume, a crude gamma-flow proxy
  (daily-VOLUME-weighted gamma × spot² × 100, calls − puts), and
  near-the-money IV (sparse — only contracts the feed prices).

The indicative feed carries NO open interest (and OPRA is not signed on this
plan), so OI-based features are not collectable here.

Rows append to cache/options_daily.csv. Free per-ticker options HISTORY is not
purchasable at $0 — but it is accumulable. After ~6-8 weeks there is enough to
test these as entry gates against the forward-test trade log, same H1/H2
discipline as everything else.

DATA NOTE: rows written before 2026-07-14 used the wrong (snake_case) response
keys and contain no real option data — archived to
cache/options_daily_broken_pre20260714.csv. The usable dataset starts
2026-07-14; maturity (~6-8 weeks) is therefore ~end of August 2026.

Usage:  py options_snapshot.py          (idempotent: one row per symbol per day)
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

from data import _env

DATA = "https://data.alpaca.markets"
BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META",
          "MSTR", "ORCL", "NFLX", "AVGO", "CRWD"]  # both forward-test baskets
OUT = Path(__file__).parent / "cache" / "options_daily.csv"


def _get(path, **q):
    url = DATA + path + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY")})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def spot(symbol):
    js = _get(f"/v2/stocks/{symbol}/bars", timeframe="1Min", limit=1,
              feed="iex", sort="desc")
    b = (js.get("bars") or [{}])[-1]
    return float(b.get("c", 0.0))


def snapshot(symbol):
    px = spot(symbol)
    call_vol = put_vol = 0.0
    gex = 0.0
    ivs = []
    token = None
    pages = 0
    while pages < 6:  # cap pages; nearest expiries dominate anyway
        q = dict(feed="indicative", limit=1000)
        if token:
            q["page_token"] = token
        js = _get(f"/v1beta1/options/snapshots/{symbol}", **q)
        snaps = js.get("snapshots") or {}
        for occ, s in snaps.items():
            # response keys are camelCase (dailyBar / greeks / impliedVolatility);
            # the feed has NO openInterest field at all
            greeks = s.get("greeks") or {}
            gamma = greeks.get("gamma")
            day = s.get("dailyBar") or {}
            vol = day.get("v") or 0
            iv = s.get("impliedVolatility")
            # OCC symbol: root + yymmdd + C/P + strike*1000
            is_call = "C" in occ[-9:]
            strike = int(occ[-8:]) / 1000.0
            if is_call:
                call_vol += vol
                if gamma and px and vol:
                    gex += gamma * vol * 100 * px * px * 0.0001
            else:
                put_vol += vol
                if gamma and px and vol:
                    gex -= gamma * vol * 100 * px * px * 0.0001
            if iv and px and abs(strike - px) / px < 0.03:
                ivs.append(iv)
        token = js.get("next_page_token")
        pages += 1
        if not token:
            break
    return {
        "date": date.today().isoformat(), "symbol": symbol, "spot": round(px, 2),
        "pc_vol_ratio": round(put_vol / call_vol, 4) if call_vol else None,
        "call_vol": int(call_vol), "put_vol": int(put_vol),
        "gex_vol_proxy": round(gex, 0),
        "atm_iv": round(sum(ivs) / len(ivs), 4) if ivs else None,
    }


def main():
    OUT.parent.mkdir(exist_ok=True)
    have = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame()
    today = date.today().isoformat()
    done = set(have[have.date == today]["symbol"]) if len(have) else set()
    rows = []
    for s in BASKET:
        if s in done:
            continue
        try:
            rows.append(snapshot(s))
            print(f"  {s}: ok")
        except Exception as e:
            print(f"  {s}: FAILED ({e})")
    if rows:
        df = pd.concat([have, pd.DataFrame(rows)], ignore_index=True)
        df.to_csv(OUT, index=False)
        print(f"{len(rows)} rows appended -> {OUT} ({len(df)} total)")
    else:
        print("nothing to do (already snapped today, or all failed)")


if __name__ == "__main__":
    main()
