"""
webull_data.py — Webull OpenAPI market-data client (READ-ONLY).

Why hand-rolled instead of the official SDK: the installed `webull-python-sdk-*`
vendors an ancient `requests`/`six` that is unimportable on Python 3.12, and its
bundled endpoint paths are stale (it ships `/market-data/quotes`; the live US
route is `/market-data/snapshot`). This module reproduces the SDK's EXACT signing
(HMAC-SHA1 over a sorted, URL-encoded param string, key = app_secret + "&") with
only the standard library — verified end-to-end against a live AAPL snapshot on
2026-07-06 (HTTP 200, real quote). No third-party deps, fits the urllib idiom of
data.py.

Auth: WEBULL_APP_KEY / WEBULL_APP_SECRET read via data._env (Windows User
registry, same as the Alpaca keys). Secrets never passed as arguments or logged.

Scope: read-only market data only. Trading/orders live in a separate, gated
module (see ../WEBULL_INTEGRATION.md); nothing here can place an order.

Usage:
  py webull_data.py                      # smoke test: snapshot a few symbols
  from webull_data import snapshot
  snapshot(["AAPL","NVDA"])              # -> list of dicts
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

from data import _env

HOST = "api.webull.com"          # US region; the only OpenAPI gateway that resolves
API_VERSION = "v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nonce() -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, socket.gethostname() + str(uuid.uuid1())))


def _sign(app_key, app_secret, host, uri, queries, body_params=None) -> dict:
    """Reproduces webullsdkcore default_signature_composer.calc_signature exactly.
    Returns the request headers (x-app-key/x-timestamp/x-signature-* + x-signature).
    'Host' participates in the signature but is sent by urllib, not set here."""
    sign_params = {
        "x-app-key": app_key,
        "x-timestamp": _now_iso(),
        "x-signature-version": "1.0",
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-nonce": _nonce(),
        "host": host,                                  # NATIVE_HOST "Host".lower()
    }
    headers = {k: v for k, v in sign_params.items() if k != "host"}
    for k, v in (queries or {}).items():               # queries fold into the sig
        cur = sign_params.get(k)
        sign_params[k] = (str(cur) + "&" + str(v)) if cur is not None else str(v)
    body_string = None
    if body_params is not None:
        raw = json.dumps(body_params, ensure_ascii=False, separators=(",", ":"))
        body_string = hashlib.md5(raw.encode()).hexdigest().upper()
    sts = uri + "&" + "&".join(f"{k}={v}" for k, v in sorted(sign_params.items()))
    if body_string:
        sts += "&" + body_string
    encoded = urllib.parse.quote(sts, safe="")
    headers["x-signature"] = base64.b64encode(
        hmac.new((app_secret + "&").encode(), encoded.encode(), hashlib.sha1).digest()
    ).decode().strip()
    headers["x-version"] = API_VERSION
    return headers


class WebullError(RuntimeError):
    pass


def get(path: str, **params):
    """Signed GET against the Webull OpenAPI. Returns parsed JSON.
    `path` is the route (e.g. '/market-data/snapshot'); `params` become the
    query string AND are folded into the signature (order-independent)."""
    ak, sk = _env("WEBULL_APP_KEY"), _env("WEBULL_APP_SECRET")
    if not ak or not sk:
        raise WebullError("WEBULL_APP_KEY / WEBULL_APP_SECRET not set (User env).")
    q = {k: v for k, v in params.items() if v is not None}
    headers = _sign(ak, sk, HOST, path, q)
    url = f"https://{HOST}{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise WebullError(f"HTTP {e.code} on {path}: {e.read().decode()[:300]}") from None


def snapshot(symbols, category: str = "US_STOCK",
             extend_hour: bool = False, overnight: bool = False):
    """Real-time snapshot for one or more symbols. Verified live 2026-07-06.
    category: US_STOCK | US_ETF | US_OPTION | CRYPTO | ... (webull categories)."""
    if isinstance(symbols, (list, tuple)):
        symbols = ",".join(symbols)
    return get("/market-data/snapshot", symbols=symbols, category=category,
               extend_hour_required=str(extend_hour).lower(),
               overnight_required=str(overnight).lower())


def bars(symbol, category: str = "US_STOCK", timespan: str = "M1", count: int = 200):
    """Recent OHLCV bars (verified live 2026-07-06). Note: `symbol` is SINGULAR
    here (snapshot() takes plural `symbols`). timespan codes (server-enforced):
    M1, M5, M15, M30, M60, M120, M240, and daily/weekly variants."""
    return get("/market-data/bars", symbol=symbol, category=category,
               timespan=timespan, count=str(count))


# NOTE: Level-2 order-book DEPTH is NOT available over REST here — it is an
# Advanced-Market-Data, MQTT-streaming feature (entitlement-gated). All
# /market-data/{depth,order-book,book,tick} REST routes 404. Depth therefore
# needs a streaming client, not this poller; see ../WEBULL_INTEGRATION.md.


if __name__ == "__main__":
    rows = snapshot(["AAPL", "NVDA", "TSLA"])
    print(f"Webull market-data auth OK — {len(rows)} snapshot(s) from {HOST}:")
    for r in rows:
        print(f"  {r.get('symbol'):<6} {r.get('price'):>10}  "
              f"chg {r.get('change_ratio')}  vol {r.get('volume')}")
    b = bars("AAPL", timespan="M5", count=3)
    print(f"bars() OK — {len(b)} M5 bars, latest close {b[0].get('close')}")
