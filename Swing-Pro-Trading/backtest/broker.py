"""
broker.py — execution-venue adapter for forward_trader.

One env var picks the venue (signals/market data stay on Alpaca IEX either way
— the venue only changes WHERE orders go and WHICH account is read):

  SWINGPRO_BROKER=alpaca   (default) Alpaca PAPER — the original forward test.
                           Byte-identical behavior to the pre-adapter code.
  SWINGPRO_BROKER=webull   Webull PAPER (UAT venue via webull_trade). PAPER IS
                           FORCED — this adapter has no prod path at all; real
                           money still requires the WEBULL_INTEGRATION.md
                           promotion gate, which is human + audition-keyed.

Webull-mode facts (measured 2026-07-08, see WEBULL_INTEGRATION.md §2a):
  * The shared UAT account caps orders at $1,000 notional. Sizing equity is
    therefore simulated locally: WEBULL_PAPER_EQUITY (default 10,000) makes the
    strategies' 10%-of-equity sizing land at ~$1k/position — inside the cap.
  * The account is SHARED with other developers, so account-truth is weak:
    reconcile adoption is disabled (SUPPORTS_ADOPT=False) — a stranger's AAPL
    must never be adopted into our books. Drop/qty sync still applies only to
    symbols already in our state. A dedicated test account from Webull support
    removes both caveats.
  * The UAT gateway 504s intermittently; submit() retries once.

Interface (normalized so forward_trader has no venue-specific branches):
  market_open() -> bool
  account()     -> (equity: float, buying_power: float)
  positions()   -> [{"symbol", "qty", "side", "avg_entry_price"}, ...]
  position(sym) -> {"avg_entry_price": float} or None
  submit(symbol, qty, side) -> order id string
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from data import _env

BROKER = (_env("SWINGPRO_BROKER") or "alpaca").lower()
if BROKER not in ("alpaca", "webull"):
    raise SystemExit(f"SWINGPRO_BROKER must be alpaca|webull, got {BROKER!r}")

VENUE = "Alpaca PAPER" if BROKER == "alpaca" else "Webull PAPER (UAT)"
SUPPORTS_ADOPT = BROKER == "alpaca"     # shared UAT account => never adopt

_PAPER = "https://paper-api.alpaca.markets"     # hardcoded: paper ONLY


# ── Alpaca implementation (identical requests to the original inline code) ──
def _alp_headers():
    return {"APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
            "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY"),
            "Content-Type": "application/json"}


def _alp_get(path, **q):
    url = _PAPER + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers=_alp_headers())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _alp_post(path, payload):
    req = urllib.request.Request(_PAPER + path, data=json.dumps(payload).encode(),
                                 headers=_alp_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


# ── Webull implementation (paper env forced; webull_trade does the signing) ──
_wb_account_id = None


def _wb_acct():
    global _wb_account_id
    if _wb_account_id is None:
        _wb_account_id = _env("WEBULL_PAPER_ACCOUNT_ID")
        if not _wb_account_id:
            import webull_trade as wt
            subs = wt.accounts(env="paper")
            _wb_account_id = subs[0]["account_id"]
    return _wb_account_id


# ── the normalized interface ────────────────────────────────────────────────
def market_open() -> bool:
    """Alpaca's clock is holiday-aware — use it whenever keys exist (webull
    mode included; it's a data question, not a venue question). Fall back to a
    plain RTH check only if Alpaca is unreachable."""
    try:
        return bool(_alp_get("/v2/clock").get("is_open"))
    except Exception:
        import pandas as pd
        from data import NY
        now = pd.Timestamp.now(tz=NY)
        return (now.dayofweek < 5 and
                now.replace(hour=9, minute=30, second=0) <= now
                <= now.replace(hour=16, minute=0, second=0))


def account() -> tuple[float, float]:
    if BROKER == "alpaca":
        a = _alp_get("/v2/account")
        return float(a["equity"]), float(a.get("buying_power", 0))
    # Webull mode: simulated sizing base. Prefer the live dashboard setting,
    # fall back to the env var, then a default (see module docstring).
    try:
        import botconfig
        eq = float(botconfig.load()["webull_sizing_equity"])
    except Exception:
        eq = float(_env("WEBULL_PAPER_EQUITY") or 10000)
    return eq, eq


def positions() -> list[dict]:
    if BROKER == "alpaca":
        return [{"symbol": p["symbol"], "qty": float(p["qty"]),
                 "side": p.get("side"),
                 "avg_entry_price": float(p["avg_entry_price"])}
                for p in _alp_get("/v2/positions")]
    import webull_trade as wt
    out = []
    for h in wt.positions(_wb_acct(), env="paper").get("holdings", []):
        try:
            out.append({"symbol": h["symbol"], "qty": float(h["qty"]),
                        "side": "long",
                        "avg_entry_price": float(h.get("unit_cost") or 0)})
        except (KeyError, ValueError, TypeError):
            continue
    return out


def position(symbol) -> dict | None:
    if BROKER == "alpaca":
        p = _alp_get(f"/v2/positions/{symbol}")
        return {"avg_entry_price": float(p["avg_entry_price"])}
    for p in positions():
        if p["symbol"] == symbol:
            return p
    return None


def submit(symbol, qty, side) -> str:
    """Market DAY order; returns the venue's order id. side: buy|sell."""
    if BROKER == "alpaca":
        o = _alp_post("/v2/orders", {"symbol": symbol, "qty": str(int(qty)),
                                     "side": side, "type": "market",
                                     "time_in_force": "day"})
        return o.get("id", "?")
    import webull_trade as wt
    from webull_data import WebullError
    last_err = None
    for attempt in (1, 2):                 # UAT gateway 504s transiently
        try:
            r = wt.place_order(_wb_acct(), symbol, side.upper(), int(qty),
                               order_type="MARKET", env="paper", execute=True)
            return r.get("client_order_id", "?")
        except WebullError as e:
            last_err = e
            if "504" not in str(e) or attempt == 2:
                raise
            time.sleep(3)
    raise last_err
