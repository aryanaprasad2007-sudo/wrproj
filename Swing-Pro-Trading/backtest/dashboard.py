"""
dashboard.py — iAPE local control dashboard (formerly SWING_PRO).

A single-file web app (stdlib only, matching the codebase's no-deps idiom):
  py dashboard.py            # serves http://127.0.0.1:8788 and opens it
  py dashboard.py --port N   # custom port
  py dashboard.py --no-open  # don't launch the browser

What it shows (auto-refreshes every 30s):
  * equity + buying power on the ACTIVE venue (broker.py: alpaca | webull)
  * 1-month equity curve (Alpaca portfolio history) with hover readout
  * open positions per track, queued daily entries (forward_state.json)
  * the event feed (forward_log.csv tail, newest first, status-classed)
  * all 8 SwingPro scheduled tasks with next-run + enable/disable buttons
  * Webull paper mirror state (bridge state + order log tail)

What it can DO (POST /api/action, whitelisted, localhost-only):
  * pause/resume any SwingPro_* scheduled task (schtasks /change)
  * run the Webull mirror once, refresh the cockpit, run a bot tick
None of these can place a real-money order: the tick trades paper by
construction, the mirror is paper-only, and prod orders require an interactive
typed confirmation this server cannot provide.

SECURITY: binds 127.0.0.1 ONLY. Do not port-forward it.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

def _refresh_webull_keys_from_registry():
    """The Windows User registry is the source of truth for these keys; a
    long-running login session can hold a STALE copy in its environment (e.g.
    after an API-key rotation), which os.environ would otherwise prefer. Pull
    the current values from the registry at startup so the real-money panel and
    the paper venue always authenticate, however the app was launched."""
    if os.name != "nt":
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            for name in ("WEBULL_APP_KEY", "WEBULL_APP_SECRET",
                         "WEBULL_UAT_APP_KEY", "WEBULL_UAT_APP_SECRET"):
                try:
                    os.environ[name] = winreg.QueryValueEx(k, name)[0]
                except OSError:
                    pass
    except OSError:
        pass


_refresh_webull_keys_from_registry()

import broker
import botconfig
import control
from data import _env

# the validated strategy internals shown READ-ONLY (changing them would
# invalidate the audition — see botconfig.py). Sourced from the live config.
try:
    from swing_pro import config_v22
    _CFG = config_v22(trade_dir="long")
    LOCKED_STRATEGY = {
        "engine": "iAPE v4 (v2.2 engine, momentum, long-only)",
        "exit": "pure stop + 3R target (no comfort exits)",
        "atr_stop_mult": _CFG.atr_stop_mult, "rr_ratio": _CFG.rr_ratio,
        "adx_min": getattr(_CFG, "adx_min", "—"),
        "rsi_long_level": getattr(_CFG, "rsi_long_level", "—"),
        "daily_track": "iAPE-D (config_v22, local EMA50 regime)",
        "mr_track": "MR-1 shadow: RSI(3)<15 & close>SMA200 (own task)",
    }
except Exception:
    LOCKED_STRATEGY = {}

HERE = Path(__file__).resolve().parent
STATE_F = HERE / "forward_state.json"
LOG_F = HERE / "forward_log.csv"
BRIDGE_F = HERE / "cache" / "webull_bridge_state.json"
WB_ORDERS = HERE / "cache" / "webull_orders.csv"
MONTH_BT = HERE / "cache" / "month_backtest.json"
COCKPIT = HERE.parent / "cockpit.html"

TASKS = ["SwingPro_Forward_Test", "SwingPro_Flow_Capture",
         "SwingPro_Options_Snapshot", "SwingPro_Daily_Signals",
         "SwingPro_Forward_Report", "SwingPro_Cockpit",
         "SwingPro_Weekly_Review", "SwingPro_MR_Shadow"]

ACTIONS = {   # action name -> argv (run in HERE, output returned to the UI)
    "bridge": [sys.executable, "webull_bridge.py", "--once"],
    "cockpit": [sys.executable, "cockpit.py"],
    "tick": [sys.executable, "forward_trader.py", "--once"],
    "kill": [sys.executable, "forward_trader.py", "--flatten"],
    "resume": [sys.executable, "forward_trader.py", "--resume"],
}
# events that should raise an alert banner + browser notification
ALERT_EVENTS = ("TICK_ERROR", "RECONCILE_ERROR", "KILL_ERROR", "DAILY_ERROR",
                "DAILY_SCAN_ERROR")
ORDER_EVENTS = ("BUY", "DAILY_BUY", "STOP", "BREAKEVEN", "TARGET", "DAILY_STOP",
                "DAILY_TARGET", "TP1_PARTIAL", "TREND_EXIT", "KILL_FLATTEN")

_cache: dict = {"t": 0.0, "state": None}
_cache_lock = threading.Lock()
_real_cache: dict = {"t": 0.0, "data": None}     # real prod account (60s TTL)
_spot_cache: dict = {"t": 0.0, "data": None}     # focus-symbol spotlight (45s TTL)


def spotlight(symbol: str):
    """Live read of the primary focus symbol: price + change, and what the
    momentum engine currently sees on the DAILY timeframe (setup forming /
    BUY triggered / market filter). Daily bars are used because the free
    intraday IEX feed is too shallow for the indicators, and the daily engine
    is the validated flagship. Cached 45s and fully guarded."""
    with _cache_lock:
        if (_spot_cache["data"] and _spot_cache["data"].get("symbol") == symbol
                and time.time() - _spot_cache["t"] < 45):
            return _spot_cache["data"]
    out = {"symbol": symbol, "price": None, "change_ratio": None,
           "signal": None, "detail": None, "timeframe": "daily"}
    try:
        from webull_data import snapshot
        snap = snapshot([symbol])[0]
        out["price"] = float(snap.get("price") or 0)
        out["change_ratio"] = float(snap.get("change_ratio") or 0)
    except Exception:
        pass
    try:
        import forward_trader as ft
        d = ft.daily_bars(symbol, 460)
        spy = ft.daily_bars("SPY", 460)
        if len(d) >= 250 and len(spy) >= 250:
            sig = ft.compute_signals(d, spy, ft.CFG_D)
            i = len(d) - 1
            trig = bool(sig["go_long"][i])
            setup = bool(sig["long_state"][i])
            mkt = bool(sig["mkt_long_ok"][i])
            above = float(sig["close"][i]) > float(sig["trend_ma"][i])
            out["signal"] = ("BUY TRIGGERED" if trig else
                             "setup forming" if setup else
                             "no setup")
            out["detail"] = (f"{'above' if above else 'below'} 50-day trend · "
                             f"market filter {'OK' if mkt else 'blocks longs'}")
    except Exception as e:
        out["detail"] = f"signal unavailable ({str(e)[:60]})"
    with _cache_lock:
        _spot_cache.update(t=time.time(), data=out)
    return out


def real_account():
    """READ-ONLY snapshot of the actual Webull (prod, real-money) account:
    net liquidation, cash, buying power, and open positions. Never places an
    order. Cached 60s (three network calls). On auth failure returns an error
    hint — most often a shell opened before the last API-key rotation."""
    with _cache_lock:
        if _real_cache["data"] and time.time() - _real_cache["t"] < 60:
            return _real_cache["data"]
    out = {"error": None, "net_liq": None, "cash": None, "buying_power": None,
           "positions": []}
    try:
        import webull_trade as wt
        acct = wt.accounts(env="prod")[0]["account_id"]
        a = wt.balance(acct, env="prod")["account_currency_assets"][0]
        out.update(account_id=acct, net_liq=float(a["net_liquidation_value"]),
                   cash=float(a["cash_balance"]),
                   buying_power=float(a.get("cash_power") or a.get("margin_power") or 0))
        out["positions"] = [
            {"symbol": p["symbol"], "qty": float(p["qty"]),
             "cost": float(p.get("unit_cost") or 0),
             "last": float(p.get("last_price") or 0),
             "pl": float(p.get("unrealized_profit_loss") or 0)}
            for p in wt.positions(acct, env="prod").get("holdings", [])]
    except Exception as e:
        msg = str(e)[:160]
        if "401" in msg or "UNAUTHORIZED" in msg:
            msg = ("auth failed (401) — if you rotated the Webull key, open a "
                   "NEW terminal so the dashboard reads the current secret.")
        out["error"] = msg
    with _cache_lock:
        _real_cache.update(t=time.time(), data=out)
    return out


# ── friendly-interface data: health · clock · live scanner · prices ──────────
_scan_cache: dict = {"t": 0.0, "data": None}
_clock_cache: dict = {"t": 0.0, "data": None}
_price_cache: dict = {"t": 0.0, "data": {}}


def _alp(path, **q):
    import urllib.parse
    url = "https://paper-api.alpaca.markets" + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY")})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())


def alpaca_clock():
    """is_open + next open/close (ISO, market tz). Holiday-aware; cached 30s."""
    with _cache_lock:
        if _clock_cache["data"] and time.time() - _clock_cache["t"] < 30:
            return _clock_cache["data"]
    out = {"is_open": None, "next_open": None, "next_close": None}
    try:
        c = _alp("/v2/clock")
        out = {"is_open": bool(c.get("is_open")), "next_open": c.get("next_open"),
               "next_close": c.get("next_close")}
    except Exception:
        pass
    with _cache_lock:
        _clock_cache.update(t=time.time(), data=out)
    return out


def next_daily_scan_epoch():
    """Epoch seconds of the next SwingPro_Daily_Signals run (13:05 PT, weekdays)."""
    try:
        import pandas as pd
        now = pd.Timestamp.now(tz="America/Los_Angeles")
        target = now.normalize() + pd.Timedelta(hours=13, minutes=5)
        if now >= target:
            target += pd.Timedelta(days=1)
        while target.dayofweek >= 5:                # skip Sat/Sun
            target += pd.Timedelta(days=1)
        return target.timestamp()
    except Exception:
        return None


def _tick_age_min():
    """Minutes since the last good tick (forward_state.json is rewritten each
    tick). Only meaningful during market hours — tick() no-ops when closed."""
    try:
        return (time.time() - STATE_F.stat().st_mtime) / 60.0
    except OSError:
        return None


def live_prices(symbols):
    """Live prices for a few symbols (open positions) via webull_data snapshot,
    cached 30s. Returns {SYM: price}; empty/partial on any failure."""
    symbols = sorted({s for s in symbols if s})
    if not symbols:
        return {}
    key = ",".join(symbols)
    with _cache_lock:
        if _price_cache["data"].get("_key") == key and time.time() - _price_cache["t"] < 30:
            return _price_cache["data"]
    out = {"_key": key}
    try:
        from webull_data import snapshot
        for r in snapshot(symbols):
            sym = str(r.get("symbol", "")).upper()
            px = float(r.get("price") or 0) or None
            if sym and px:
                out[sym] = px
    except Exception:
        pass
    with _cache_lock:
        _price_cache.update(t=time.time(), data=out)
    return out


def _scanner_compute():
    """Every traded symbol: live price, DAILY signal state (none/forming/
    triggered), trend + market-filter reads, and whether the current book can
    afford 1 share. Heavy (bars per symbol) — run in a background thread."""
    import forward_trader as ft
    bc = botconfig.load()
    try:
        eq, _ = broker.account()
    except Exception:
        eq = None
    book = botconfig.sizing_equity(eq if eq is not None else 2000.0, broker.BROKER, bc)
    per_trade = (float(bc.get("sizing_pct", 10.0)) / 100.0) * book
    syms = ft.daily_universe(bc)
    prices = {}
    try:
        from webull_data import snapshot
        for r in snapshot(syms):
            sym = str(r.get("symbol", "")).upper()
            px = float(r.get("price") or 0) or None
            if px:
                prices[sym] = px
    except Exception:
        pass
    try:
        spy = ft.daily_bars("SPY", 460)
    except Exception:
        spy = None
    rows = []
    for sym in syms:
        row = {"symbol": sym, "price": None, "signal": None, "above_trend": None,
               "mkt_ok": None, "affordable": None, "shares": 0}
        try:
            d = ft.daily_bars(sym, 460)
            px = prices.get(sym) or (float(d["close"].iloc[-1]) if len(d) else None)
            row["price"] = round(px, 2) if px else None
            if px:
                row["shares"] = int(per_trade / px)
                row["affordable"] = per_trade >= px
            if spy is not None and len(d) >= 250 and len(spy) >= 250:
                sg = ft.compute_signals(d, spy, ft.CFG_D)
                i = len(d) - 1
                row["above_trend"] = bool(float(sg["close"][i]) > float(sg["trend_ma"][i]))
                row["mkt_ok"] = bool(sg["mkt_long_ok"][i])
                row["signal"] = ("triggered" if bool(sg["go_long"][i])
                                 else "forming" if bool(sg["long_state"][i]) else "none")
        except Exception as e:
            row["error"] = str(e)[:40]
        rows.append(row)
    return {"as_of": datetime.now().strftime("%H:%M:%S"), "per_trade": round(per_trade, 0),
            "book": book, "sizing_pct": float(bc.get("sizing_pct", 10.0)), "rows": rows}


def _scanner_loop():
    while True:
        try:
            data = _scanner_compute()
            with _cache_lock:
                _scan_cache.update(t=time.time(), data=data)
        except Exception:
            pass
        time.sleep(240)


def scanner():
    with _cache_lock:
        return _scan_cache["data"]


def enriched_positions(st, equity):
    """Open positions in both books with live price, unrealized P/L, and a
    0..1 progress from stop→target. Plus a portfolio risk summary."""
    pos_syms = list(st.get("positions", {})) + list(st.get("daily_positions", {}))
    px_map = live_prices(pos_syms)
    rows, total_risk = [], 0.0
    for book_name, kind in (("positions", "5m"), ("daily_positions", "daily")):
        for sym, p in st.get(book_name, {}).items():
            entry = float(p.get("entry_ref", 0) or 0)
            sl = float(p.get("sl", 0) or 0)
            tp = float(p.get("tp", 0) or 0)
            qty = float(p.get("qty", 0) or 0)
            price = px_map.get(sym)
            risk = max(entry - sl, 0) * qty
            total_risk += risk
            unreal = (price - entry) * qty if price else None
            frac = (max(0.0, min(1.0, (price - sl) / (tp - sl)))
                    if (price and tp > sl) else None)
            rows.append({"symbol": sym, "kind": kind, "qty": qty,
                         "entry": round(entry, 2), "stop": round(sl, 2),
                         "target": round(tp, 2),
                         "price": round(price, 2) if price else None,
                         "unreal": round(unreal, 2) if unreal is not None else None,
                         "risk": round(risk, 2), "frac": frac,
                         "be": bool(p.get("be_done"))})
    book = equity if equity else 2000.0
    summary = {"total_risk": round(total_risk, 2),
               "pct_of_book": round(100.0 * total_risk / book, 1) if book else None,
               "slots_used": len(rows), "slots_max": int(botconfig.load()["max_positions"]),
               "unreal_total": round(sum(r["unreal"] for r in rows if r["unreal"] is not None), 2)}
    return rows, summary


# ── data assembly ────────────────────────────────────────────────────────────
def _tasks_status():
    try:
        r = subprocess.run(["schtasks", "/query", "/fo", "csv"],
                           capture_output=True, text=True, timeout=20)
        rows = list(csv.DictReader(r.stdout.splitlines()))
        by_name = {row["TaskName"].lstrip("\\"): row for row in rows}
        return [{"name": t,
                 "status": by_name.get(t, {}).get("Status", "MISSING"),
                 "next_run": by_name.get(t, {}).get("Next Run Time", "?")}
                for t in TASKS]
    except Exception as e:
        return [{"name": t, "status": f"query failed: {e}", "next_run": "?"}
                for t in TASKS]


def _equity_history():
    """1M daily equity from Alpaca (works regardless of active venue — it is
    the long-running forward-test account). Empty list if unreachable."""
    try:
        import urllib.parse
        q = urllib.parse.urlencode({"period": "1M", "timeframe": "1D"})
        req = urllib.request.Request(
            "https://paper-api.alpaca.markets/v2/account/portfolio/history?" + q,
            headers={"APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
                     "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY")})
        with urllib.request.urlopen(req, timeout=15) as r:
            h = json.loads(r.read().decode())
        return [{"t": datetime.fromtimestamp(ts).strftime("%m/%d"),
                 "eq": eq} for ts, eq in zip(h.get("timestamp", []),
                                             h.get("equity", []))
                if eq]                       # drop None AND pre-funding zeros
    except Exception:
        return []


def _log_tail(n=40):
    if not LOG_F.exists():
        return []
    with open(LOG_F, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[-n:][::-1]


def _wb_orders_tail(n=15):
    if not WB_ORDERS.exists():
        return []
    with open(WB_ORDERS, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[-n:][::-1]


def trade_progress(n_recent=12):
    """The bot's OWN closed-trade record, reconstructed from the event log
    (forward_log.csv) in pure stdlib so the dashboard keeps its no-deps design.

    P/L is measured at the LOGGED signal levels — entry ref vs the stop/target
    the strategy fired at — NOT broker-verified fills. That is deliberate: the
    Webull UAT venue is a SHARED sim account whose balance can't be trusted, so
    the honest record of what THIS bot did is its own event log. Positions are
    sized off the live book, so on a $2,000 book these are $2,000-scale dollars.

    Counts only trades AFTER the most recent SIM_RESET / VENUE_SWITCH marker, so
    'this run' starts clean when the venue or the sim book changes."""
    rows = []
    if LOG_F.exists():
        with open(LOG_F, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    # anchor: everything after the last reset/venue marker
    start = 0
    for i, r in enumerate(rows):
        if (r.get("event") or "") in ("SIM_RESET", "VENUE_SWITCH"):
            start = i + 1
    rows = rows[start:]

    def fnum(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    open_i, open_d, closed = {}, {}, []
    EXIT_I = {"STOP", "BREAKEVEN", "TARGET", "TREND_EXIT"}
    for r in rows:
        ev = r.get("event", "") or ""
        sym = r.get("symbol", "") or ""
        qty, ref = fnum(r.get("qty")), fnum(r.get("ref_price"))
        if ev == "BUY" and qty and ref is not None:
            open_i[sym] = {"qty": qty, "entry": ref, "ts": r.get("ts", "")}
        elif ev in EXIT_I and sym in open_i:
            t = open_i.pop(sym)
            ex = ref if ref is not None else t["entry"]
            closed.append({"symbol": sym, "track": "5m", "entry": t["entry"],
                           "exit": ex, "exit_ev": ev,
                           "pnl": t["qty"] * (ex - t["entry"]), "ts": r.get("ts", "")})
        elif ev == "DAILY_BUY" and qty and ref is not None:
            open_d[sym] = {"qty": qty, "entry": ref, "ts": r.get("ts", "")}
        elif ev in ("DAILY_STOP", "DAILY_TARGET") and sym in open_d:
            t = open_d.pop(sym)
            ex = ref if ref is not None else t["entry"]
            closed.append({"symbol": sym, "track": "daily", "entry": t["entry"],
                           "exit": ex, "exit_ev": ev.replace("DAILY_", ""),
                           "pnl": t["qty"] * (ex - t["entry"]), "ts": r.get("ts", "")})

    n = len(closed)
    wins = [c for c in closed if c["pnl"] > 0]
    gross_w = sum(c["pnl"] for c in wins)
    gross_l = -sum(c["pnl"] for c in closed if c["pnl"] <= 0)
    pf = round(gross_w / gross_l, 2) if gross_l > 0 else None   # None => no losers
    return {"closed": n, "wins": len(wins),
            "win_rate": (100.0 * len(wins) / n) if n else None,
            "pf": pf, "net": sum(c["pnl"] for c in closed),
            "open_now": len(open_i) + len(open_d),
            "recent": list(reversed(closed))[:n_recent],
            "series": [{"ts": c["ts"], "pnl": round(c["pnl"], 2)} for c in closed]}


def system_health(tasks, events, market_open):
    """One green/amber/red read on 'is the bot actually working': trader task
    enabled, ticking recently (in market hours), tasks ready, errors today."""
    tick_age = _tick_age_min()
    ft_task = next((t for t in tasks if t["name"] == "SwingPro_Forward_Test"), None)
    ft_on = bool(ft_task and ft_task["status"] in ("Ready", "Running"))
    today = datetime.now().strftime("%Y-%m-%d")
    errs = sum(1 for e in events if (e.get("event", "") or "").endswith("ERROR")
               and str(e.get("ts", "")).startswith(today))
    ready = sum(1 for t in tasks if t["status"] in ("Ready", "Running"))
    level, reasons = "ok", []
    if not ft_on:
        level = "crit"; reasons.append("trader task disabled")
    if market_open and tick_age is not None and tick_age > 15:
        level = "crit"; reasons.append(f"no tick in {tick_age:.0f} min")
    if errs >= 5:
        level = "crit" if level == "crit" else "warn"
        reasons.append(f"{errs} errors today")
    elif errs:
        level = "warn" if level == "ok" else level
        reasons.append(f"{errs} error{'s' if errs > 1 else ''} today")
    if ready < len(tasks):
        level = "warn" if level == "ok" else level
        reasons.append(f"{len(tasks) - ready} task(s) paused")
    return {"level": level, "msg": "All systems go" if level == "ok" else "; ".join(reasons),
            "tick_age_min": round(tick_age, 1) if tick_age is not None else None,
            "errors_today": errs, "tasks_ready": ready, "tasks_total": len(tasks)}


def build_state():
    with _cache_lock:
        if _cache["state"] and time.time() - _cache["t"] < 10:
            return _cache["state"]
    st = json.loads(STATE_F.read_text()) if STATE_F.exists() else {}
    try:
        equity, bp = broker.account()
        acct_err = None
    except Exception as e:
        equity, bp, acct_err = None, None, str(e)[:120]
    try:
        mkt = broker.market_open()
    except Exception:
        mkt = None
    bridge = json.loads(BRIDGE_F.read_text()) if BRIDGE_F.exists() else {}
    tasks = _tasks_status()
    events = _log_tail()
    prog = trade_progress()
    pos_live, risk = enriched_positions(st, equity)
    base = equity if equity else 2000.0
    run, sim_curve = base, ([{"t": "start", "eq": round(base, 2)}] if prog["series"] else [])
    for c in prog["series"]:
        run += c["pnl"]
        sim_curve.append({"t": str(c["ts"])[5:16].replace("T", " "), "eq": round(run, 2)})
    out = {
        "generated": datetime.now().strftime("%H:%M:%S"),
        "venue": broker.VENUE, "broker": broker.BROKER,
        "market_open": mkt,
        "health": system_health(tasks, events, bool(mkt)),
        "clock": alpaca_clock(),
        "next_scan_epoch": next_daily_scan_epoch(),
        "scanner": scanner(),
        "positions_live": pos_live,
        "risk": risk,
        "sim_curve": sim_curve,
        "verdict": {"closed": prog["closed"], "judge": 30, "pf": prog["pf"],
                    "bench_pf": 1.72, "win_rate": prog["win_rate"]},
        "control": control.status(),
        "settings": botconfig.load(),
        "locked_strategy": LOCKED_STRATEGY,
        "spotlight": spotlight((botconfig.load().get("focus_symbols") or ["AAPL"])[0]),
        "real_account": real_account(),
        "equity": equity, "buying_power": bp, "account_error": acct_err,
        "positions": st.get("positions", {}),
        "daily_positions": st.get("daily_positions", {}),
        "daily_pending": st.get("daily_pending", {}),
        "shadow": st.get("shadow", {}),
        "events": events,
        "progress": prog,
        "backtest": (json.loads(MONTH_BT.read_text()) if MONTH_BT.exists() else None),
        "tasks": tasks,
        "equity_history": _equity_history(),
        "bridge": {"account": bridge.get("account_id"),
                   "mirrored": bridge.get("mirrored", {}),
                   "last_run": bridge.get("last_run")},
        "webull_orders": _wb_orders_tail(),
        "cockpit_mtime": (datetime.fromtimestamp(COCKPIT.stat().st_mtime)
                          .strftime("%Y-%m-%d %H:%M") if COCKPIT.exists() else None),
    }
    with _cache_lock:
        _cache.update(t=time.time(), state=out)
    return out


# ── actions ──────────────────────────────────────────────────────────────────
def run_action(payload):
    name = payload.get("action")
    if name == "close_position":
        # Sell (CLOSE) a REAL position at market. De-risking only — this path
        # never opens a new position. Requires the exact confirm token the UI
        # sends after the user clicks through the confirmation dialog, so a
        # stray/accidental request cannot fire. Quantity is taken from the LIVE
        # account holding (never the client), so it can't oversell/short.
        symbol = str(payload.get("symbol", "")).upper()
        if payload.get("confirm") != f"SELL {symbol}":
            return {"ok": False, "output": "confirmation token missing/mismatched"}
        try:
            import webull_trade as wt
            acct = wt.accounts(env="prod")[0]["account_id"]
            held = 0
            for p in wt.positions(acct, env="prod").get("holdings", []):
                if p.get("symbol", "").upper() == symbol:
                    held = int(float(p.get("qty") or 0))
            if held < 1:
                return {"ok": False, "output": f"no live {symbol} position to close"}
            resp = wt.place_order(acct, symbol, "SELL", held, order_type="MARKET",
                                  env="prod", execute=True, web_confirmed=True)
            with _cache_lock:
                _real_cache["t"] = 0.0
            return {"ok": True, "output": f"market SELL {held} {symbol} sent to your "
                    f"real account — {json.dumps(resp)[:200]}"}
        except Exception as e:
            return {"ok": False, "output": f"close failed: {str(e)[:200]}"}
    if name == "settings":
        cfg = botconfig.save(payload.get("settings", {}))
        with _cache_lock:
            _cache["t"] = 0.0
        return {"ok": True, "output": "settings saved — live on the next tick",
                "settings": cfg}
    if name == "observer":
        control.set_observer(bool(payload.get("enable")))
        with _cache_lock:
            _cache["t"] = 0.0
        return {"ok": True, "output": "observer mode "
                + ("ON — new entries need a fresh dashboard heartbeat"
                   if payload.get("enable") else "OFF")}
    if name == "kill":
        # halt+flatten, then also disable the tick task so nothing re-enters
        r = subprocess.run(ACTIONS["kill"], cwd=HERE, capture_output=True,
                           text=True, timeout=120)
        subprocess.run(["schtasks", "/change", "/tn", "SwingPro_Forward_Test",
                        "/disable"], capture_output=True, text=True, timeout=20)
        with _cache_lock:
            _cache["t"] = 0.0
        return {"ok": r.returncode == 0,
                "output": "KILL SWITCH: " + (r.stdout + r.stderr).strip()[-500:]
                + " · tick task disabled"}
    if name == "resume":
        subprocess.run(ACTIONS["resume"], cwd=HERE, capture_output=True,
                       text=True, timeout=30)
        subprocess.run(["schtasks", "/change", "/tn", "SwingPro_Forward_Test",
                        "/enable"], capture_output=True, text=True, timeout=20)
        with _cache_lock:
            _cache["t"] = 0.0
        return {"ok": True, "output": "resumed: halt cleared + tick task enabled"}
    if name == "task":
        task = payload.get("task", "")
        if task not in TASKS:
            return {"ok": False, "output": f"unknown task {task!r}"}
        flag = "/enable" if payload.get("enable") else "/disable"
        r = subprocess.run(["schtasks", "/change", "/tn", task, flag],
                           capture_output=True, text=True, timeout=20)
        return {"ok": r.returncode == 0,
                "output": (r.stdout + r.stderr).strip()[:400]}
    if name in ACTIONS:
        r = subprocess.run(ACTIONS[name], cwd=HERE, capture_output=True,
                           text=True, timeout=180)
        with _cache_lock:
            _cache["t"] = 0.0                      # bust cache after actions
        return {"ok": r.returncode == 0,
                "output": (r.stdout + r.stderr).strip()[-800:]}
    return {"ok": False, "output": f"unknown action {name!r}"}


# ── http ─────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                     # quiet console
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE.encode(), "text/html")
        elif self.path.startswith("/api/state"):
            control.touch_heartbeat()          # a human is watching = fresh beat
            self._send(200, build_state())
        elif self.path.startswith("/cockpit"):
            if COCKPIT.exists():
                self._send(200, COCKPIT.read_bytes(), "text/html")
            else:
                self._send(404, {"error": "cockpit.html not built yet"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/api/action"):
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        self._send(200, run_action(payload))


# ── the page ─────────────────────────────────────────────────────────────────
PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>iAPE — Control</title>
<style>
:root{
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
  --muted:#898781; --grid:#2c2c2a; --axis:#383835;
  --border:rgba(255,255,255,.10); --series1:#3987e5;
  --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --crit:#d03b3b;
  --up:#0ca30c; --down:#e66767;
}
@media (prefers-color-scheme: light){:root{
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
  --border:rgba(11,11,11,.10); --series1:#2a78d6;
  --up:#006300; --down:#d03b3b;
}}
*{box-sizing:border-box;margin:0}
body{background:var(--page);color:var(--ink);
  font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:20px}
h1{font-size:17px;font-weight:650;letter-spacing:.2px}
h2{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;
  letter-spacing:.7px;margin:0 0 10px}
.wrap{max-width:1180px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
.bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);
  border-radius:999px;padding:3px 11px;font-size:12px;color:var(--ink2)}
.dot{width:8px;height:8px;border-radius:50%;flex:none}
.spacer{flex:1}
.card{background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:14px 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile .lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}
.tile .val{font-size:24px;font-weight:650;margin-top:3px}
.tile .sub{font-size:12px;color:var(--ink2);margin-top:2px}
.grid2{display:grid;grid-template-columns:1.4fr 1fr;gap:14px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--muted);font-weight:600;text-align:left;font-size:11px;
  text-transform:uppercase;letter-spacing:.5px;padding:4px 8px;
  border-bottom:1px solid var(--grid)}
td{padding:5px 8px;border-bottom:1px solid var(--grid);color:var(--ink2)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td .sym{color:var(--ink);font-weight:600}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:12px}
.up{color:var(--up)} .down{color:var(--down)}
button{background:transparent;color:var(--ink2);border:1px solid var(--border);
  border-radius:7px;padding:5px 12px;font:600 12px system-ui;cursor:pointer}
button:hover{border-color:var(--muted);color:var(--ink)}
button:disabled{opacity:.45;cursor:wait}
button.danger{border-color:var(--crit);color:var(--crit);font-weight:700}
button.danger:hover{background:var(--crit);color:#fff}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.switch{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2);cursor:pointer}
button.primary{border-color:var(--series1);color:var(--series1);font-weight:700}
button.primary:hover{background:var(--series1);color:#fff}
.settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.settings-grid label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--ink2)}
.settings-grid .hint{color:var(--muted);font-size:11px}
.settings-grid input{background:var(--page);border:1px solid var(--border);border-radius:7px;
  color:var(--ink);padding:7px 9px;font:600 14px system-ui;font-variant-numeric:tabular-nums}
.settings-grid input:focus{outline:none;border-color:var(--series1)}
#locked table td{padding:3px 8px}
#banner{border-radius:10px;padding:10px 14px;font-size:13px;font-weight:600;
  border:1px solid var(--crit);background:rgba(208,59,59,.12);color:var(--crit)}
#banner.warn{border-color:var(--warn);background:rgba(250,178,25,.12);color:var(--warn)}
#gate .dot{background:var(--good)}
#toast{font-size:12px;color:var(--muted);white-space:pre-wrap;max-height:88px;
  overflow:auto;margin-top:8px;font-family:Consolas,monospace}
#chart{width:100%;height:190px;display:block}
.tip{position:fixed;pointer-events:none;background:var(--surface);
  border:1px solid var(--border);border-radius:7px;padding:6px 10px;
  font-size:12px;color:var(--ink);display:none;box-shadow:0 4px 14px rgba(0,0,0,.35)}
.empty{color:var(--muted);font-size:13px;padding:6px 0}
a{color:var(--series1)}
.scroll{overflow-x:auto}
#health .dot{background:var(--muted)}
#health.ok .dot{background:var(--good)}
#health.warn .dot{background:var(--warn)}
#health.crit .dot{background:var(--crit)}
#health.crit{border-color:var(--crit);color:var(--crit)}
#statuscard{border-left:3px solid var(--series1)}
#statusline .big{font-weight:650}
#statusline .cd{font-variant-numeric:tabular-nums;color:var(--ink);font-weight:600}
.sig{font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px;white-space:nowrap}
.sig.triggered{background:rgba(12,163,12,.16);color:var(--good)}
.sig.forming{background:rgba(250,178,25,.16);color:var(--warn)}
.sig.none{background:rgba(137,135,129,.16);color:var(--muted)}
.yes{color:var(--up)} .no{color:var(--muted)}
.distbar{position:relative;height:8px;border-radius:6px;min-width:90px;
  background:linear-gradient(90deg,rgba(208,59,59,.40),rgba(137,135,129,.22) 50%,rgba(12,163,12,.40))}
.distbar .mk{position:absolute;top:-3px;width:3px;height:14px;border-radius:2px;background:var(--ink)}
.vbar{height:10px;border-radius:6px;background:var(--grid);overflow:hidden}
.vbar>span{display:block;height:100%;background:var(--series1)}
.glossary{display:grid;gap:7px;margin:8px 0}
.glossary .gt{display:inline-block;font-weight:700;color:var(--ink);margin-right:6px}
@media(max-width:640px){
  body{padding:12px}
  .bar{gap:8px} h1{font-size:15px}
  .tiles{grid-template-columns:repeat(auto-fit,minmax(118px,1fr))}
  .tile .val{font-size:20px}
  .metric:first-child .mval{font-size:24px}
}
</style></head><body><div class="wrap">

<div class="bar">
  <h1>iAPE</h1>
  <span class="pill" id="health"><span class="dot"></span><span></span></span>
  <span class="pill" id="venue"><span class="dot" style="background:var(--series1)"></span><span></span></span>
  <span class="pill" id="mkt"><span class="dot"></span><span></span></span>
  <span class="pill" id="gate"><span class="dot"></span><span></span></span>
  <span class="spacer"></span>
  <span class="pill" id="updated"></span>
</div>

<div id="banner" style="display:none"></div>

<div class="card" id="statuscard">
  <div id="statusline"></div>
</div>

<div class="card" id="spotcard" style="border-color:var(--series1)">
  <div id="spot"></div>
</div>

<div class="card" id="controlbar">
  <div class="actions" style="justify-content:space-between">
    <div class="actions">
      <button id="killbtn" class="danger" data-act="kill">■ KILL — halt &amp; flatten all</button>
      <button data-act="resume">Resume</button>
      <label class="switch"><input type="checkbox" id="obs"> Observer mode (require me watching)</label>
      <button id="alertsbtn">Enable desktop alerts</button>
    </div>
    <span id="gatereason" style="font-size:12px;color:var(--muted)"></span>
  </div>
</div>

<div class="tiles" id="tiles"></div>

<div class="card" id="scannercard">
  <h2>Watchlist <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— every symbol the bot watches: price, daily signal, and can this book afford it</span></h2>
  <div id="scanner"></div>
</div>

<div class="card" id="backtestcard">
  <h2>1-month backtest <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— what the current config would have done on this book</span></h2>
  <div id="backtest"></div>
</div>

<div class="card" id="progresscard">
  <h2>Trade progress — this run <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— the bot's own closed trades since the $2,000 reset</span></h2>
  <div id="verdict"></div>
  <div id="progress"></div>
</div>

<div class="card" id="settingscard">
  <h2>Bot settings — how much to trade &amp; what runs</h2>
  <div class="settings-grid">
    <label>Sizing per position (% of equity)
      <input id="set_sizing_pct" type="number" step="0.5" min="0.1" max="100"></label>
    <label>Max concurrent positions
      <input id="set_max_positions" type="number" step="1" min="1" max="50"></label>
    <label>Max $ per order <span class="hint">(0 = no cap)</span>
      <input id="set_max_notional_usd" type="number" step="50" min="0"></label>
    <label>Daily loss limit $ <span class="hint">(0 = off; pauses entries)</span>
      <input id="set_daily_loss_limit_usd" type="number" step="50" min="0"></label>
    <label id="wbeq_wrap">Webull sizing equity $ <span class="hint">(paper base)</span>
      <input id="set_webull_sizing_equity" type="number" step="1000" min="100"></label>
    <label id="alpeq_wrap">Book size to trade $ <span class="hint">(0 = full real balance)</span>
      <input id="set_alpaca_sizing_equity" type="number" step="500" min="0"></label>
    <label>Symbols to trade <span class="hint">(comma-sep; blank = full baskets)</span>
      <input id="set_focus_symbols" type="text" placeholder="e.g. AAPL"></label>
  </div>
  <div class="actions" style="margin-top:10px">
    <span style="font-size:12px;color:var(--muted)">Tracks:</span>
    <label class="switch"><input type="checkbox" id="trk_intraday"> Intraday 5m</label>
    <label class="switch"><input type="checkbox" id="trk_daily"> Daily SP-D</label>
    <span class="spacer"></span>
    <button id="savebtn" class="primary">Save settings</button>
    <span id="setmsg" style="font-size:12px;color:var(--muted)"></span>
  </div>
  <details style="margin-top:12px">
    <summary style="cursor:pointer;font-size:12px;color:var(--muted)">Validated strategy internals (locked — why?)</summary>
    <div id="locked" style="margin-top:8px"></div>
    <div style="font-size:11px;color:var(--muted);margin-top:6px">These are pre-registered and drive the audition you're scoring. Changing them live would invalidate the ≥30-trade comparison, so they're read-only here. A new strategy variant goes through a fresh backtest + audition, not a live edit.</div>
  </details>
</div>

<div class="card" id="realcard" style="border-color:var(--good)">
  <h2 style="color:var(--good)">● Real Webull account — LIVE MONEY (read-only)</h2>
  <div id="real"></div>
</div>

<div class="card">
  <h2 id="charttitle">Equity — last month</h2>
  <svg id="chart" role="img" aria-label="Equity curve, last month"></svg>
</div>

<div class="grid2">
  <div class="card">
    <h2>Bot positions &amp; queue <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">— practice/paper trades the bot placed</span></h2>
    <div id="positions"></div>
  </div>
  <div class="card">
    <h2>Scheduled tasks</h2>
    <div id="tasks"></div>
    <div class="actions" style="margin-top:12px">
      <button data-act="bridge">Mirror to Webull now</button>
      <button data-act="cockpit">Refresh cockpit</button>
      <button data-act="tick">Run bot tick</button>
      <a href="/cockpit" target="_blank" style="font-size:12px">Open cockpit ↗</a>
    </div>
    <div id="toast"></div>
  </div>
</div>

<div class="grid2">
  <div class="card">
    <h2>Event feed</h2>
    <div id="events" style="max-height:340px;overflow:auto"></div>
  </div>
  <div class="card">
    <h2>Webull paper mirror</h2>
    <div id="mirror"></div>
  </div>
</div>

<div class="card" id="helpcard">
  <details>
    <summary style="cursor:pointer;font-size:13px;font-weight:600">How this works &amp; what the words mean</summary>
    <div style="margin-top:12px;font-size:13px;color:var(--ink2);line-height:1.6">
      <p style="margin:0 0 10px"><b>This is practice money.</b> The bot trades a simulated Webull paper account — no real funds move here. Your real balance shows separately in the green “Real Webull account” card and is read-only.</p>
      <p style="margin:0 0 10px"><b>How a trade happens:</b> after each market close the daily engine scans your watchlist (1:05&nbsp;PM PT). If a symbol triggers, it’s queued and bought at the <i>next</i> market open, then managed automatically until it hits its stop or its target.</p>
      <div class="glossary">
        <div><span class="gt">Setup forming</span> the symbol meets most conditions but hasn’t fired the buy yet.</div>
        <div><span class="gt">Triggered</span> the buy condition is met — it’ll be bought at the next open.</div>
        <div><span class="gt">Stop</span> the price where a losing trade is cut. <span class="gt">Target (3R)</span> the price where a winner is taken — 3× the risk.</div>
        <div><span class="gt">R</span> one unit of risk (entry → stop). A “+3R” win makes 3× what a loss costs.</div>
        <div><span class="gt">Win rate</span> % of trades that profit. <span class="gt">Profit factor (PF)</span> gross wins ÷ gross losses; &gt;1 makes money.</div>
        <div><span class="gt">Affordable</span> the per-trade budget (sizing% × book) covers ≥1 share; un-affordable symbols are skipped.</div>
        <div><span class="gt">Observer mode</span> the bot only opens new trades while you’re watching (a fresh dashboard heartbeat). <span class="gt">Kill</span> halts everything and flattens.</div>
      </div>
      <p style="margin:10px 0 0;color:var(--muted)">The honest bar before any real-money talk: <b>≥30 closed trades at or above the benchmark</b> (profit factor 1.72). A good day or a bad month proves nothing on its own. Not financial advice.</p>
    </div>
  </details>
</div>

</div><div class="tip" id="tip"></div>
<script>
const $=s=>document.querySelector(s);
const fmt$=v=>v==null?"—":"$"+Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function fmtDur(ms){
  if(ms==null||isNaN(ms)) return "—";
  if(ms<=0) return "now";
  let s=Math.floor(ms/1000);
  const d=Math.floor(s/86400); s-=d*86400;
  const h=Math.floor(s/3600);  s-=h*3600;
  const m=Math.floor(s/60);    s-=m*60;
  if(d>0) return `${d}d ${h}h`;
  if(h>0) return `${h}h ${m}m`;
  if(m>0) return `${m}m ${s}s`;
  return `${s}s`;
}
function tickCountdowns(){
  document.querySelectorAll(".cd[data-until]").forEach(el=>{
    const u=parseInt(el.getAttribute("data-until"))||0;
    el.textContent = u ? fmtDur(u-Date.now()) : "—";
  });
}
setInterval(tickCountdowns,1000);

const EV_CLASS = e => /ERROR/.test(e) ? ["var(--crit)","●"]
  : /SKIP|EXPIRE|RECONCILE|FOREIGN/.test(e) ? ["var(--warn)","▲"]
  : /BUY|TARGET|TP1/.test(e) ? ["var(--good)","●"]
  : ["var(--muted)","○"];

function health(s){
  const h=s.health||{}, el=$("#health");
  el.className="pill "+(h.level||"");
  el.querySelector("span:last-child").textContent = h.level==="ok" ? "Systems OK" : (h.msg||"—");
  el.title = `tick ${h.tick_age_min==null?"—":h.tick_age_min+"m ago"} · tasks ${h.tasks_ready}/${h.tasks_total} · ${h.errors_today} errors today`;
}

function statusline(s){
  const c=s.control||{}, venue=esc(s.venue||""), book=fmt$(s.equity);
  const open=(s.positions_live||[]).length, q=Object.keys(s.daily_pending||{}).length;
  let head, sub="";
  if(c.halted){
    head=`<span class="big" style="color:var(--crit)">■ Halted.</span> Kill switch active — no new entries; exits still run. Press Resume to re-arm.`;
  } else {
    const gate = c.entries_allowed ? "" :
      `<span style="color:var(--warn)">Entries paused${c.reason&&c.reason!=="ok"?" ("+esc(c.reason)+")":""}; exits still run.</span> `;
    const hold = open ? `Holding <span class="big">${open}</span> position${open>1?"s":""}` : "Flat";
    const qd = q ? `, ${q} queued for the open` : "";
    head = `<span class="big">Live on ${venue}</span> · ${book} book. ${gate}${hold}${qd}.`;
    const scan = `Next daily scan <span class="cd" data-until="${Math.round((s.next_scan_epoch||0)*1000)}"></span>`;
    if(s.market_open){
      const nc = s.clock&&s.clock.next_close ? Date.parse(s.clock.next_close) : "";
      sub = `Market <span class="big" style="color:var(--good)">open</span> — closes in <span class="cd" data-until="${nc}"></span>. ${scan}.`;
    } else {
      const no = s.clock&&s.clock.next_open ? Date.parse(s.clock.next_open) : "";
      sub = `Market <span class="big">closed</span>. Opens in <span class="cd" data-until="${no}"></span>. ${scan} → earliest new trade at the following open.`;
    }
  }
  $("#statusline").innerHTML=`<div style="font-size:14px">${head}</div><div style="margin-top:5px;font-size:13px;color:var(--muted)">${sub}</div>`;
  tickCountdowns();
}

function scannerTable(s){
  const sc=s.scanner;
  if(!sc){ $("#scanner").innerHTML=`<div class="empty">Scanning the watchlist… (refreshes every few minutes)</div>`; return; }
  const rank=x=>x.signal==="triggered"?0:x.signal==="forming"?1:2;
  const rows=(sc.rows||[]).slice().sort((a,b)=>rank(a)-rank(b)||(a.symbol>b.symbol?1:-1));
  const badge=v=> v==null?`<span class="sig none">—</span>`
    : v==="triggered"?`<span class="sig triggered">● TRIGGERED</span>`
    : v==="forming"?`<span class="sig forming">◐ forming</span>`
    : `<span class="sig none">○ no setup</span>`;
  const nAff=(sc.rows||[]).filter(r=>r.affordable).length;
  let html=`<div style="font-size:12px;color:var(--muted);margin-bottom:8px">${nAff}/${(sc.rows||[]).length} affordable at ${fmt$(sc.per_trade)}/trade · updated ${esc(sc.as_of)}</div>
    <div class="scroll"><table><tr><th>Symbol</th><th class="num">Price</th><th>Daily signal</th><th>Trend</th><th>Market</th><th class="num">Shares</th><th>Buy?</th></tr>`+
    rows.map(r=>`<tr><td><span class="sym">${esc(r.symbol)}</span></td>
      <td class="num">${r.price!=null?fmt$(r.price):"—"}</td>
      <td>${badge(r.signal)}</td>
      <td style="font-size:12px">${r.above_trend==null?"—":(r.above_trend?'<span class="yes">above</span>':'<span class="no">below</span>')}</td>
      <td style="font-size:12px">${r.mkt_ok==null?"—":(r.mkt_ok?'<span class="yes">OK</span>':'<span class="no">blocks</span>')}</td>
      <td class="num">${r.shares||0}</td>
      <td>${r.affordable==null?'<span class="muted">—</span>':(r.affordable?'<span class="yes">✓ can buy</span>':'<span class="no">✕ too pricey</span>')}</td></tr>`).join("")+`</table></div>`;
  $("#scanner").innerHTML=html;
}

function verdictBar(s){
  const v=s.verdict||{}, judge=v.judge||30, frac=Math.max(0,Math.min(1,(v.closed||0)/judge));
  const pfTxt = v.pf==null?"—":(+v.pf).toFixed(2);
  $("#verdict").innerHTML=`<div style="margin-bottom:12px">
    <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;font-size:12px;color:var(--muted);margin-bottom:5px">
      <span>Progress to a verdict: <b style="color:var(--ink)">${v.closed||0} / ${judge}</b> closed trades</span>
      <span>PF ${pfTxt} vs benchmark ${v.bench_pf}</span></div>
    <div class="vbar"><span style="width:${(frac*100).toFixed(0)}%"></span></div>
    <div style="font-size:11px;color:var(--muted);margin-top:5px">Real-money talk stays off the table until this fills at or above the benchmark.</div>
  </div>`;
}

function tiles(s){
  const eq=s.equity, base=s.broker==="alpaca"?100000:null;
  const d = (eq!=null&&base)?eq-base:null;
  const pos=Object.keys(s.positions).length, dpos=Object.keys(s.daily_positions).length;
  const today=new Date().toISOString().slice(0,10);
  const evToday=s.events.filter(e=>(e.ts||"").startsWith(today)).length;
  const ready=s.tasks.filter(t=>t.status==="Ready"||t.status==="Running").length;
  const mirLive=Object.values(s.bridge.mirrored||{}).filter(v=>v&&v!=="DRY").length;
  // effective sizing book: a $2k override means the bot trades small on the big
  // paper account. Show it so the equity headline can't mislead.
  const book=(s.broker==="alpaca"&&s.settings&&+s.settings.alpaca_sizing_equity>0)
    ? +s.settings.alpaca_sizing_equity : null;
  const perPos=book?book*((+((s.settings||{}).sizing_pct)||0)/100):null;
  const tileList=[
    ["Equity ("+(s.broker==="alpaca"?"Alpaca":"Webull sim")+")",fmt$(eq),
      d==null?"":`<span class="${d>=0?'up':'down'}">${d>=0?"▲":"▼"} ${fmt$(Math.abs(d))} vs start</span>`]];
  if(book) tileList.push(["Trading book (sizing)",fmt$(book),
      `~${fmt$(perPos)}/position · real balance untouched`]);
  tileList.push(
    ["Buying power",fmt$(s.buying_power),""],
    ["Open positions",pos+dpos,`${pos} intraday · ${dpos} daily`],
    ["Queued entries",Object.keys(s.daily_pending).length,"fill at next open"],
    ["Events today",evToday,""],
    ["Tasks ready",ready+"/"+s.tasks.length,""],
    ["Webull mirrors",mirLive,"live paper orders"]);
  $("#tiles").innerHTML=tileList.map(([l,v,sub])=>`<div class="card tile"><div class="lbl">${l}</div><div class="val">${v}</div><div class="sub">${sub}</div></div>`).join("");
}

function posTable(s){
  const P=s.positions_live||[], R=s.risk||{};
  let html="";
  if(P.length){
    html+=`<div class="scroll"><table><tr><th>Symbol</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Now</th><th class="num">Unreal.</th><th>Stop → Target</th><th class="num">Target</th></tr>`+
      P.map(p=>{
        const bar = p.frac==null ? `<span class="muted" style="font-size:12px">—</span>`
          : `<div class="distbar" title="stop ${p.stop} · target ${p.target}"><div class="mk" style="left:${(p.frac*100).toFixed(0)}%"></div></div>`;
        return `<tr><td><span class="sym">${esc(p.symbol)}</span> <span style="color:var(--muted);font-size:11px">${esc(p.kind)}${p.be?" · BE":""}</span></td>
          <td class="num">${p.qty}</td><td class="num">${p.entry.toFixed(2)}</td>
          <td class="num">${p.price!=null?p.price.toFixed(2):"—"}</td>
          <td class="num ${p.unreal==null?'':(p.unreal>=0?'up':'down')}">${p.unreal==null?"—":fmt$(p.unreal)}</td>
          <td style="min-width:110px">${bar}</td>
          <td class="num">${p.target.toFixed(2)}</td></tr>`;
      }).join("")+`</table></div>`;
    html+=`<div style="font-size:12px;color:var(--muted);margin-top:8px">
      At risk <b style="color:var(--ink)">${fmt$(R.total_risk)}</b> (${R.pct_of_book!=null?R.pct_of_book+"%":"—"} of book) ·
      slots ${R.slots_used}/${R.slots_max} ·
      unrealized <span class="${(R.unreal_total||0)>=0?'up':'down'}">${fmt$(R.unreal_total)}</span></div>`;
  } else {
    const realN=(s.real_account&&s.real_account.positions||[]).length;
    html=`<div class="empty">The bot has no open practice positions yet.${realN?` Your ${realN} real position${realN>1?"s":""} show${realN>1?"":"s"} in the green “Real Webull account” card above.`:""}</div>`;
  }
  const q=Object.entries(s.daily_pending||{});
  const scRows=(s.scanner&&s.scanner.rows)||[];
  const affOf=sym=>{const r=scRows.find(x=>x.symbol===sym);return r?r.affordable:null;};
  if(q.length) html+=`<div style="margin-top:10px"><div class="scroll"><table><tr><th>Queued (next open)</th><th class="num">Ref</th><th class="num">Stop</th><th class="num">Target</th><th>Fill date</th><th>Will fill?</th></tr>`+
    q.map(([k,v])=>{
      const aff=affOf(k);
      const cell = aff===false ? `<span class="no">⚠ skips (too pricey)</span>`
        : aff===true ? `<span class="yes">✓ yes</span>` : `<span class="muted">—</span>`;
      return `<tr><td><span class="sym">${esc(k)}</span></td><td class="num">${(+v.ref).toFixed(2)}</td><td class="num">${(+v.sl).toFixed(2)}</td><td class="num">${(+v.tp).toFixed(2)}</td><td>${esc(v.fill_date)}</td><td style="font-size:12px">${cell}</td></tr>`;
    }).join("")+`</table></div></div>`;
  $("#positions").innerHTML=html;
}

function backtest(s){
  const b=s.backtest;
  if(!b){ $("#backtest").innerHTML=`<div class="empty">No backtest yet — run <code>py run_month_backtest.py</code>.</div>`; return; }
  const mini=(l,v,sub,cls)=>`<div class="card tile"><div class="lbl">${l}</div><div class="val ${cls||''}">${v}</div><div class="sub">${sub||''}</div></div>`;
  const net=b.net||0;
  let warn="";
  if(b.sizing_warning) warn+=`<div id="banner" class="warn" style="display:block;position:static;margin:0 0 10px">▲ ${esc(b.sizing_warning)}</div>`;
  else if(b.blocker) warn+=`<div class="empty" style="margin-bottom:10px">${esc(b.blocker)}</div>`;
  let html=warn+`<div style="font-size:12px;color:var(--muted);margin-bottom:8px">
    ${esc(b.engine)} · ${esc((b.symbols||[]).join(", "))} · last ${b.window_days} days · book ${fmt$(b.book)} @ ${b.sizing_pct}% (${fmt$(b.per_trade_budget)}/trade) · as of ${esc(b.as_of)}</div>
    <div class="tiles" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">
    ${mini("Profit (1mo)",fmt$(net),"whole-share, live rule",net>0?"up":(net<0?"down":""))}
    ${mini("Sim equity",fmt$(b.sim_equity),"from "+fmt$(b.book),b.sim_equity>=b.book?"up":"down")}
    ${mini("Signals",b.trades_signaled??0,(b.trades_untakeable?b.trades_untakeable+" un-takeable":""))}
    ${mini("Takeable",b.trades_takeable??0,"actually placeable")}
    ${mini("Win rate",b.win_rate==null?"—":b.win_rate.toFixed(0)+"%",b.trades_takeable?`${b.wins}/${b.trades_takeable}`:"")}
  </div>`;
  const d=b.detail||[];
  if(d.length){
    html+=`<table style="margin-top:10px"><tr><th>Signal date</th><th>Symbol</th><th>Outcome</th><th class="num">Entry</th><th class="num">Exit</th><th class="num">Per share</th><th class="num">Shares</th><th class="num">P/L</th></tr>`+
      d.map(t=>`<tr><td style="font-size:12px">${esc(t.entry_date)}</td><td><span class="sym">${esc(t.symbol)}</span></td>
        <td style="font-size:12px">${t.open?"open":esc(t.reason)}</td>
        <td class="num">${(+t.entry).toFixed(2)}</td><td class="num">${(+t.exit).toFixed(2)}</td>
        <td class="num ${t.per_share>=0?'up':'down'}">${fmt$(t.per_share)}</td>
        <td class="num">${t.takeable?t.qty_live:"0 ✕"}</td>
        <td class="num ${t.pnl_live>=0?'up':'down'}">${fmt$(t.pnl_live)}</td></tr>`).join("")+`</table>`;
  }
  html+=`<div style="font-size:11px;color:var(--muted);margin-top:8px">${esc(b.note||"")}</div>`;
  $("#backtest").innerHTML=html;
}

function progress(s){
  const p=s.progress||{};
  const base=(s.equity!=null)?s.equity:2000;   // Webull-sim book size
  const net=p.net||0, sim=base+net;
  const pfTxt = p.pf==null ? (p.closed&&net>0?"∞":"—") : (+p.pf).toFixed(2);
  const mini=(l,v,sub,cls)=>`<div class="card tile"><div class="lbl">${l}</div><div class="val ${cls||''}">${v}</div><div class="sub">${sub||''}</div></div>`;
  let html=`<div class="tiles" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">
    ${mini("Closed trades",p.closed??0,p.open_now?`${p.open_now} open now`:"none open")}
    ${mini("Win rate",p.win_rate==null?"—":p.win_rate.toFixed(0)+"%",p.closed?`${p.wins}/${p.closed}`:"")}
    ${mini("Profit factor",pfTxt,"")}
    ${mini("Net P/L",fmt$(net),"at logged levels",net>=0?"up":"down")}
    ${mini("Sim equity",fmt$(sim),"started "+fmt$(base),sim>=base?"up":"down")}
  </div>`;
  if(p.recent&&p.recent.length){
    html+=`<table style="margin-top:10px"><tr><th>Closed</th><th>Symbol</th><th>Track</th><th class="num">Entry</th><th class="num">Exit</th><th>Type</th><th class="num">P/L</th></tr>`+
      p.recent.map(t=>`<tr><td style="font-size:12px;color:var(--muted)">${esc((t.ts||"").slice(5,16).replace("T"," "))}</td>
        <td><span class="sym">${esc(t.symbol)}</span></td><td style="font-size:12px">${esc(t.track)}</td>
        <td class="num">${(+t.entry).toFixed(2)}</td><td class="num">${(+t.exit).toFixed(2)}</td>
        <td style="font-size:12px">${esc(t.exit_ev)}</td>
        <td class="num ${t.pnl>=0?'up':'down'}">${fmt$(t.pnl)}</td></tr>`).join("")+`</table>`;
  } else {
    html+=`<div class="empty">No closed trades yet on this run. When the bot exits a position (stop or 3R target), it shows here with its P/L, and Sim equity moves off $${(base).toLocaleString()}.</div>`;
  }
  $("#progress").innerHTML=html;
}

function taskTable(s){
  $("#tasks").innerHTML=`<table>`+s.tasks.map(t=>{
    const on=t.status==="Ready"||t.status==="Running";
    const col=t.status==="Running"?"var(--series1)":on?"var(--good)":t.status==="Disabled"?"var(--warn)":"var(--crit)";
    return `<tr><td><span class="chip"><span class="dot" style="background:${col}"></span>${esc(t.name.replace("SwingPro_",""))}</span></td>
      <td style="font-size:12px">${esc(t.status)}</td>
      <td style="font-size:12px;color:var(--muted)">${esc(t.next_run)}</td>
      <td class="num"><button data-task="${esc(t.name)}" data-enable="${!on}">${on?"Pause":"Resume"}</button></td></tr>`;
  }).join("")+`</table>`;
}

function events(s){
  $("#events").innerHTML = s.events.length ? `<table>`+s.events.map(e=>{
    const [col,icon]=EV_CLASS(e.event||"");
    return `<tr><td style="white-space:nowrap;font-size:12px">${esc((e.ts||"").replace("T"," "))}</td>
      <td><span class="chip" style="color:${col}">${icon} ${esc(e.event)}</span></td>
      <td><span class="sym">${esc(e.symbol)}</span></td>
      <td class="num">${esc(e.qty)}</td><td class="num">${e.ref_price?(+e.ref_price).toFixed(2):""}</td>
      <td style="font-size:12px;color:var(--muted)">${esc(e.detail)}</td></tr>`;
  }).join("")+`</table>` : `<div class="empty">No events logged yet.</div>`;
}

function mirror(s){
  const b=s.bridge, m=Object.entries(b.mirrored||{});
  let html=`<div style="font-size:12px;color:var(--muted);margin-bottom:6px">
    account ${esc(b.account||"not linked")} · last run ${esc(b.last_run?b.last_run.slice(0,19).replace("T"," "):"never")}</div>`;
  html += m.length ? `<table><tr><th>Alpaca order</th><th>Webull mirror</th></tr>`+
    m.map(([a,w])=>`<tr><td style="font-family:Consolas,monospace;font-size:12px">${esc(a.slice(0,13))}…</td>
      <td>${w==="DRY"?`<span class="chip" style="color:var(--warn)">▲ dry-logged</span>`:`<span class="chip" style="color:var(--good)">● ${esc(String(w).slice(0,13))}…</span>`}</td></tr>`).join("")+`</table>`
    : `<div class="empty">Nothing mirrored yet.</div>`;
  if(s.webull_orders.length) html+=`<div style="margin-top:10px"><table><tr><th>Time</th><th>Action</th><th>Sym</th><th class="num">Qty</th><th>Sent</th></tr>`+
    s.webull_orders.map(o=>`<tr><td style="font-size:12px">${esc((o.ts||"").slice(5,16).replace("T"," "))}</td>
      <td style="font-size:12px">${esc(o.action)}</td><td><span class="sym">${esc(o.symbol)}</span></td>
      <td class="num">${esc(o.qty)}</td><td style="font-size:12px">${o.dry_run==="True"?"dry-run":"HTTP "+esc(o.http_status)}</td></tr>`).join("")+`</table></div>`;
  $("#mirror").innerHTML=html;
}

function spot(s){
  const d=s.spotlight; if(!d){ $("#spot").innerHTML=""; return; }
  const chg=d.change_ratio!=null?d.change_ratio*100:null;
  const sigCol = d.signal==="BUY TRIGGERED" ? "var(--good)"
    : d.signal==="setup forming" ? "var(--warn)" : "var(--muted)";
  const sigIcon = d.signal==="BUY TRIGGERED" ? "●"
    : d.signal==="setup forming" ? "◐" : "○";
  const foc=(s.settings&&s.settings.focus_symbols)||[];
  const focused = foc.map(x=>x.toUpperCase()).includes((d.symbol||"").toUpperCase());
  $("#spot").innerHTML=`<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
    <div style="font-size:22px;font-weight:700">${esc(d.symbol)}</div>
    <div style="font-size:22px;font-weight:650;font-variant-numeric:tabular-nums">${d.price!=null?fmt$(d.price):"—"}</div>
    ${chg!=null?`<div class="${chg>=0?'up':'down'}" style="font-size:14px;font-weight:600">${chg>=0?"▲":"▼"} ${Math.abs(chg).toFixed(2)}%</div>`:""}
    <div class="chip" style="color:${sigCol};font-size:14px;font-weight:600">${sigIcon} ${esc(d.signal||"signal loading…")}${d.signal?` <span style="color:var(--muted);font-weight:400">(${esc(d.timeframe||"daily")})</span>`:""}</div>
    <div style="font-size:12px;color:var(--muted)">${esc(d.detail||"")}</div>
    <span style="flex:1"></span>
    <div class="chip" style="font-size:12px;color:${focused?'var(--good)':'var(--muted)'}">
      ${focused?"● bot is focused on this symbol":"○ bot trading full baskets"}</div>
  </div>`;
}

let settingsDirty=false;
function settings(s){
  if(settingsDirty) return;                 // don't clobber fields mid-edit
  const c=s.settings||{};
  const set=(id,v)=>{const el=$(id); if(el&&document.activeElement!==el) el.value=v;};
  set("#set_sizing_pct",c.sizing_pct);
  set("#set_max_positions",c.max_positions);
  set("#set_max_notional_usd",c.max_notional_usd);
  set("#set_daily_loss_limit_usd",c.daily_loss_limit_usd);
  set("#set_webull_sizing_equity",c.webull_sizing_equity);
  set("#set_alpaca_sizing_equity",c.alpaca_sizing_equity);
  set("#set_focus_symbols",(c.focus_symbols||[]).join(", "));
  const ti=$("#trk_intraday"), td=$("#trk_daily");
  if(document.activeElement!==ti) ti.checked=!!(c.tracks&&c.tracks.intraday);
  if(document.activeElement!==td) td.checked=!!(c.tracks&&c.tracks.daily);
  $("#wbeq_wrap").style.display = s.broker==="webull" ? "" : "none";
  $("#alpeq_wrap").style.display = s.broker==="alpaca" ? "" : "none";
  const L=s.locked_strategy||{};
  $("#locked").innerHTML = Object.keys(L).length
    ? `<table>`+Object.entries(L).map(([k,v])=>`<tr><td style="color:var(--muted)">${esc(k)}</td><td class="sym">${esc(v)}</td></tr>`).join("")+`</table>` : "";
}

async function saveSettings(){
  const num=id=>parseFloat($(id).value);
  const body={action:"settings", settings:{
    sizing_pct:num("#set_sizing_pct"), max_positions:num("#set_max_positions"),
    max_notional_usd:num("#set_max_notional_usd"),
    daily_loss_limit_usd:num("#set_daily_loss_limit_usd"),
    webull_sizing_equity:num("#set_webull_sizing_equity"),
    alpaca_sizing_equity:num("#set_alpaca_sizing_equity"),
    focus_symbols:$("#set_focus_symbols").value,
    tracks:{intraday:$("#trk_intraday").checked, daily:$("#trk_daily").checked}
  }};
  const r=await (await fetch("/api/action",{method:"POST",body:JSON.stringify(body)})).json();
  settingsDirty=false;
  $("#setmsg").textContent = r.ok ? "✓ saved — live next tick" : "✗ "+(r.output||"failed");
  refresh();
}

function realAccount(s){
  const r=s.real_account||{};
  if(r.error){ $("#real").innerHTML=`<div class="empty" style="color:var(--warn)">▲ ${esc(r.error)}</div>`; return; }
  const plTot=(r.positions||[]).reduce((a,p)=>a+(p.pl||0),0);
  let html=`<div class="tiles" style="grid-template-columns:repeat(auto-fit,minmax(130px,1fr))">
    <div class="card tile"><div class="lbl">Net liquidation</div><div class="val">${fmt$(r.net_liq)}</div></div>
    <div class="card tile"><div class="lbl">Cash</div><div class="val">${fmt$(r.cash)}</div></div>
    <div class="card tile"><div class="lbl">Buying power</div><div class="val">${fmt$(r.buying_power)}</div></div>
    <div class="card tile"><div class="lbl">Open P/L</div><div class="val ${plTot>=0?'up':'down'}">${fmt$(plTot)}</div></div>
  </div>`;
  html += (r.positions&&r.positions.length)
    ? `<table style="margin-top:10px"><tr><th>Symbol</th><th class="num">Qty</th><th class="num">Cost</th><th class="num">Last</th><th class="num">Unreal. P/L</th><th></th></tr>`+
      r.positions.map(p=>`<tr><td><span class="sym">${esc(p.symbol)}</span></td><td class="num">${p.qty}</td>
        <td class="num">${p.cost.toFixed(2)}</td><td class="num">${p.last.toFixed(2)}</td>
        <td class="num ${p.pl>=0?'up':'down'}">${fmt$(p.pl)}</td>
        <td class="num"><button class="danger" data-close="${esc(p.symbol)}" data-qty="${p.qty}">Sell all</button></td></tr>`).join("")+`</table>
        <div style="font-size:11px;color:var(--muted);margin-top:6px">“Sell all” places a market order to close the position on your real account — you confirm before it sends.</div>`
    : `<div class="empty" style="margin-top:8px">No open positions on the real account.</div>`;
  $("#real").innerHTML=html;
}

function chart(s){
  // Webull mode: show the sim-equity curve (starts at the book, moves on each
  // closed trade). Never fall back to the Alpaca $100k history here — that would
  // contradict the $2,000 framing. Alpaca mode keeps its portfolio history.
  const svg=$("#chart"), tip=$("#tip");
  const H = s.broker==="webull" ? ((s.sim_curve||[]).length>=2 ? s.sim_curve : []) : (s.equity_history||[]);
  const W=svg.clientWidth||900, Hh=190, padL=58, padR=12, padT=10, padB=22;
  svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  if(H.length<2){svg.innerHTML=`<text x="12" y="24" fill="var(--muted)" font-size="13">${s.broker==="webull"?"No closed trades yet — the equity line begins on the first exit.":"No history available."}</text>`;return;}
  const eqs=H.map(p=>p.eq), lo=Math.min(...eqs), hi=Math.max(...eqs), pad=(hi-lo)*0.15||100;
  const y=v=>padT+(Hh-padT-padB)*(1-(v-(lo-pad))/((hi+pad)-(lo-pad)));
  const x=i=>padL+(W-padL-padR)*i/(H.length-1);
  let g="";
  const steps=4, span=(hi+pad)-(lo-pad);
  const fmtAx=v=> span<3000 ? "$"+Math.round(v).toLocaleString()
    : span<30000 ? (v/1000).toFixed(1)+"k" : Math.round(v/1000)+"k";
  for(let k=0;k<=steps;k++){
    const v=(lo-pad)+span*k/steps, yy=y(v);
    g+=`<line x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}" stroke="var(--grid)" stroke-width="1"/>
        <text x="${padL-8}" y="${yy+4}" text-anchor="end" fill="var(--muted)" font-size="11" style="font-variant-numeric:tabular-nums">${fmtAx(v)}</text>`;
  }
  const pts=H.map((p,i)=>`${x(i)},${y(p.eq)}`).join(" ");
  const area=`${padL},${y(lo-pad)} ${pts} ${W-padR},${y(lo-pad)}`;
  g+=`<polygon points="${area}" fill="var(--series1)" opacity="0.10"/>`;
  g+=`<polyline points="${pts}" fill="none" stroke="var(--series1)" stroke-width="2" stroke-linejoin="round"/>`;
  const n=Math.max(1,Math.floor(H.length/6));
  H.forEach((p,i)=>{if(i%n===0)g+=`<text x="${x(i)}" y="${Hh-6}" text-anchor="middle" fill="var(--muted)" font-size="11">${p.t}</text>`;});
  g+=`<line id="xh" y1="${padT}" y2="${Hh-padB}" stroke="var(--axis)" stroke-width="1" visibility="hidden"/>
      <circle id="xdot" r="4" fill="var(--series1)" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>`;
  svg.innerHTML=g;
  svg.onmousemove=ev=>{
    const r=svg.getBoundingClientRect(), mx=(ev.clientX-r.left)*(W/r.width);
    const i=Math.max(0,Math.min(H.length-1,Math.round((mx-padL)/((W-padL-padR)/(H.length-1)))));
    const p=H[i], xx=x(i), yy=y(p.eq);
    const xh=$("#xh"), xd=$("#xdot");
    xh.setAttribute("x1",xx); xh.setAttribute("x2",xx); xh.setAttribute("visibility","visible");
    xd.setAttribute("cx",xx); xd.setAttribute("cy",yy); xd.setAttribute("visibility","visible");
    tip.style.display="block"; tip.style.left=(ev.clientX+14)+"px"; tip.style.top=(ev.clientY-10)+"px";
    tip.innerHTML=`<b>${p.t}</b> · ${fmt$(p.eq)}`;
  };
  svg.onmouseleave=()=>{tip.style.display="none";$("#xh").setAttribute("visibility","hidden");$("#xdot").setAttribute("visibility","hidden");};
}

let lastEventKey=null, notifyReady=false;
function keyOf(e){ return (e.ts||"")+"|"+(e.event||"")+"|"+(e.symbol||""); }

function control(s){
  const c=s.control||{};
  const g=$("#gate"), dot=g.querySelector(".dot"), txt=g.querySelector("span:last-child");
  if(c.halted){ dot.style.background="var(--crit)"; txt.textContent="HALTED"; }
  else if(!c.entries_allowed){ dot.style.background="var(--warn)"; txt.textContent="Entries paused"; }
  else { dot.style.background="var(--good)"; txt.textContent="Entries live"; }
  $("#gatereason").textContent = c.reason && c.reason!=="ok" ? c.reason
    : (c.observer ? `observer on · heartbeat ${c.heartbeat_age_min==null?"—":c.heartbeat_age_min.toFixed(1)+"m"} ago` : "");
  const obs=$("#obs"); if(document.activeElement!==obs) obs.checked=!!c.observer;
  const b=$("#banner");
  const errs=s.events.filter(e=>/ERROR/.test(e.event||"")).slice(0,1);
  if(c.halted){ b.style.display="block"; b.className=""; b.textContent="■ KILL SWITCH ACTIVE — bot halted, positions flattened, tick task disabled. Click Resume to re-arm."; }
  else if(errs.length){ b.style.display="block"; b.className="warn"; b.textContent="▲ "+errs[0].event+" ("+errs[0].symbol+"): "+(errs[0].detail||"")+" — "+errs[0].ts; }
  else b.style.display="none";
}

function notifyNew(s){
  if(!s.events.length) return;
  const newest=s.events[0], k=keyOf(newest);
  if(lastEventKey===null){ lastEventKey=k; return; }      // don't fire on first load
  if(k===lastEventKey) return;
  lastEventKey=k;
  const ev=newest.event||"";
  const isAlert=/ERROR/.test(ev), isOrder=/BUY|STOP|TARGET|TP1|FLATTEN|BREAKEVEN|TREND_EXIT/.test(ev);
  if(!(isAlert||isOrder)) return;
  if(notifyReady){
    new Notification((isAlert?"⚠ ":"● ")+"iAPE "+ev,
      {body:`${newest.symbol||""} ${newest.qty||""}  ${newest.detail||""}`.trim()});
  }
}

async function refresh(){
  const s=await (await fetch("/api/state")).json();
  $("#venue span:last-child").textContent=s.venue;
  const mk=$("#mkt");
  mk.querySelector(".dot").style.background=s.market_open?"var(--good)":"var(--muted)";
  mk.querySelector("span:last-child").textContent=s.market_open?"Market open":"Market closed";
  $("#updated").textContent="updated "+s.generated+(s.account_error?" · acct err":"");
  const useSim = s.broker==="webull" && (s.sim_curve||[]).length>=2;
  $("#charttitle").textContent = useSim
    ? "Sim equity — this run (started $2,000, realized)"
    : s.broker==="webull"
    ? "Equity — no closed trades yet (curve starts once it trades)"
    : "Equity — Alpaca paper, last month";
  const br=$('button[data-act="bridge"]'); if(br) br.style.display = s.broker==="webull" ? "none" : "";
  control(s); notifyNew(s); settings(s); spot(s); health(s); statusline(s);
  tiles(s); scannerTable(s); backtest(s); verdictBar(s); progress(s);
  realAccount(s); posTable(s); taskTable(s); events(s); mirror(s); chart(s);
}

// mark the settings form dirty so live refreshes don't overwrite your typing
$("#settingscard").addEventListener("input",()=>{settingsDirty=true;});

document.addEventListener("click",async ev=>{
  const b=ev.target.closest("button"); if(!b)return;
  if(b.id==="savebtn"){ b.disabled=true; await saveSettings(); b.disabled=false; return; }
  if(b.dataset.close){
    const sym=b.dataset.close, qty=b.dataset.qty;
    if(!confirm(`Sell ALL ${qty} shares of ${sym} at market on your REAL Webull account?\n\nThis is real money and cannot be undone once filled.`)) return;
    b.disabled=true; b.textContent="selling…";
    try{
      const r=await (await fetch("/api/action",{method:"POST",body:JSON.stringify({action:"close_position",symbol:sym,confirm:"SELL "+sym})})).json();
      $("#toast").textContent=(r.ok?"✓ ":"✗ ")+(r.output||"");
    }catch(e){$("#toast").textContent="✗ "+e;}
    b.disabled=false; refresh(); return;
  }
  if(b.dataset.act==="kill" && !confirm("KILL SWITCH: halt the bot, market-sell EVERY open position, and disable the tick task. Proceed?")) return;
  b.disabled=true;
  const body=b.dataset.act?{action:b.dataset.act}
    :{action:"task",task:b.dataset.task,enable:b.dataset.enable==="true"};
  try{
    const r=await (await fetch("/api/action",{method:"POST",body:JSON.stringify(body)})).json();
    $("#toast").textContent=(r.ok?"✓ ":"✗ ")+(r.output||"(no output)");
  }catch(e){$("#toast").textContent="✗ "+e;}
  b.disabled=false; refresh();
});

$("#obs").addEventListener("change",async e=>{
  await fetch("/api/action",{method:"POST",
    body:JSON.stringify({action:"observer",enable:e.target.checked})});
  refresh();
});

// notifications: use the grant if we already have it; otherwise wait for a
// user gesture (the "Enable alerts" button / observer toggle) — never prompt on
// load, since a modal permission dialog would block the page.
if("Notification" in window && Notification.permission==="granted") notifyReady=true;
$("#alertsbtn").addEventListener("click",()=>{
  if(!("Notification" in window)){ $("#toast").textContent="this browser has no notifications"; return; }
  Notification.requestPermission().then(p=>{
    notifyReady = p==="granted";
    $("#toast").textContent = notifyReady ? "✓ desktop alerts enabled"
      : "✗ alerts blocked (allow notifications for this site)";
  });
});

refresh(); setInterval(refresh,30000);
</script></body></html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    threading.Thread(target=_scanner_loop, daemon=True).start()   # live watchlist
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}"
    print(f"iAPE dashboard: {url}  (Ctrl+C to stop)")
    if not a.no_open:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
