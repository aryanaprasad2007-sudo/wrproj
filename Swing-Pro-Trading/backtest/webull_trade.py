"""
webull_trade.py — Webull OpenAPI TRADING client (GATED — see ../WEBULL_INTEGRATION.md).

Environments (host chosen by WEBULL_ENV, default "paper"):
  paper -> us-openapi-alb.uat.webullbroker.com   (Webull's UAT environment: the
           API-side PAPER-TRADING venue — simulated fills, not real money.
           NEEDS ITS OWN CREDENTIALS: set WEBULL_UAT_APP_KEY /
           WEBULL_UAT_APP_SECRET; the prod keys return 401 here, live-verified
           2026-07-08.)
  prod  -> api.webull.com                        (REAL MONEY; every mutating
           call requires an interactive typed confirmation, never auto-fires)

ROUTES (live-verified 2026-07-08 — the SAME lesson as webull_data.py): the US
gateway serves the SDK's *v1* route family, NOT the /openapi/... v2/v3 routes
(those all 404 "Route Not Found" on BOTH hosts). Working prod routes:
  GET  /app/subscriptions/list      -> 200 (lists app-linked accounts)
  GET  /account/profile|balance|positions?account_id=...
  GET  /trade/orders/list-open|list-today, /trade/order/detail
  POST /trade/order/place|replace|cancel
v1 stock_order schema differs from the docs' v3: instrument_id (NOT symbol),
qty (NOT quantity), tif (NOT time_in_force). instrument_id comes free from
webull_data.snapshot() ("instrumentId"). The UAT host answers 401 (not 404) on
these routes = same family, different credentials.

SAFETY MODEL (house rule #3 — nothing auto-trades real money pre-audition):
  * EXECUTION_ENABLED = False at module level. place/replace/cancel default to
    DRY-RUN: the intended order is logged to cache/webull_orders.csv and NOTHING
    is sent. Callers must pass execute=True explicitly (the paper round-trip CLI
    does; no strategy module does).
  * WEBULL_ENV="prod" + execute=True additionally demands a typed confirmation
    on a real console. Non-interactive contexts (scheduled tasks) cannot
    confirm, therefore cannot send prod orders, by construction.
  * Every intended AND sent order is appended to cache/webull_orders.csv so the
    referee can score would-be fills — same discipline as the STRICT shadow.

Signing: webull_data._sign() (HMAC-SHA1, verified live 2026-07-06) — both hosts
are in the SDK's SHA1 whitelist; POST bodies fold into the signature as an
uppercase-MD5 of the compact JSON, which _sign already implements. The 2FA
trade-token flow (/openapi/auth/token/*) 404s on this gateway and is therefore
skipped automatically; ensure_token() stays for forward-compat.

Usage:
  py webull_trade.py                      # smoke: subscriptions list (paper)
  py webull_trade.py --env prod           # same, read-only, against prod
  py webull_trade.py --env prod --balance <acct>     # also --positions --open
  py webull_trade.py --roundtrip <acct>   # PAPER ONLY: place far-from-market
                                          # limit -> detail -> cancel -> verify
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from data import _env
from webull_data import WebullError, _sign

# ── the gate ────────────────────────────────────────────────────────────────
EXECUTION_ENABLED = False          # module default: mutating calls DRY-RUN
WEBULL_ENV = (_env("WEBULL_ENV") or "paper").lower()   # "paper" | "prod"

HOSTS = {
    "paper": "us-openapi-alb.uat.webullbroker.com",    # UAT = simulated fills
    "prod": "api.webull.com",
}

_CACHE = Path(__file__).resolve().parent / "cache"
ORDER_LOG = _CACHE / "webull_orders.csv"
_LOG_FIELDS = ["ts", "env", "dry_run", "action", "account_id", "client_order_id",
               "symbol", "side", "qty", "order_type", "limit_price", "http_status",
               "response"]
_tokens: dict[str, str] = {}       # per-env trade-token cache (unused on v1 gw)


def _host(env=None) -> str:
    env = (env or WEBULL_ENV).lower()
    if env not in HOSTS:
        raise WebullError(f"WEBULL_ENV must be paper|prod, got {env!r}")
    return HOSTS[env]


def _keys(env) -> tuple[str, str]:
    """paper prefers UAT-specific keys (portal sandbox creds); prod uses the
    verified production pair."""
    if env == "paper":
        ak, sk = _env("WEBULL_UAT_APP_KEY"), _env("WEBULL_UAT_APP_SECRET")
        if ak and sk:
            return ak, sk
    ak, sk = _env("WEBULL_APP_KEY"), _env("WEBULL_APP_SECRET")
    if not ak or not sk:
        raise WebullError("WEBULL_APP_KEY / WEBULL_APP_SECRET not set (User env).")
    return ak, sk


# ── transport (signed GET/POST, optional x-access-token) ────────────────────
def _request(method: str, path: str, env=None, query=None, body=None,
             extra_headers=None, with_token=True):
    env = (env or WEBULL_ENV).lower()
    ak, sk = _keys(env)
    host = _host(env)
    q = {k: str(v) for k, v in (query or {}).items() if v is not None}
    headers = _sign(ak, sk, host, path, q, body_params=body)
    if with_token and env in _tokens:
        headers["x-access-token"] = _tokens[env]       # not signed (SDK parity)
    for k, v in (extra_headers or {}).items():
        headers[k] = v
    url = f"https://{host}{path}" + (("?" + urllib.parse.urlencode(q)) if q else "")
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:400]}


def _ok(status, payload, what):
    if status != 200:
        raise WebullError(f"HTTP {status} on {what}: {json.dumps(payload)[:400]}")
    return payload


# ── trade token (2FA) — newer-gateway feature; 404 => not needed here ───────
def ensure_token(env=None, wait_seconds=90) -> str | None:
    env = (env or WEBULL_ENV).lower()
    if env in _tokens:
        return _tokens[env]
    status, cfg = _request("GET", "/openapi/config", env=env, with_token=False)
    if status != 200 or not cfg.get("token_check_enabled", False):
        return None                                     # v1 gateway: no token
    tf = _CACHE / f"webull_token_{env}.json"
    local = None
    if tf.exists():
        try:
            local = json.loads(tf.read_text()).get("token")
        except (json.JSONDecodeError, OSError):
            local = None
    status, tok = _request("POST", "/openapi/auth/token/create", env=env,
                           body=({"token": local} if local else {}),
                           with_token=False)
    _ok(status, tok, "auth/token/create")
    deadline = time.time() + wait_seconds
    while tok.get("status") != "NORMAL":
        if time.time() > deadline:
            raise WebullError(
                "trade token still %s after %ss — approve the 2FA prompt in the "
                "Webull app, then rerun." % (tok.get("status"), wait_seconds))
        print("  token status=%s — approve the 2FA prompt in the Webull app "
              "(polling)..." % tok.get("status"))
        time.sleep(5)
        status, tok = _request("POST", "/openapi/auth/token/check", env=env,
                               body={"token": tok["token"]}, with_token=False)
        _ok(status, tok, "auth/token/check")
    _CACHE.mkdir(exist_ok=True)
    tf.write_text(json.dumps(tok))
    _tokens[env] = tok["token"]
    return _tokens[env]


# ── read-only account/order queries ─────────────────────────────────────────
def accounts(env=None):
    """App-linked accounts (subscription relationships). This is how you find
    account_id."""
    ensure_token(env)
    return _ok(*_request("GET", "/app/subscriptions/list", env=env),
               "app/subscriptions/list")


def profile(account_id, env=None):
    ensure_token(env)
    return _ok(*_request("GET", "/account/profile", env=env,
                         query={"account_id": account_id}), "account/profile")


def balance(account_id, currency="USD", env=None):
    ensure_token(env)
    return _ok(*_request("GET", "/account/balance", env=env,
                         query={"account_id": account_id,
                                "total_asset_currency": currency}),
               "account/balance")


def positions(account_id, env=None, page_size=100):
    ensure_token(env)
    return _ok(*_request("GET", "/account/positions", env=env,
                         query={"account_id": account_id,
                                "page_size": page_size}), "account/positions")


def open_orders(account_id, env=None, page_size=20):
    ensure_token(env)
    return _ok(*_request("GET", "/trade/orders/list-open", env=env,
                         query={"account_id": account_id,
                                "page_size": page_size}),
               "trade/orders/list-open")


def today_orders(account_id, env=None, page_size=20):
    ensure_token(env)
    return _ok(*_request("GET", "/trade/orders/list-today", env=env,
                         query={"account_id": account_id,
                                "page_size": page_size}),
               "trade/orders/list-today")


def order_detail(account_id, client_order_id, env=None):
    ensure_token(env)
    return _ok(*_request("GET", "/trade/order/detail", env=env,
                         query={"account_id": account_id,
                                "client_order_id": client_order_id}),
               "trade/order/detail")


def instrument_id_for(symbol) -> str:
    """Resolve a US-equity symbol to Webull's instrument_id via the (already
    verified) market-data snapshot."""
    from webull_data import snapshot
    rows = snapshot([symbol])
    if not rows or not rows[0].get("instrumentId"):
        raise WebullError(f"could not resolve instrument_id for {symbol!r}")
    return rows[0]["instrumentId"]


# ── order mutation (gated) ──────────────────────────────────────────────────
def _log_order(**row):
    _CACHE.mkdir(exist_ok=True)
    new = not ORDER_LOG.exists()
    with open(ORDER_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_LOG_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        row.setdefault("ts", datetime.now(timezone.utc).isoformat())
        w.writerow(row)


def _require_confirmation(env, action, payload, web_confirmed=False):
    """Real-money orders require an explicit HUMAN confirmation. Two accepted
    forms, both human-initiated:
      * CLI: type SEND at an interactive console.
      * Dashboard: the user clicks + confirms in their local browser, which sets
        web_confirmed=True on this call.
    Strategy/scheduled code passes neither and has no TTY, so it can never reach
    a live prod order — the invariant that matters."""
    if env != "prod":
        return
    if web_confirmed:
        _log_order(env=env, dry_run=False, action=f"{action}_CONFIRM",
                   response="confirmed via dashboard (user click)")
        return
    if not sys.stdin.isatty():
        raise WebullError("prod %s blocked: no interactive console to confirm "
                          "(scheduled/automated contexts can never send real "
                          "orders)." % action)
    print(f"\n*** REAL-MONEY {action} on Webull PROD ***\n{json.dumps(payload, indent=2)}")
    if input("Type SEND to transmit, anything else aborts: ").strip() != "SEND":
        raise WebullError(f"prod {action} aborted by user.")


def place_order(account_id, symbol, side, qty, order_type="LIMIT",
                limit_price=None, stop_price=None, tif="DAY",
                extended_hours=False, instrument_id=None, client_order_id=None,
                env=None, execute=None, web_confirmed=False):
    """Single US-equity order (v1 stock_order schema). DRY-RUN unless
    execute=True (or the module gate is flipped). Returns the server response,
    or the logged intent when dry."""
    env = (env or WEBULL_ENV).lower()
    execute = EXECUTION_ENABLED if execute is None else execute
    coid = client_order_id or uuid.uuid4().hex
    so = {"client_order_id": coid,
          "instrument_id": instrument_id or instrument_id_for(symbol),
          "side": side, "tif": tif, "order_type": order_type, "qty": str(qty),
          "extended_hours_trading": bool(extended_hours)}
    if limit_price is not None:
        so["limit_price"] = str(limit_price)
    if stop_price is not None:
        so["stop_price"] = str(stop_price)
    body = {"account_id": account_id, "stock_order": so}

    if not execute:
        _log_order(env=env, dry_run=True, action="PLACE", account_id=account_id,
                   client_order_id=coid, symbol=symbol, side=side, qty=qty,
                   order_type=order_type, limit_price=limit_price,
                   http_status="", response="DRY-RUN (not sent)")
        return {"dry_run": True, "client_order_id": coid, "would_send": body}

    _require_confirmation(env, "PLACE", body, web_confirmed=web_confirmed)
    ensure_token(env)
    status, resp = _request("POST", "/trade/order/place", env=env, body=body,
                            extra_headers={"category": "US_STOCK"})
    _log_order(env=env, dry_run=False, action="PLACE", account_id=account_id,
               client_order_id=coid, symbol=symbol, side=side, qty=qty,
               order_type=order_type, limit_price=limit_price,
               http_status=status, response=json.dumps(resp)[:500])
    _ok(status, resp, "trade/order/place")
    if isinstance(resp, dict):
        resp.setdefault("client_order_id", coid)
    return resp


def replace_order(account_id, client_order_id, qty=None, limit_price=None,
                  env=None, execute=None):
    env = (env or WEBULL_ENV).lower()
    execute = EXECUTION_ENABLED if execute is None else execute
    so = {"client_order_id": client_order_id}
    if qty is not None:
        so["qty"] = str(qty)
    if limit_price is not None:
        so["limit_price"] = str(limit_price)
    body = {"account_id": account_id, "stock_order": so}
    if not execute:
        _log_order(env=env, dry_run=True, action="REPLACE", account_id=account_id,
                   client_order_id=client_order_id, qty=qty,
                   limit_price=limit_price, http_status="",
                   response="DRY-RUN (not sent)")
        return {"dry_run": True, "would_send": body}
    _require_confirmation(env, "REPLACE", body)
    ensure_token(env)
    status, resp = _request("POST", "/trade/order/replace", env=env, body=body,
                            extra_headers={"category": "US_STOCK"})
    _log_order(env=env, dry_run=False, action="REPLACE", account_id=account_id,
               client_order_id=client_order_id, qty=qty, limit_price=limit_price,
               http_status=status, response=json.dumps(resp)[:500])
    return _ok(status, resp, "trade/order/replace")


def cancel_order(account_id, client_order_id, env=None, execute=None):
    env = (env or WEBULL_ENV).lower()
    execute = EXECUTION_ENABLED if execute is None else execute
    body = {"account_id": account_id, "client_order_id": client_order_id}
    if not execute:
        _log_order(env=env, dry_run=True, action="CANCEL", account_id=account_id,
                   client_order_id=client_order_id, http_status="",
                   response="DRY-RUN (not sent)")
        return {"dry_run": True, "would_send": body}
    _require_confirmation(env, "CANCEL", body)
    ensure_token(env)
    status, resp = _request("POST", "/trade/order/cancel", env=env, body=body)
    _log_order(env=env, dry_run=False, action="CANCEL", account_id=account_id,
               client_order_id=client_order_id, http_status=status,
               response=json.dumps(resp)[:500])
    return _ok(status, resp, "trade/order/cancel")


# ── CLI ─────────────────────────────────────────────────────────────────────
def _smoke(env):
    print(f"env={env} host={_host(env)}")
    status, acc = _request("GET", "/app/subscriptions/list", env=env)
    print(f"/app/subscriptions/list -> HTTP {status}: {json.dumps(acc)[:400]}")
    if status == 401 and env == "paper":
        print("paper env rejected the credentials: set WEBULL_UAT_APP_KEY / "
              "WEBULL_UAT_APP_SECRET (sandbox creds from the developer portal).")
    return status == 200


def _roundtrip(account_id, symbol, env):
    """Paper-only proof: place a limit buy far below market (cannot fill),
    query it, cancel it, verify the cancel. This is promotion-path step 2."""
    if env != "paper":
        raise WebullError("--roundtrip is paper-only by design.")
    from webull_data import snapshot
    last = float(snapshot([symbol])[0]["price"])
    limit = round(last * 0.80, 2)                      # 20% below: cannot fill
    print(f"{symbol} last={last} -> placing 1-share LIMIT BUY @ {limit} (paper)")
    resp = place_order(account_id, symbol, "BUY", 1, limit_price=limit,
                       env=env, execute=True)
    coid = resp.get("client_order_id")
    print("placed:", json.dumps(resp)[:300])
    time.sleep(3)
    print("detail:", json.dumps(order_detail(account_id, coid, env=env))[:300])
    print("cancel:", json.dumps(cancel_order(account_id, coid, env=env,
                                             execute=True))[:300])
    time.sleep(3)
    print("detail after cancel:",
          json.dumps(order_detail(account_id, coid, env=env))[:300])


def _manual_order(symbol, side, qty, limit, env):
    """Human-initiated single order. For env=prod this is REAL MONEY; place_order
    forces an interactive typed 'SEND' confirmation (and refuses entirely if
    there's no console, so nothing automated can reach here). The account is
    resolved automatically. This is the *manual discretionary* path — separate
    from any strategy code, which never runs with execution enabled."""
    acct = _env("WEBULL_PAPER_ACCOUNT_ID") if env == "paper" else None
    if acct is None:
        acct = accounts(env=env)[0]["account_id"]
    from webull_data import snapshot
    last = float(snapshot([symbol])[0]["price"])
    kind = "LIMIT @ " + str(limit) if limit else "MARKET"
    print(f"{symbol} last={last} · you are about to {side} {qty} share(s) "
          f"as a {kind} order on {env.upper()} (account {acct}).")
    resp = place_order(acct, symbol, side.upper(), qty,
                       order_type="LIMIT" if limit else "MARKET",
                       limit_price=limit, env=env, execute=True)
    print("result:", json.dumps(resp, indent=2)[:600])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Webull trading client (gated)")
    p.add_argument("--env", default=WEBULL_ENV, choices=["paper", "prod"])
    p.add_argument("--profile", metavar="ACCT")
    p.add_argument("--balance", metavar="ACCT")
    p.add_argument("--positions", metavar="ACCT")
    p.add_argument("--open", metavar="ACCT")
    p.add_argument("--roundtrip", metavar="ACCT")
    p.add_argument("--symbol", default="AAPL")
    # manual discretionary order (prod = real money, forces typed confirmation):
    p.add_argument("--buy", metavar="SYMBOL")
    p.add_argument("--sell", metavar="SYMBOL")
    p.add_argument("--qty", type=int)
    p.add_argument("--limit", type=float, help="limit price; omit for MARKET")
    a = p.parse_args()
    if a.profile:
        print(json.dumps(profile(a.profile, env=a.env), indent=2))
    elif a.balance:
        print(json.dumps(balance(a.balance, env=a.env), indent=2))
    elif a.positions:
        print(json.dumps(positions(a.positions, env=a.env), indent=2))
    elif a.open:
        print(json.dumps(open_orders(a.open, env=a.env), indent=2))
    elif a.roundtrip:
        _roundtrip(a.roundtrip, a.symbol, a.env)
    elif a.buy or a.sell:
        if not a.qty or a.qty < 1:
            sys.exit("--qty (>=1) is required with --buy/--sell")
        _manual_order(a.buy or a.sell, "BUY" if a.buy else "SELL",
                      a.qty, a.limit, a.env)
    else:
        sys.exit(0 if _smoke(a.env) else 1)
