"""
webull_bridge.py — one-way mirror: forward_trader's REAL paper orders -> Webull
PAPER orders. This is the "connect the bot to Webull" seam, built PAPER-ONLY.

What it does: tails forward_log.csv (the fixed-schema event log every Alpaca
paper order already writes), and for each order-bearing event places the same
trade on Webull's UAT/paper environment via webull_trade. State in
cache/webull_bridge_state.json keys off the Alpaca order id, so runs are
idempotent — rerun as often as you like, each order mirrors at most once.

SAFETY:
  * PAPER-ONLY BY CONSTRUCTION: refuses to import-time-configure any env but
    "paper". There is deliberately NO flag to point this at prod — promoting a
    strategy to real money is a human decision that happens in
    WEBULL_INTEGRATION.md's promotion path, not by editing a bridge flag.
  * The live Alpaca forward test is UNTOUCHED — this only READS forward_log.csv.
  * No UAT credentials yet? Runs in DRY-RUN: intents land in
    cache/webull_orders.csv (dry_run=True) and state marks them "DRY" so they
    re-mirror for real once WEBULL_UAT_APP_KEY/SECRET are set.

Fidelity note: mirrors are MARKET DAY orders placed at mirror-time, not at the
original fill time — fills will differ (that's fine; the referee for strategy
performance remains the Alpaca track + forward_review; this bridge proves the
Webull execution plumbing under real signal flow, promotion-path step 2).

Usage:
  py webull_bridge.py --once      # mirror any new orders, then exit
  py webull_bridge.py --status    # show cursor + mirrored orders
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import webull_trade as wt
from webull_data import WebullError

HERE = Path(__file__).resolve().parent
FORWARD_LOG = HERE / "forward_log.csv"
STATE_FILE = HERE / "cache" / "webull_bridge_state.json"

ENV = "paper"                     # hard-wired; no prod mode exists here
if wt._host(ENV) == wt.HOSTS["prod"]:      # belt-and-braces against edits
    raise SystemExit("webull_bridge is paper-only.")

# OBSOLETE GUARD (2026-07-09): with SWINGPRO_BROKER=webull the bot places its
# orders on Webull DIRECTLY — mirroring forward_log again would DOUBLE-ORDER.
from data import _env
if (_env("SWINGPRO_BROKER") or "alpaca").lower() == "webull":
    raise SystemExit("bot trades Webull directly (SWINGPRO_BROKER=webull); "
                     "the mirror is obsolete and would duplicate orders.")

# The PUBLIC shared UAT account enforces ORDER_RISK_RULE_NOTIONAL at $1,000
# per order (measured 2026-07-08: $1,020 rejected, $680 accepted). Mirrors are
# qty-clamped to fit; the log records original vs sent qty. A dedicated test
# account from Webull support would lift this.
MAX_MIRROR_NOTIONAL = 1000.0

# forward_trader events that correspond to a REAL submitted order (they carry
# the Alpaca order id in the `order` column) and the side they map to.
EVENT_SIDE = {
    "BUY": "BUY", "DAILY_BUY": "BUY",
    "SELL_STOP": "SELL", "SELL_TARGET": "SELL", "SELL_EOD": "SELL",
    "TP1_PARTIAL": "SELL", "DAILY_STOP": "SELL", "DAILY_TARGET": "SELL",
}


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"account_id": None, "mirrored": {}}


def _save_state(st: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, indent=1))


def _paper_account(st: dict) -> str | None:
    """Resolve (and cache) the paper account id; None => no working UAT creds
    yet, bridge runs dry."""
    if st.get("account_id"):
        return st["account_id"]
    try:
        subs = wt.accounts(env=ENV)
        acct = subs[0]["account_id"] if isinstance(subs, list) and subs else None
        if acct:
            st["account_id"] = acct
        return acct
    except WebullError:
        return None


def _order_events():
    if not FORWARD_LOG.exists():
        return []
    with open(FORWARD_LOG, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f)
                if r.get("event") in EVENT_SIDE and r.get("order")]


def run_once(dry_only=False) -> int:
    st = _load_state()
    acct = None if dry_only else _paper_account(st)
    live = acct is not None
    if not live:
        print("no working UAT credentials -> DRY-RUN mirroring "
              "(set WEBULL_UAT_APP_KEY / WEBULL_UAT_APP_SECRET to go live)")
    mirrored = st["mirrored"]
    new = 0
    for r in _order_events():
        oid = r["order"]
        if mirrored.get(oid) not in (None, "DRY"):
            continue                       # already mirrored for real
        if mirrored.get(oid) == "DRY" and not live:
            continue                       # already logged the dry intent
        side = EVENT_SIDE[r["event"]]
        sym, qty = r["symbol"], int(float(r["qty"]))
        sent_qty = qty
        if live:
            try:
                from webull_data import snapshot
                px = float(snapshot([sym])[0]["price"])
                cap = max(1, int(MAX_MIRROR_NOTIONAL // px))
                sent_qty = min(qty, cap)
            except (WebullError, KeyError, ValueError, IndexError):
                pass                       # no price -> try full qty, venue decides
        try:
            resp = wt.place_order(acct or "PENDING-UAT-CREDS", sym, side,
                                  sent_qty, order_type="MARKET", env=ENV,
                                  execute=live)
            mirrored[oid] = resp.get("client_order_id", "?") if live else "DRY"
            clamp = f" (clamped from {qty})" if sent_qty != qty else ""
            print(f"{'MIRRORED' if live else 'DRY-LOGGED'} {r['event']} "
                  f"{side} {sent_qty} {sym}{clamp} (alpaca {oid[:8]}...) -> "
                  f"{mirrored[oid]}")
            new += 1
        except WebullError as e:
            print(f"FAILED {side} {sent_qty} {sym}: {e}")
    st["last_run"] = datetime.now(timezone.utc).isoformat()
    _save_state(st)
    if not new:
        print("nothing new to mirror.")
    return new


def status():
    st = _load_state()
    ev = _order_events()
    live = sum(1 for v in st["mirrored"].values() if v not in ("DRY", None))
    dry = sum(1 for v in st["mirrored"].values() if v == "DRY")
    print(f"paper account: {st.get('account_id') or 'NOT LINKED (need UAT creds)'}")
    print(f"order events in forward_log: {len(ev)}; mirrored live: {live}; "
          f"dry-logged: {dry}; last run: {st.get('last_run', 'never')}")
    for r in ev:
        oid = r["order"]
        print(f"  {r['ts']}  {r['event']:<13} {r['symbol']:<5} x{r['qty']:<4} "
              f"-> {st['mirrored'].get(oid, 'PENDING')}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Mirror bot orders to Webull paper")
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry", action="store_true", help="force dry-run logging")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()
    if a.status:
        status()
    elif a.once or a.dry:
        sys.exit(0 if run_once(dry_only=a.dry) >= 0 else 1)
    else:
        p.print_help()
