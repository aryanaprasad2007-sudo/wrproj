"""
webull_fills.py — broker-truth fills for orders placed on the Webull PAPER venue.

forward_trader logs the Webull client_order_id in forward_log.csv's `order`
column (32 hex chars, no dashes — Alpaca ids are dashed UUIDs, so the two are
distinguishable). This module maps those ids to actual fill prices via
wt.order_detail, so the Friday referee (forward_review) and the cockpit can
score Webull-era trades on real fills instead of silently falling back to
reference prices.

Details for TERMINAL orders (filled/cancelled/…) are cached forever in
cache/webull_fills.json — they cannot change, and the UAT gateway 504s enough
that re-fetching them every review would be both slow and flaky. Pending
orders are re-fetched each call.

CAVEAT (measured 2026-07-11): the shared UAT simulator can print absurd fills —
an after-hours UNH market buy "filled" at $10.00 on a ~$425 stock. This module
reports what the venue said; deciding whether to TRUST it is the caller's job
(forward_review.with_fills() nulls fills >15% from the logged reference).

Bot orders are paper-only by design, so everything here queries env="paper".
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "cache" / "webull_fills.json"

# order_status values that can never change again -> safe to cache forever
TERMINAL = {"FILLED", "CANCELLED", "FAILED", "EXPIRED", "REJECTED"}

_WB_ID = re.compile(r"^[0-9a-f]{32}$")


def looks_webull(oid) -> bool:
    """True if this order id has the Webull client_order_id shape
    (uuid4().hex: 32 lowercase hex chars, no dashes)."""
    return bool(_WB_ID.match(str(oid or "").strip().lower()))


def _load() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(d: dict):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(d, indent=1))


def _fetch(coid: str) -> dict:
    """One order_detail call (with a single 504 retry — the UAT gateway drops
    requests transiently). Returns {status, price, qty, time}."""
    import broker
    import webull_trade as wt
    from webull_data import WebullError
    last = None
    for attempt in (1, 2):
        try:
            d = wt.order_detail(broker._wb_acct(), coid, env="paper")
            items = d.get("items") or [{}]
            it = items[0]
            px = it.get("filled_price")
            try:
                px = float(px) if px else None
            except (TypeError, ValueError):
                px = None
            return {"status": it.get("order_status", "?"),
                    "price": px if (px or 0) > 0 else None,
                    "qty": float(it.get("filled_qty") or 0),
                    "time": it.get("last_filled_time", "")}
        except WebullError as e:
            last = e
            if "504" in str(e) and attempt == 1:
                time.sleep(3)
                continue
            raise
    raise last


def fill_map(order_ids) -> dict:
    """{client_order_id: fill_price} for FILLED Webull orders among order_ids.
    Non-Webull-shaped ids are ignored; venue errors degrade to 'no fill for
    that id' (callers fall back to reference prices) rather than raising."""
    cache = _load()
    dirty = False
    out = {}
    for oid in sorted({str(o).strip().lower() for o in order_ids
                       if looks_webull(o)}):
        rec = cache.get(oid)
        if not rec or rec.get("status") not in TERMINAL:
            try:
                rec = _fetch(oid)
                cache[oid] = rec
                dirty = True
            except Exception as e:
                rec = rec or {"status": f"ERR {str(e)[:60]}", "price": None}
        if rec.get("price"):
            out[oid] = float(rec["price"])
    if dirty:
        _save(cache)
    return out


if __name__ == "__main__":
    # smoke test against the two known bridge-era orders (one FILLED, one
    # CANCELLED) — proves the fetch path without placing anything
    known = ["48bb7a26837d4533a957117bbf106035",   # UNH x2 MARKET -> FILLED
             "6a4caf3b98914c5d8fb78df377b8069d",   # UNH x2 LIMIT  -> CANCELLED
             "not-an-id", ""]
    print("fill_map:", fill_map(known))
    print("cache:", json.dumps(_load(), indent=1))
