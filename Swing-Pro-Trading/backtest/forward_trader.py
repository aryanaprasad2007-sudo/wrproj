"""
forward_trader.py — the paper-trading FORWARD TEST for iAPE (formerly SWING_PRO) long-only.

This is variant B live: decisions on closed 5m bars, exits checked at 1m
resolution — the best configuration the 2-year backtests validated (PF 1.10).
Signals come from the SAME compute_signals() the backtest harness uses, so
there is zero logic drift between what was tested and what trades.

Since 2026-07-06 this loop also carries the DAILY track (iAPE-D, the
30y-validated flagship candidate): daily_signals.py queues post-close signals
on the disjoint control basket; each tick fills due entries at the open and
manages their pure stop + 3R exits at 1m resolution (DAILY_* log events).

SAFETY: orders go ONLY to https://paper-api.alpaca.markets (hardcoded).
Paper = simulated money. This script cannot touch a live account.

Modes:
  py forward_trader.py --once     one tick: check exits, process new 5m closes
                                  (this is what the scheduled task runs each minute)
  py forward_trader.py --report   write/refresh the forward-test report
  py forward_trader.py --status   print positions & account snapshot

Data feed: IEX (free real-time). v2 uses no volume gates, so IEX's thin volume
doesn't affect signals; prices may differ from SIP by pennies — that's part of
what a forward test is for. Not financial advice.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

from data import _env, NY
from swing_pro import config_v22, compute_signals
import broker   # execution venue: SWINGPRO_BROKER=alpaca (default) | webull
import control  # kill switch / observer dead-man gate for NEW entries
import botconfig  # live operator settings (sizing, caps, tracks, loss limit)

PAPER = "https://paper-api.alpaca.markets"      # hardcoded: paper ONLY
DATA = "https://data.alpaca.markets"
# Two baskets forward-tested side by side (2026-07-02, universe-scan decision):
#   current  = the original Big Tech 5 (benchmark PF 1.30 from the 2y backtest)
#   candidate = universe-scan H1 top-5, H2-validated (H2 PF 1.40; MSTR flagged weak)
# The Friday review scores each basket separately — the forward test is the judge.
BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META",
          "MSTR", "ORCL", "NFLX", "AVGO", "CRWD"]
# DAILY track (iAPE-D, live 2026-07-06): the 30y-validated daily engine
# paper-trades the survivorship CONTROL basket — 13 names with zero overlap
# with the intraday 10, so both experiments share one account without
# collisions. daily_signals.py (13:05 PT, post-close) queues entries in state
# ("daily_pending"); this loop fills them at the next open and manages the
# pure stop + 3R target at 1m resolution. Pre-registered benchmark:
# control-basket H2 2021-26 = PF 1.72, ~0.4 trades/wk.
DAILY_BASKET = ["JPM", "GS", "XOM", "CVX", "CAT", "DE", "BA",
                "WMT", "COST", "HD", "UNH", "DIS", "KO"]
HERE = Path(__file__).parent
STATE_F = HERE / "forward_state.json"
LOG_F = HERE / "forward_log.csv"
REPORTS = HERE / "reports"
CFG = config_v22(trade_dir="long")   # v2.2: pure stop + 3R target (exit-sweep winner)
# STRICT shadow config — same 7 indicators, tighter thresholds. NOT traded: its
# signals are logged hypothetically (SHADOW_* events) so live prices can score a
# higher-win-rate variant without touching the real experiment or the retired
# backtest dataset. Promotion requires it to beat live v2.2 on real forward data.
STRICT_CFG = config_v22(trade_dir="long", adx_min=25, slope_min_atr=0.30,
                        rsi_long_level=55)
# v2.2-D: local daily EMA50 regime (no HTF bucketing on a daily chart)
CFG_D = config_v22(trade_dir="long", use_htf_trend=False)


def daily_universe(bc=None):
    """Symbols the DAILY (flagship) track scans/trades: the validated control
    basket PLUS any operator focus symbols not already in it. Focusing on AAPL
    therefore routes AAPL to the daily engine (which has ample data and the 30y
    validation), and the intraday track skips anything in this set so no symbol
    is ever owned by both tracks on one account (the original disjoint-basket
    invariant, preserved dynamically)."""
    bc = bc or botconfig.load()
    extra = [s for s in (bc.get("focus_symbols") or []) if s not in DAILY_BASKET]
    return list(DAILY_BASKET) + extra


def _headers():
    return {"APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
            "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY"),
            "Content-Type": "application/json"}


def _get(base, path, **q):
    """GET with a short retry/backoff on transient network resets.

    WinError 10054 ("connection forcibly closed by the remote host") and kindred
    keep-alive drops are common against a data feed polled every minute — the
    remote closes an idle socket between calls. One quiet retry almost always
    succeeds, which stops these blips from spamming TICK_ERROR and tripping the
    dashboard's health light. A genuine outage still raises after 3 tries."""
    url = base + path + ("?" + urllib.parse.urlencode(q) if q else "")
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, OSError) as e:
            last = e
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))     # 0.5s, then 1.0s
    raise last


def _post(path, payload):
    req = urllib.request.Request(PAPER + path, data=json.dumps(payload).encode(),
                                 headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def bars(symbol, timeframe, limit):
    """Intraday bars, IEX feed, RTH-only (09:30-16:00 ET) to match the data
    the engine was validated on (data._clean_rth). Explicit start is required
    — same Alpaca gotcha as daily_bars: without it the window defaults to
    today, capping any request at one session (~55 5m bars) regardless of
    limit. The raw request over-fetches 3x because IEX also returns
    extended-hours bars that the RTH filter then discards."""
    minutes = 5 if timeframe == "5Min" else 1
    sessions = (limit * minutes) / 390 + 1          # 390 RTH minutes per day
    start = (datetime.now()
             - pd.Timedelta(days=sessions * 1.6 + 5)).strftime("%Y-%m-%d")
    js = _get(DATA, f"/v2/stocks/{symbol}/bars", timeframe=timeframe,
              limit=min(limit * 3, 10000), feed="iex", sort="desc", start=start)
    rows = list(reversed(js.get("bars") or []))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).rename(columns={"t": "time", "o": "open", "h": "high",
                                            "l": "low", "c": "close", "v": "volume"})
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(NY)
    df = df.set_index("time")[["open", "high", "low", "close", "volume"]]
    t = df.index.time
    df = df[(t >= dtime(9, 30)) & (t < dtime(16, 0))]
    # completed bars only (drop the currently-forming bar)
    now = pd.Timestamp.now(tz=NY)
    span = pd.Timedelta(minutes=minutes)
    return df[df.index + span <= now].tail(limit)


def daily_bars(symbol, limit=460):
    """Daily bars, IEX feed (same price universe the forward test trades on).
    No forming-bar drop — callers run after the close (daily_signals scan) or
    only need an ATR estimate (reconcile adoption). Explicit start is required:
    without it Alpaca defaults to today and returns zero daily bars."""
    start = (datetime.now() - pd.Timedelta(days=int(limit * 1.6) + 30)).strftime("%Y-%m-%d")
    js = _get(DATA, f"/v2/stocks/{symbol}/bars", timeframe="1Day",
              limit=limit, feed="iex", sort="desc", start=start)
    rows = list(reversed(js.get("bars") or []))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).rename(columns={"t": "time", "o": "open", "h": "high",
                                            "l": "low", "c": "close", "v": "volume"})
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(NY)
    return df.set_index("time")[["open", "high", "low", "close", "volume"]]


def load_state():
    st = json.loads(STATE_F.read_text()) if STATE_F.exists() else {}
    for k in ("positions", "last_bar", "daily_pending", "daily_positions",
              "daily_last_bar"):
        st.setdefault(k, {})
    return st


def save_state(st):
    STATE_F.write_text(json.dumps(st, indent=1, default=str))


LOG_FIELDS = ["ts", "event", "symbol", "qty", "ref_price", "stop", "target",
              "order", "detail"]


def log(**row):
    """Fixed-schema append so heterogeneous events can never misalign the CSV."""
    row = {"ts": datetime.now().isoformat(timespec="seconds"), **row}
    norm = {k: row.get(k, "") for k in LOG_FIELDS}
    hdr = not LOG_F.exists()
    pd.DataFrame([norm]).to_csv(LOG_F, mode="a", header=hdr, index=False)
    print("  LOG", {k: v for k, v in norm.items() if v != ""})


def order(symbol, qty, side):
    return broker.submit(symbol, int(qty), side)


# ──────────────────────────────────────────────────────────────────────────────
def reconcile(st):
    """State file vs actual account positions — reality wins, mismatches logged.
    Protects the forward test from order failures / missed ticks corrupting data.
    Covers both books: intraday ("positions") and the daily track ("daily_positions"),
    routed by basket membership (the baskets are disjoint by design)."""
    known = set(BASKET) | set(daily_universe())
    try:
        acct_pos = {p["symbol"]: float(p["qty"]) for p in broker.positions()
                    if p["symbol"] in known and p.get("side") == "long"}
    except Exception as e:
        log(event="RECONCILE_ERROR", symbol="-", detail=str(e)[:100])
        return
    for book in ("positions", "daily_positions"):
        for sym in list(st[book]):
            if sym not in acct_pos:
                log(event="RECONCILE_DROP", symbol=sym,
                    detail=f"in state ({book}) but not in account - dropping")
                st[book].pop(sym)
            elif int(acct_pos[sym]) != int(st[book][sym]["qty"]):
                ours, actual = int(st[book][sym]["qty"]), int(acct_pos[sym])
                if not broker.SUPPORTS_ADOPT and actual > ours:
                    # SHARED venue (Webull UAT): "reality wins" is WRONG upward.
                    # The account total includes other developers' shares, so an
                    # excess over what we bought is foreign — absorbing it would
                    # (a) inflate the position we think we own and (b) make the
                    # exit try to sell shares that are not ours. This is exactly
                    # how AAPL became 1538 on 2026-07-27 (our 1 + a foreign 1537)
                    # and how NVDA hit GENERATE_NEW_SHORT_POSITION on 2026-07-16.
                    # The untracked-symbol guard below does not cover this case:
                    # it only fires for symbols we hold NONE of.
                    seen = st.setdefault("foreign_excess_seen", {})
                    today_s = date.today().isoformat()
                    if seen.get(sym) != today_s:
                        seen[sym] = today_s
                        log(event="RECONCILE_FOREIGN_EXCESS", symbol=sym,
                            qty=actual - ours,
                            detail=f"account {actual} vs our {ours} - excess "
                                   f"is another dev's, keeping {ours}")
                elif actual <= 0:
                    log(event="RECONCILE_DROP", symbol=sym,
                        detail=f"account qty {actual} ({book}) - dropping")
                    st[book].pop(sym)
                else:
                    # shrinking is always honoured, on any venue: we can never
                    # sell more than the account actually holds.
                    log(event="RECONCILE_QTY", symbol=sym,
                        detail=f"state {ours} vs account {actual}")
                    st[book][sym]["qty"] = actual
    tracked = set(st["positions"]) | set(st["daily_positions"])
    for sym, q in acct_pos.items():
        if sym not in tracked and q >= 1:
            if not broker.SUPPORTS_ADOPT:
                # shared Webull UAT account: an untracked holding may belong to
                # another developer — never fold it into our books. Log once
                # per symbol per day, not every minute tick.
                seen = st.setdefault("foreign_seen", {})
                today_s = date.today().isoformat()
                if seen.get(sym) != today_s:
                    seen[sym] = today_s
                    log(event="RECONCILE_FOREIGN", symbol=sym, qty=int(q),
                        detail="untracked on shared venue - ignored, not adopted")
                continue
            # untracked position (crash between order and state save) — adopt with
            # a protective volatility stop so it is never unmanaged
            try:
                p = broker.position(sym)
                entry = float(p["avg_entry_price"])
                if sym in daily_universe():
                    d1 = daily_bars(sym, 20)
                    atr_est = float((d1["high"] - d1["low"]).tail(14).mean()) if len(d1) else entry * 0.02
                    r = CFG_D.atr_stop_mult * atr_est
                    st["daily_positions"][sym] = {
                        "qty": int(q), "entry_ref": entry, "risk": r,
                        "sl": entry - r, "tp": entry + CFG_D.rr_ratio * r,
                        "entry_time": "adopted-by-reconcile", "signal_bar": ""}
                else:
                    m5 = bars(sym, "5Min", 20)
                    atr_est = float((m5["high"] - m5["low"]).tail(14).mean()) if len(m5) else entry * 0.005
                    r = CFG.atr_stop_mult * atr_est
                    st["positions"][sym] = {
                        "qty": int(q), "entry_ref": entry, "risk": r,
                        "sl": entry - r, "tp": entry + CFG.rr_ratio * r,
                        "be_done": False, "tp1_done": False,
                        "entry_time": "adopted-by-reconcile"}
                log(event="RECONCILE_ADOPT", symbol=sym, qty=int(q), ref_price=entry)
            except Exception as e:
                log(event="RECONCILE_ERROR", symbol=sym, detail=str(e)[:100])


def _at_position_cap(st, bc):
    """True if TOTAL open positions (both books) are at the operator's cap."""
    return len(st["positions"]) + len(st["daily_positions"]) >= bc["max_positions"]


def consume_daily_pending(st, equity, buying_power, entries_ok=True, bc=None):
    """Fill entries queued by daily_signals.py at this session's open (first
    open tick ~06:30 PT). Only on the exact fill_date — a pending whose window
    passed (machine off) is expired, because a late fill would drift from the
    backtest's next-open semantics. When entries_ok is False (halt/observer),
    pendings are LEFT QUEUED (not expired) so they fill once entries reopen."""
    if not entries_ok:
        return
    bc = bc or botconfig.load()
    today = date.today().isoformat()
    for sym, q in list(st["daily_pending"].items()):
        if q["fill_date"] > today:
            continue
        if q["fill_date"] < today:
            log(event="DAILY_EXPIRE", symbol=sym,
                detail=f"missed fill window {q['fill_date']}")
            st["daily_pending"].pop(sym)
            continue
        if not botconfig.in_focus(sym, bc):
            continue                          # leave queued; focus may widen later
        if _at_position_cap(st, bc):
            log(event="DAILY_SKIP", symbol=sym,
                detail=f"position cap {bc['max_positions']} reached")
            continue                          # leave queued; a slot may free up
        try:
            qty = int((bc["sizing_pct"] / 100.0) * equity / q["ref"])
            qty = botconfig.cap_qty(qty, q["ref"], bc)
            if qty < 1:
                log(event="DAILY_SKIP", symbol=sym, detail="qty < 1 share")
                st["daily_pending"].pop(sym)
                continue
            if qty * q["ref"] > buying_power:
                log(event="DAILY_SKIP", symbol=sym, qty=qty,
                    detail=f"insufficient buying power {buying_power:.0f}")
                st["daily_pending"].pop(sym)
                continue
            oid = order(sym, qty, "buy")
            st["daily_positions"][sym] = {
                "qty": qty, "entry_ref": q["ref"], "risk": q["risk"],
                "sl": q["sl"], "tp": q["tp"], "entry_time": today,
                "signal_bar": q.get("signal_bar", "")}
            st["daily_pending"].pop(sym)
            log(event="DAILY_BUY", symbol=sym, qty=qty, ref_price=q["ref"],
                stop=round(q["sl"], 2), target=round(q["tp"], 2), order=oid,
                detail=f"signal bar {q.get('signal_bar', '?')}")
        except Exception as e:
            log(event="DAILY_ERROR", symbol=sym, detail=str(e)[:120])
            st["daily_pending"].pop(sym, None)


def manage_daily_exits(st):
    """v2.2-D exits: pure stop + 3R target, nothing else (no BE/partial/trend).
    Static prices checked each minute; an open that gaps through the stop sells
    on the first 1m bar — realized fill vs stop reference IS the gap-risk data
    the Friday review measures."""
    for sym, pos in list(st["daily_positions"].items()):
        try:
            m1 = bars(sym, "1Min", 3)
            if not len(m1):
                continue
            hi, lo = float(m1["high"].iloc[-1]), float(m1["low"].iloc[-1])
            if lo <= pos["sl"]:  # stop wins any tie, same as the backtest
                oid = order(sym, pos["qty"], "sell")
                log(event="DAILY_STOP", symbol=sym, qty=pos["qty"],
                    ref_price=pos["sl"], order=oid)
                st["daily_positions"].pop(sym)
            elif hi >= pos["tp"]:
                oid = order(sym, pos["qty"], "sell")
                log(event="DAILY_TARGET", symbol=sym, qty=pos["qty"],
                    ref_price=pos["tp"], order=oid)
                st["daily_positions"].pop(sym)
        except Exception as e:
            log(event="TICK_ERROR", symbol=sym, detail=str(e)[:120])


def tick():
    if not broker.market_open():
        return
    st = load_state()
    reconcile(st)
    save_state(st)
    equity, buying_power = broker.account()
    bc = botconfig.load()                          # live operator settings
    # Capital base for position sizing. Real equity by default; if the operator
    # set alpaca_sizing_equity (e.g. 2000) the bot trades that small book on the
    # big paper account without touching the real balance or the forward-test
    # history. Buying-power checks below still use the REAL buying power.
    sizing_eq = botconfig.sizing_equity(equity, broker.BROKER, bc)

    # NEW-entry gate (kill switch / observer dead-man). Exits are NEVER gated.
    entries_ok, gate_reason = control.entries_allowed()

    # Daily loss limit: pause NEW entries once today is down the set $ amount.
    # Evaluated fresh each tick (day_open_equity resets daily), so it auto-clears
    # the next session; exits keep running.
    today_s = date.today().isoformat()
    if st.get("day_open_date") != today_s:
        st["day_open_date"] = today_s
        st["day_open_equity"] = equity
    limit = bc.get("daily_loss_limit_usd", 0) or 0
    day_pl = equity - st.get("day_open_equity", equity)
    if entries_ok and limit > 0 and day_pl <= -limit:
        entries_ok, gate_reason = False, (
            f"daily loss limit hit ({day_pl:.0f} <= -{limit:.0f}) — entries "
            f"paused for today")
    if not entries_ok:
        log(event="NEW_ENTRIES_BLOCKED", detail=gate_reason)

    # DAILY track first: exits free buying power before queued fills
    manage_daily_exits(st)
    if bc["tracks"].get("daily", True):
        consume_daily_pending(st, sizing_eq, buying_power, entries_ok, bc)
    save_state(st)

    spy5 = bars("SPY", "5Min", 900)
    dscan = set(daily_universe(bc))     # symbols the daily track owns this tick

    for sym in BASKET:
      try:  # one symbol's API hiccup must not kill the whole tick
        pos = st["positions"].get(sym)

        # ── 1) exit management at 1m resolution (variant B) ──────────────────
        if pos:
            m1 = bars(sym, "1Min", 3)
            if len(m1):
                hi, lo = float(m1["high"].iloc[-1]), float(m1["low"].iloc[-1])
                stop = pos["entry_ref"] if pos["be_done"] else pos["sl"]
                if hi >= pos["entry_ref"] + CFG.be_trigger_r * pos["risk"]:
                    pos["be_done"] = True
                if lo <= stop:
                    oid = order(sym, pos["qty"], "sell")
                    log(event="STOP" if not pos["be_done"] else "BREAKEVEN",
                        symbol=sym, qty=pos["qty"], ref_price=stop, order=oid)
                    st["positions"].pop(sym)
                    pos = None
                elif not pos["tp1_done"] and CFG.use_partial and \
                        hi >= pos["entry_ref"] + CFG.partial_r * pos["risk"]:
                    part = max(1, int(pos["qty"] * CFG.partial_pct / 100))
                    oid = order(sym, part, "sell")
                    pos["qty"] -= part
                    pos["tp1_done"] = True
                    log(event="TP1_PARTIAL", symbol=sym, qty=part, order=oid)
                elif hi >= pos["tp"]:
                    oid = order(sym, pos["qty"], "sell")
                    log(event="TARGET", symbol=sym, qty=pos["qty"],
                        ref_price=pos["tp"], order=oid)
                    st["positions"].pop(sym)
                    pos = None

        # ── 2) new closed 5m bar? -> full signal cycle ────────────────────────
        df5 = bars(sym, "5Min", 900)
        if len(df5) < 600 or len(spy5) < 600:
            continue
        last_ts = str(df5.index[-1])
        if st["last_bar"].get(sym) == last_ts:
            continue
        st["last_bar"][sym] = last_ts

        sig = compute_signals(df5, spy5, CFG)
        i = len(df5) - 1

        # ── STRICT shadow track (no orders — hypothetical scoring on live prices) ──
        sh = st.setdefault("shadow", {})
        sp = sh.get(sym)
        hi_k, lo_k = float(df5["high"].iloc[-1]), float(df5["low"].iloc[-1])
        if sp:  # conservative bar-level exit check: stop wins any tie
            if lo_k <= sp["sl"]:
                log(event="SHADOW_EXIT", symbol=sym, ref_price=sp["sl"],
                    detail=f"stop pps={sp['sl'] - sp['ref']:.4f}")
                sh.pop(sym)
                sp = None
            elif hi_k >= sp["tp"]:
                log(event="SHADOW_EXIT", symbol=sym, ref_price=sp["tp"],
                    detail=f"target pps={sp['tp'] - sp['ref']:.4f}")
                sh.pop(sym)
                sp = None
        if sp is None and sym not in sh:
            sigS = compute_signals(df5, spy5, STRICT_CFG)
            if sigS["go_long"][i]:
                atr_s, c_s = sigS["atr"][i], sigS["close"][i]
                raw_s = c_s - (sigS["swing_low"][i] - CFG.struct_buf_atr * atr_s)
                r_s = max(raw_s, CFG.atr_stop_mult * atr_s * 0.5) if (CFG.use_struct_stop and raw_s > 0) \
                    else CFG.atr_stop_mult * atr_s
                if not np.isnan(r_s) and r_s > 0:
                    sh[sym] = {"ref": float(c_s), "risk": float(r_s),
                               "sl": float(c_s - r_s),
                               "tp": float(c_s + CFG.rr_ratio * r_s),
                               "entry_time": last_ts}
                    log(event="SHADOW_BUY", symbol=sym, ref_price=c_s,
                        stop=round(c_s - r_s, 2),
                        target=round(c_s + CFG.rr_ratio * r_s, 2),
                        detail="strict-mode candidate")

        # trend exit on the 5m close
        if pos and CFG.exit_on_trend and sig["close"][i] < sig["trend_ma"][i]:
            oid = order(sym, pos["qty"], "sell")
            log(event="TREND_EXIT", symbol=sym, qty=pos["qty"],
                ref_price=sig["close"][i], order=oid)
            st["positions"].pop(sym)
            pos = None

        # entry (gated: halt / observer / daily-loss block NEW positions; the
        # intraday track toggle and the position cap also apply — exits above
        # always run so nothing is stranded)
        if (not pos and entries_ok and bc["tracks"].get("intraday", True)
                and botconfig.in_focus(sym, bc) and sym not in dscan
                and not _at_position_cap(st, bc) and sig["go_long"][i]):
            atr_i, c_i = sig["atr"][i], sig["close"][i]
            raw = c_i - (sig["swing_low"][i] - CFG.struct_buf_atr * atr_i)
            r = max(raw, CFG.atr_stop_mult * atr_i * 0.5) if (CFG.use_struct_stop and raw > 0) \
                else CFG.atr_stop_mult * atr_i
            qty = botconfig.cap_qty(int((bc["sizing_pct"] / 100.0) * sizing_eq / c_i),
                                    c_i, bc)
            if qty >= 1 and not np.isnan(r) and r > 0:
                oid = order(sym, qty, "buy")
                st["positions"][sym] = {
                    "qty": qty, "entry_ref": float(c_i), "risk": float(r),
                    "sl": float(c_i - r), "tp": float(c_i + CFG.rr_ratio * r),
                    "be_done": False, "tp1_done": False,
                    "entry_time": last_ts}
                log(event="BUY", symbol=sym, qty=qty, ref_price=c_i,
                    stop=round(c_i - r, 2), target=round(c_i + CFG.rr_ratio * r, 2),
                    order=oid)
      except Exception as e:
        log(event="TICK_ERROR", symbol=sym, detail=str(e)[:120])
    save_state(st)


# ──────────────────────────────────────────────────────────────────────────────
def report():
    REPORTS.mkdir(exist_ok=True)
    lg = pd.read_csv(LOG_F) if LOG_F.exists() else pd.DataFrame()
    st = load_state()
    out = REPORTS / "forward_test.md"
    eq, _bp = broker.account()
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# iAPE forward test (paper) — updated {date.today().isoformat()}\n\n")
        f.write(f"Account equity: **${eq:,.2f}**  ·  open intraday: "
                f"{len(st['positions'])}  ·  open daily: {len(st['daily_positions'])}"
                f"  ·  logged events: {len(lg)}\n\n")
        if len(st["positions"]):
            f.write("## Open positions (intraday 5m track)\n\n")
            f.write(pd.DataFrame(st["positions"]).T.to_markdown() + "\n\n")
        if len(st["daily_positions"]):
            f.write("## Open positions (DAILY track, iAPE-D)\n\n")
            f.write(pd.DataFrame(st["daily_positions"]).T.to_markdown() + "\n\n")
        if len(st["daily_pending"]):
            f.write("## Queued daily entries (fill at next open)\n\n")
            f.write(pd.DataFrame(st["daily_pending"]).T.to_markdown() + "\n\n")
        if len(lg):
            f.write("## Event log (last 40)\n\n")
            f.write(lg.tail(40).to_markdown(index=False) + "\n\n")
        f.write("\nBenchmark to beat honestly: the 2y backtest says variant-B long-only "
                "runs PF ≈ 1.10 with ~5 trades/week on this basket. Judge after 4–6 "
                "weeks and ≥30 closed trades, not after a good Tuesday.\n")
    print(f"Report: {out}")


def status():
    equity, buying_power = broker.account()
    st = load_state()
    print(f"Venue: {broker.VENUE}")
    print(f"Paper equity: ${equity:,.2f}  "
          f"(buying power ${buying_power:,.2f})")
    print(f"Open intraday positions ({len(st['positions'])}):")
    for s, p in st["positions"].items():
        print(f"  {s}: {p['qty']} sh, entry_ref {p['entry_ref']:.2f}, "
              f"stop {p['sl']:.2f}{' (BE)' if p['be_done'] else ''}, tp {p['tp']:.2f}")
    print(f"Open DAILY positions ({len(st['daily_positions'])}):")
    for s, p in st["daily_positions"].items():
        print(f"  {s}: {p['qty']} sh, entry_ref {p['entry_ref']:.2f}, "
              f"stop {p['sl']:.2f}, tp {p['tp']:.2f} (signal {p.get('signal_bar', '?')})")
    print(f"Queued daily entries ({len(st['daily_pending'])}):")
    for s, q in st["daily_pending"].items():
        print(f"  {s}: buy at {q['fill_date']} open, ref {q['ref']:.2f}, "
              f"stop {q['sl']:.2f}, tp {q['tp']:.2f}")
    print(f"Market open: {broker.market_open()}")


def flatten_all(halt=True):
    """KILL SWITCH engine: optionally set the halt flag, then market-sell every
    position the bot tracks (both books) on the active venue. Idempotent — a
    second call finds nothing to sell. Exits are always allowed, so this works
    even while halted."""
    if halt:
        control.set_halt(True)
    st = load_state()
    sold = 0
    for book in ("positions", "daily_positions"):
        for sym, pos in list(st[book].items()):
            try:
                oid = order(sym, pos["qty"], "sell")
                log(event="KILL_FLATTEN", symbol=sym, qty=pos["qty"], order=oid,
                    detail=f"kill switch: flattened {book}")
                st[book].pop(sym)
                sold += 1
            except Exception as e:
                log(event="KILL_ERROR", symbol=sym, detail=str(e)[:120])
    st["daily_pending"] = {}          # cancel anything queued for next open
    save_state(st)
    print(f"flatten_all: sold {sold} position(s); halt={'ON' if halt else 'unchanged'}")
    return sold


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--flatten", action="store_true",
                    help="KILL SWITCH: halt new entries + market-sell all positions")
    ap.add_argument("--resume", action="store_true",
                    help="clear the halt flag (does NOT re-open closed positions)")
    a = ap.parse_args()
    if a.report:
        report()
    elif a.status:
        status()
    elif a.flatten:
        flatten_all(halt=True)
    elif a.resume:
        control.set_halt(False)
        print("halt cleared — new entries allowed again (subject to observer mode)")
    elif a.once:
        tick()
    else:
        print(__doc__)
