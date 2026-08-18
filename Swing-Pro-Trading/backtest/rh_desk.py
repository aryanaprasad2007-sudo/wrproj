"""
rh_desk.py — the iAPE trading desk for the Robinhood AGENTIC account.

WHAT THIS IS
------------
The signal->ticket read path that was missing. Everything upstream of this
(swing_pro.py, mean_rev.py, the switch classifier) is validated engine code;
this module does not invent new strategy math. It:

  1. Scans the tradeable universe on completed DAILY bars with the SAME engine
     and the SAME stop/target math as daily_signals.py (config_v22,
     use_htf_trend=False, long-only, struct stop, 3R target) -- so a ticket
     here is the identical trade the paper track would take.
  2. Adds the MR-1 mean-reversion read (RSI(3)<15 & close>SMA200) from
     mean_rev.py, and the frozen regime classifier from switch_shadow.py
     (SPY > rising 50d) that decides which engine the regime favours.
  3. Prices each candidate against the Robinhood agentic account's REAL cash
     using FRACTIONAL shares -- which is why this venue works where the $2k
     Webull book did not (see the sizing note below).
  4. Emits cache/rh_desk.json (machine-readable ticket book) and rh_desk.html
     (the human desk: watch / signals / tickets / research, one page).

THE EXECUTION SPLIT -- read this before changing anything
---------------------------------------------------------
This module places NO orders and holds NO broker credentials. It cannot.
The Robinhood agentic account is reachable only through the MCP connector in
Ari's chat surface, not from local Python. So the division of labour is:

    Python (this file)  ->  signals, levels, sizing, affordability, the book
    Claude (via MCP)    ->  live quotes, review_equity_order, place_equity_order
    Ari                 ->  says go, per trade, in chat

That is not a limitation to engineer around. It is the safety property: there
is no local code path that can place a real-money order unattended, and no
scheduled task can ever fire one. Do not add one.

SIZING NOTE -- why this venue unblocks the program
--------------------------------------------------
The $2,000 Webull book stalled because whole-share sizing at 10-22% of equity
bought 0 shares of a $335 stock (int(440/335)=1, int(200/335)=0). Robinhood
supports fractional shares to 6dp on market orders in regular hours, so a
$225 book can hold a proper 20% position in ANY name -- price no longer
decides the universe. Tickets are still flagged when a name is unaffordable
under a whole-share fallback, because fractional orders are regular-hours-only
and a limit order outside RTH must be whole-share.

Usage:
    py rh_desk.py                 scan + write book + html
    py rh_desk.py --open          ... and open the desk in a browser
    py rh_desk.py --book 225.37   override the account book size
    py rh_desk.py --json          print the ticket book to stdout (for Claude)
"""
from __future__ import annotations

import argparse
import json
import math
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import botconfig
import indicators as ta
from forward_trader import (BASKET, CFG_D, DAILY_BASKET, daily_bars,
                            daily_universe, load_state)
from mean_rev import MRConfig
from swing_pro import compute_signals

HERE = Path(__file__).parent
CACHE = HERE / "cache"
BOOK_F = CACHE / "rh_desk.json"
SETTINGS_F = CACHE / "rh_desk_settings.json"
HTML_F = HERE.parent / "rh_desk.html"

# The agentic account. Masked in every user-facing surface; the full number is
# only ever passed to MCP tools.
RH_ACCOUNT = "788099208"
RH_MASK = "••••9208"

DEFAULTS = {
    "book_usd": 225.37,        # refreshed from get_portfolio each session
    "sizing_pct": 20.0,        # flat % of book per position (risk-layer winner)
    "max_positions": 5,        # concurrency cap on a small book
    "min_ticket_usd": 1.00,    # Robinhood's floor for a fractional order
    "universe": "daily",       # daily | all
    # Explicit symbol list for THIS desk only. When non-empty it replaces the
    # universe entirely. Deliberately kept here rather than in botconfig's
    # focus_symbols: focus_symbols feeds daily_universe(), which would pull the
    # name into the PAPER track and contaminate a registered-benchmark basket
    # mid-audition. The Robinhood book and the audition stay separate.
    "symbols": [],
}


def settings() -> dict:
    s = dict(DEFAULTS)
    if SETTINGS_F.exists():
        try:
            s.update(json.loads(SETTINGS_F.read_text()))
        except Exception:
            pass
    return s


def save_settings(s: dict) -> None:
    CACHE.mkdir(exist_ok=True)
    SETTINGS_F.write_text(json.dumps(s, indent=1))


# --------------------------------------------------------------------------
# signals
# --------------------------------------------------------------------------

@dataclass
class Read:
    """One symbol's full read: both engines, levels, sizing, affordability."""
    symbol: str
    price: float = float("nan")          # last completed daily close
    bar: str = ""
    # momentum (iAPE-D flagship)
    mom_state: str = "none"              # none | forming | triggered
    mom_entry: float = float("nan")
    mom_stop: float = float("nan")
    mom_target: float = float("nan")
    mom_risk_pct: float = float("nan")   # stop distance / entry
    above_trend: bool = False
    market_ok: bool = False
    adx: float = float("nan")
    # mean reversion (MR-1)
    mr_state: str = "none"               # none | forming | triggered
    mr_stop: float = float("nan")
    rsi3: float = float("nan")
    above_200: bool = False
    # book
    qty: float = 0.0
    notional: float = 0.0
    risk_usd: float = float("nan")
    whole_share_ok: bool = False
    held: str = ""                       # "", "iape-paper", "robinhood"
    note: str = ""


def _levels(sig, i, cfg):
    """Stop/target for bar i -- byte-identical math to daily_signals.py."""
    atr_i, c_i = sig["atr"][i], sig["close"][i]
    raw = c_i - (sig["swing_low"][i] - cfg.struct_buf_atr * atr_i)
    r = (max(raw, cfg.atr_stop_mult * atr_i * 0.5)
         if (cfg.use_struct_stop and raw > 0) else cfg.atr_stop_mult * atr_i)
    if np.isnan(r) or r <= 0:
        return None
    return float(c_i), float(c_i - r), float(c_i + cfg.rr_ratio * r), float(r)


def _mom_read(df, spy, rd: Read) -> None:
    """Momentum engine read.

    'triggered' = go_long fired on the last completed bar (the exact condition
    daily_signals.py queues on). 'forming' = long_state, the engine's own
    setup-without-trigger gate (trend + slope + MACD + impulse + RSI + ADX all
    aligned, entry trigger not yet fired) -- not a proxy I invented."""
    sig = compute_signals(df, spy, CFG_D)
    i = len(df) - 1
    c_i = float(sig["close"][i])
    tma = sig["trend_ma"][i]
    rd.above_trend = bool(c_i > tma) if not np.isnan(tma) else False
    rd.market_ok = bool(sig["mkt_long_ok"][i])
    _, _, adx = ta.dmi(df["high"].to_numpy(float), df["low"].to_numpy(float),
                       df["close"].to_numpy(float), CFG_D.adx_len, CFG_D.adx_len)
    if not np.isnan(adx[i]):
        rd.adx = float(adx[i])
    lv = _levels(sig, i, CFG_D)
    if lv is None:
        return
    entry, sl, tp, r = lv
    if bool(sig["go_long"][i]):
        rd.mom_state = "triggered"
    elif bool(sig["long_state"][i]):
        rd.mom_state = "forming"
    rd.mom_entry, rd.mom_stop, rd.mom_target = entry, sl, tp
    rd.mom_risk_pct = r / entry * 100.0 if entry else float("nan")


def _mr_read(df, rd: Read, cfg: MRConfig) -> None:
    """MR-1 read: RSI(3) < 15 while above the 200d SMA."""
    c = df["close"].to_numpy(float)
    if len(c) < cfg.trend_len + 5:
        return
    rsi = ta.rsi(c, cfg.rsi_len)
    sma200 = ta.sma(c, cfg.trend_len)
    atr = ta.atr(df["high"].to_numpy(float), df["low"].to_numpy(float), c,
                 cfg.atr_len)
    i = len(c) - 1
    rd.rsi3 = float(rsi[i]) if not np.isnan(rsi[i]) else float("nan")
    rd.above_200 = bool(c[i] > sma200[i]) if not np.isnan(sma200[i]) else False
    if not rd.above_200:
        return
    if not np.isnan(atr[i]):
        rd.mr_stop = float(c[i] - cfg.stop_atr_mult * atr[i])
    if not np.isnan(rsi[i]):
        if rsi[i] < cfg.rsi_entry:
            rd.mr_state = "triggered"
        elif rsi[i] < 30.0:
            rd.mr_state = "forming"


def regime(spy: pd.DataFrame) -> dict:
    """The FROZEN switch classifier from switch_shadow.py: SPY above a rising
    50d SMA -> momentum regime, else mean-reversion. In-sample this policy beat
    running both in parallel by +59.7% MAR; it is in forward shadow since
    2026-07-13 and has NOT graduated. Reported as context, not as an order."""
    c = spy["close"]
    sma50 = pd.Series(ta.sma(c.to_numpy(float), 50), index=c.index)
    above = bool(c.iloc[-1] > sma50.iloc[-1])
    rising = bool(sma50.iloc[-1] > sma50.iloc[-6])
    mom = above and rising
    return {
        "favours": "momentum" if mom else "mean-reversion",
        "spy": round(float(c.iloc[-1]), 2),
        "sma50": round(float(sma50.iloc[-1]), 2),
        "above_50d": above,
        "sma50_rising": rising,
        "shadow_only": True,
    }


# --------------------------------------------------------------------------
# sizing
# --------------------------------------------------------------------------

def size_ticket(rd: Read, s: dict, slots_left: int) -> None:
    """Flat %-of-book sizing with fractional shares, plus the honest risk $."""
    if slots_left <= 0:
        rd.note = "position cap reached"
        return
    budget = s["book_usd"] * s["sizing_pct"] / 100.0
    px = rd.mom_entry if not math.isnan(rd.mom_entry) else rd.price
    if math.isnan(px) or px <= 0:
        return
    if budget < s["min_ticket_usd"]:
        rd.note = f"budget ${budget:.2f} below the ${s['min_ticket_usd']:.2f} order floor"
        return
    rd.qty = round(budget / px, 6)
    rd.notional = round(rd.qty * px, 2)
    rd.whole_share_ok = px <= budget
    if not math.isnan(rd.mom_stop):
        rd.risk_usd = round(rd.qty * (px - rd.mom_stop), 2)
    if not rd.whole_share_ok:
        rd.note = (f"fractional only -- 1 share is ${px:,.2f} vs a "
                   f"${budget:.2f} budget (regular-hours market orders only)")


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

def scan(book_usd: float | None = None, universe: str | None = None,
         rh_held: list[str] | None = None,
         symbols: list[str] | None = None) -> dict:
    """rh_held: symbols currently open in the REAL Robinhood account. This
    module cannot query the broker (no credentials, by design), so Claude
    passes the live position list in from get_equity_positions. Anything held
    there is suppressed as a ticket -- the engine adds no second entry to a
    position it already has open."""
    s = settings()
    if book_usd is not None:
        s["book_usd"] = float(book_usd)
    if universe:
        s["universe"] = universe
    if symbols is not None:
        s["symbols"] = [x.strip().upper() for x in symbols if x.strip()]
    save_settings(s)

    bc = botconfig.load()
    if s["symbols"]:
        syms = list(dict.fromkeys(s["symbols"]))
    else:
        syms = daily_universe(bc)
        if s["universe"] == "all":
            syms = list(dict.fromkeys(syms + BASKET))

    spy = daily_bars("SPY", 460)
    if len(spy) < 300:
        raise RuntimeError(f"SPY returned only {len(spy)} daily bars")

    st = load_state()
    paper_held = set(st.get("daily_positions", {})) | set(st.get("positions", {}))
    queued = st.get("daily_pending", {})
    rh_set = {x.strip().upper() for x in (rh_held or []) if x.strip()}
    # a real holding consumes a slot, same as it would on the paper book
    slots_used = len(rh_set)

    mrcfg = MRConfig()
    reads: list[Read] = []
    errors: list[str] = []
    for sym in syms:
        rd = Read(symbol=sym)
        try:
            df = daily_bars(sym, 460)
            if len(df) < 300:
                errors.append(f"{sym}: only {len(df)} bars")
                continue
            rd.price = float(df["close"].iloc[-1])
            rd.bar = str(df.index[-1].date())
            _mom_read(df, spy, rd)
            _mr_read(df, rd, mrcfg)
            if sym in rh_set:
                rd.held = "robinhood"      # real position wins the label
            elif sym in paper_held:
                rd.held = "iape-paper"
        except Exception as e:
            errors.append(f"{sym}: {str(e)[:100]}")
            continue
        reads.append(rd)

    reg = regime(spy)
    # Rank: the regime-favoured engine's triggers first, then the other
    # engine's triggers, then forming setups, then the rest.
    def rank(r: Read):
        fav_mom = reg["favours"] == "momentum"
        prim = r.mom_state if fav_mom else r.mr_state
        sec = r.mr_state if fav_mom else r.mom_state
        order = {"triggered": 0, "forming": 1, "none": 2}
        return (order[prim], order[sec], r.symbol)
    reads.sort(key=rank)

    slots = s["max_positions"] - slots_used
    for r in reads:
        if r.mom_state == "triggered" and not r.held:
            size_ticket(r, s, slots)
            if r.qty > 0:
                slots -= 1

    tickets = [r for r in reads if r.mom_state == "triggered" and not r.held]
    # triggers that exist but are not tickets, so the page never shows a
    # "0 tickets" message next to a "N triggered" tile without explaining why
    suppressed = [{"symbol": r.symbol, "why": f"already held ({r.held})"}
                  for r in reads if r.mom_state == "triggered" and r.held]
    book = {
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "account": RH_MASK,
        "account_full": RH_ACCOUNT,
        "settings": s,
        "regime": reg,
        "reads": [asdict(r) for r in reads],
        "tickets": [asdict(r) for r in tickets],
        "suppressed": suppressed,
        "rh_held": sorted(rh_set),
        "paper_queued": {k: v for k, v in queued.items()},
        "paper_held": sorted(paper_held),
        "errors": errors,
        "execution": ("Signals only. Orders are placed by Claude through the "
                      "Robinhood MCP connector after Ari confirms each ticket "
                      "in chat. No local code path can place an order."),
    }
    CACHE.mkdir(exist_ok=True)
    BOOK_F.write_text(json.dumps(book, indent=1))
    return book


# --------------------------------------------------------------------------
# the desk page
# --------------------------------------------------------------------------

CSS = """
:root{
  --bg:#fdf7fd; --bg2:#f8eefb; --ink:#3d1f4f; --ink2:#6b4b7d; --ink3:#9a7fa8;
  --card:#ffffff; --line:#f2ddf4; --line2:#e6cdea;
  --purple:#8b3fd4; --purple-soft:#f4e7fc; --purple-deep:#5b1f96;
  --pink:#e0399b; --pink-soft:#ffe7f4; --pink-deep:#b3186f;
  --amber:#a8650a; --amber-soft:#fff3dd; --amber-line:#f3cd8c;
  --shadow:0 1px 2px rgba(139,63,212,.05), 0 4px 16px rgba(139,63,212,.07);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;color:var(--ink);
 background:linear-gradient(170deg,#fdf7fd 0%,#f9eefb 42%,#fdf3f9 100%);
 background-attachment:fixed;min-height:100vh;
 font:16px/1.65 ui-rounded,"SF Pro Rounded","Segoe UI Variable Display",
 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:34px 22px 90px}

.hd{display:flex;align-items:center;gap:13px;flex-wrap:wrap;margin-bottom:5px}
h1{font-size:31px;line-height:1.2;margin:0;font-weight:800;letter-spacing:-.02em;
 background:linear-gradient(96deg,var(--purple-deep),var(--pink));
 -webkit-background-clip:text;background-clip:text;color:transparent}
.acct{font-size:14px;font-weight:700;color:var(--purple);
 background:var(--purple-soft);padding:5px 14px;border-radius:999px;
 white-space:nowrap;border:1.5px solid var(--line2)}
.sub{color:var(--ink3);font-size:14px;margin:0 0 24px;font-weight:500}

h2{font-size:13px;text-transform:uppercase;letter-spacing:.1em;
 color:var(--pink-deep);margin:40px 0 14px;font-weight:800;
 display:flex;align-items:center;gap:11px}
h2::after{content:"";flex:1;height:2px;border-radius:2px;
 background:linear-gradient(90deg,var(--line2),transparent)}

.card{background:var(--card);border:1.5px solid var(--line);border-radius:18px;
 padding:20px 22px;margin-bottom:14px;box-shadow:var(--shadow);font-size:15px}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(176px,1fr));gap:14px}
.row>.card{margin:0;text-align:center;padding:18px 14px}
.k{color:var(--ink3);font-size:11.5px;text-transform:uppercase;
 letter-spacing:.09em;font-weight:700}
.v{font-size:26px;font-weight:800;margin-top:6px;color:var(--purple-deep);
 letter-spacing:-.02em;line-height:1.25}

.banner{background:var(--purple-soft);border:1.5px solid var(--line2);
 padding:15px 19px;border-radius:16px;margin-bottom:14px;font-size:14.5px;
 color:var(--ink2);line-height:1.62}
.banner b{color:var(--purple-deep)}
.warn{background:var(--amber-soft);border-color:var(--amber-line);color:#674713}
.warn b{color:var(--amber)}

.scroll{overflow-x:auto;border-radius:15px;border:1.5px solid var(--line);
 box-shadow:var(--shadow)}
table{width:100%;border-collapse:collapse;font-size:14.5px;background:var(--card)}
th{text-align:left;color:var(--pink-deep);font-weight:800;font-size:11px;
 text-transform:uppercase;letter-spacing:.07em;padding:13px 13px;
 background:var(--pink-soft);white-space:nowrap}
td{padding:14px 13px;border-top:1.5px solid var(--line);white-space:nowrap;
 font-weight:500}
tbody tr:nth-child(even) td{background:#fdf9fe}
tbody tr:hover td{background:var(--purple-soft)}
.sym{font-weight:800;font-size:15.5px;color:var(--purple-deep)}
.num{text-align:right;font-variant-numeric:tabular-nums}
.yes{color:var(--purple);font-weight:800;font-size:16px}
.no{color:#d3bcdb;font-weight:700;font-size:16px}

.pill{display:inline-block;padding:4px 13px;border-radius:999px;font-size:12px;
 font-weight:800;letter-spacing:.02em;white-space:nowrap}
.trig{background:linear-gradient(96deg,var(--pink),#f56cbb);color:#fff;
 box-shadow:0 2px 8px rgba(224,57,155,.34)}
.form{background:var(--amber-soft);color:var(--amber);
 border:1.5px solid var(--amber-line)}
.none{background:#f7f0f9;color:#bda5c7;border:1.5px solid var(--line)}
.held{background:var(--purple-soft);color:var(--purple-deep);
 border:1.5px solid var(--line2)}
.mut{color:var(--ink3)}

.ticket{border:2.5px solid transparent;border-radius:20px;
 background:linear-gradient(#fff,#fff) padding-box,
 linear-gradient(120deg,var(--pink),var(--purple)) border-box;
 box-shadow:0 4px 22px rgba(224,57,155,.16)}
.ticket h3{margin:0 0 14px;font-size:21px;font-weight:800;
 color:var(--pink-deep);letter-spacing:-.01em}
.lv{display:grid;grid-template-columns:repeat(auto-fit,minmax(106px,1fr));
 gap:11px;margin:6px 0 12px}
.lv>div{font-size:11px;color:var(--ink3);text-transform:uppercase;
 letter-spacing:.06em;font-weight:700;background:var(--bg2);
 border-radius:13px;padding:11px 13px}
.lv b{display:block;font-size:19px;font-weight:800;margin-top:4px;
 color:var(--purple-deep);text-transform:none;letter-spacing:-.01em;
 font-variant-numeric:tabular-nums}
.say{background:var(--pink-soft);border-radius:14px;padding:14px 17px;
 margin-top:12px;font-size:14.5px;color:var(--ink2);line-height:1.62}

code{background:var(--purple-soft);color:var(--purple-deep);padding:3px 9px;
 border-radius:8px;font-size:13.5px;font-weight:700;
 font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
ol{margin:0;padding-left:22px;line-height:2.05;font-size:15px}
ol::marker{color:var(--pink);font-weight:800}
footer{color:var(--ink3);font-size:13.5px;margin-top:46px;
 border-top:2px solid var(--line);padding-top:20px;line-height:1.7}

@media(max-width:640px){
  .wrap{padding:20px 14px 60px}
  h1{font-size:25px} .v{font-size:22px} body{font-size:15px}
  table{font-size:13.5px} td,th{padding:11px 9px}
  .card{padding:16px 16px;border-radius:15px}
  .lv{grid-template-columns:repeat(auto-fit,minmax(92px,1fr))}
  /* 2-up tiles instead of 5 full-width blocks: keeps the numbers on one
     screen instead of pushing the watchlist three scrolls down. */
  .row{grid-template-columns:1fr 1fr;gap:10px}
  .row>.card{padding:14px 8px}
  .v{font-size:19px} .k{font-size:10px;letter-spacing:.06em}
  .row>.card .v span{font-size:16px!important}
}
"""


def _pill(state: str, held: str = "") -> str:
    if held:
        return '<span class="pill held">holding</span>'
    cls = {"triggered": "trig", "forming": "form", "none": "none"}[state]
    txt = {"triggered": "triggered", "forming": "forming", "none": "—"}[state]
    return f'<span class="pill {cls}">{txt}</span>'


def _f(x, dp=2, dash="—"):
    return dash if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{dp}f}"


ART_CSS = """
:root{
  --ground:#fcf6fd; --veil:#f6e9fa; --card:#ffffff; --edge:#f0dbf4;
  --ink:#3a1c4c; --ink2:#6d4d80; --ink3:#9d82ab;
  --grape:#8b3fd4; --grape-deep:#5d2199; --grape-veil:#f4e7fc;
  --rose:#dd3a99; --rose-deep:#a91768; --rose-veil:#ffe7f4;
  --amber:#a3630b; --amber-veil:#fff2da; --amber-edge:#f0c886;
  --lift:0 1px 2px rgba(120,50,175,.05), 0 6px 20px rgba(120,50,175,.08);
}
@media (prefers-color-scheme:dark){
  :root{
    --ground:#190e21; --veil:#241531; --card:#22142d; --edge:#3a2249;
    --ink:#f6eafa; --ink2:#cbb0da; --ink3:#9b7fac;
    --grape:#c78ff2; --grape-deep:#e0bcff; --grape-veil:#2e1a3e;
    --rose:#ff7ec4; --rose-deep:#ffa8d8; --rose-veil:#3a1730;
    --amber:#f0b95f; --amber-veil:#33240f; --amber-edge:#5c421c;
    --lift:0 1px 2px rgba(0,0,0,.25), 0 6px 22px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --ground:#190e21; --veil:#241531; --card:#22142d; --edge:#3a2249;
  --ink:#f6eafa; --ink2:#cbb0da; --ink3:#9b7fac;
  --grape:#c78ff2; --grape-deep:#e0bcff; --grape-veil:#2e1a3e;
  --rose:#ff7ec4; --rose-deep:#ffa8d8; --rose-veil:#3a1730;
  --amber:#f0b95f; --amber-veil:#33240f; --amber-edge:#5c421c;
  --lift:0 1px 2px rgba(0,0,0,.25), 0 6px 22px rgba(0,0,0,.3);
}
:root[data-theme="light"]{
  --ground:#fcf6fd; --veil:#f6e9fa; --card:#ffffff; --edge:#f0dbf4;
  --ink:#3a1c4c; --ink2:#6d4d80; --ink3:#9d82ab;
  --grape:#8b3fd4; --grape-deep:#5d2199; --grape-veil:#f4e7fc;
  --rose:#dd3a99; --rose-deep:#a91768; --rose-veil:#ffe7f4;
  --amber:#a3630b; --amber-veil:#fff2da; --amber-edge:#f0c886;
  --lift:0 1px 2px rgba(120,50,175,.05), 0 6px 20px rgba(120,50,175,.08);
}
*{box-sizing:border-box}
.dk{background:var(--ground);color:var(--ink);min-height:100%;
 font:16px/1.6 ui-rounded,"SF Pro Rounded","Segoe UI Variable Display",
 "Segoe UI",-apple-system,BlinkMacSystemFont,Roboto,sans-serif;
 -webkit-font-smoothing:antialiased;padding:20px 16px 56px}
.dk *{font-family:inherit}
.col{max-width:860px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
.num{font-variant-numeric:tabular-nums}

.top{display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.mark{font-size:25px;font-weight:800;letter-spacing:-.02em;margin:0;
 text-wrap:balance;
 background:linear-gradient(96deg,var(--grape-deep),var(--rose));
 -webkit-background-clip:text;background-clip:text;color:transparent}
.tag{font-size:13px;font-weight:700;color:var(--grape);background:var(--grape-veil);
 border:1.5px solid var(--edge);padding:4px 12px;border-radius:999px}

/* the answer */
.verdict{background:var(--card);border:2px solid var(--edge);border-radius:20px;
 padding:22px;box-shadow:var(--lift);text-align:center}
.verdict.go{border-color:transparent;
 background:linear-gradient(var(--card),var(--card)) padding-box,
 linear-gradient(120deg,var(--rose),var(--grape)) border-box}
.vhead{font-size:26px;font-weight:800;letter-spacing:-.02em;margin:0 0 6px;
 color:var(--grape-deep);text-wrap:balance;line-height:1.25}
.verdict.go .vhead{color:var(--rose-deep)}
.vsub{color:var(--ink2);font-size:15px;margin:0}
.stamp{display:inline-flex;align-items:center;gap:7px;margin-top:13px;
 font-size:12.5px;font-weight:700;color:var(--ink3);background:var(--veil);
 border-radius:999px;padding:5px 14px}
.stamp.old{background:var(--amber-veil);color:var(--amber);
 border:1.5px solid var(--amber-edge)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--grape);flex:none}
.stamp.old .dot{background:var(--amber)}

.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:11px}
.tile{background:var(--card);border:1.5px solid var(--edge);border-radius:16px;
 padding:15px 12px;text-align:center;box-shadow:var(--lift)}
.tk{font-size:10.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;
 color:var(--ink3)}
.tv{font-size:21px;font-weight:800;margin-top:5px;color:var(--grape-deep);
 letter-spacing:-.02em;line-height:1.3}

/* Scoped to .sec, NOT the bare h2 element: the verdict headline is also an h2
   and was inheriting the uppercase + flex + trailing rule from it. */
.sec{font-size:11.5px;font-weight:800;letter-spacing:.13em;text-transform:uppercase;
 color:var(--rose-deep);margin:16px 0 0;display:flex;align-items:center;gap:10px}
.sec::after{content:"";flex:1;height:2px;border-radius:2px;
 background:linear-gradient(90deg,var(--edge),transparent)}

.panel{background:var(--card);border:1.5px solid var(--edge);border-radius:18px;
 padding:18px 20px;box-shadow:var(--lift);font-size:15px;color:var(--ink2)}
.panel b,.panel strong{color:var(--ink)}
.note{background:var(--grape-veil);border:1.5px solid var(--edge);border-radius:16px;
 padding:15px 18px;font-size:14.5px;color:var(--ink2);line-height:1.62}
.note b{color:var(--grape-deep)}
.note.care{background:var(--amber-veil);border-color:var(--amber-edge);color:var(--amber)}
.note.care b{color:var(--amber)}

/* signal cards - reflow instead of a 12-column table, so this stays readable
   in a narrow side panel next to a chart */
.sig{background:var(--card);border:1.5px solid var(--edge);border-radius:18px;
 padding:16px 18px;box-shadow:var(--lift);display:flex;flex-direction:column;gap:12px}
.sig.hot{border-color:transparent;
 background:linear-gradient(var(--card),var(--card)) padding-box,
 linear-gradient(120deg,var(--rose),var(--grape)) border-box}
.sigtop{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.tick{font-size:19px;font-weight:800;color:var(--grape-deep);letter-spacing:-.01em}
.px{font-size:19px;font-weight:800;margin-left:auto;color:var(--ink)}
.pill{display:inline-block;padding:3px 12px;border-radius:999px;font-size:11.5px;
 font-weight:800;white-space:nowrap}
.p-trig{background:linear-gradient(96deg,var(--rose),#f472bd);color:#fff;
 box-shadow:0 2px 9px rgba(221,58,153,.32)}
.p-form{background:var(--amber-veil);color:var(--amber);
 border:1.5px solid var(--amber-edge)}
.p-none{background:var(--veil);color:var(--ink3);border:1.5px solid var(--edge)}
.p-held{background:var(--grape-veil);color:var(--grape-deep);
 border:1.5px solid var(--edge)}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(74px,1fr));gap:9px}
.fact{background:var(--veil);border-radius:12px;padding:9px 10px;text-align:center}
.fl{font-size:9.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
 color:var(--ink3)}
.fv{font-size:15.5px;font-weight:800;margin-top:3px;color:var(--ink)}
.fv.dim{color:var(--ink3);font-weight:700}
.fv.on{color:var(--grape)}
.fv.off{color:var(--ink3);opacity:.5}
.lvls{font-size:13px;color:var(--ink3);display:flex;gap:16px;flex-wrap:wrap}
.lvls b{color:var(--ink);font-weight:700}
.lvls.hyp{opacity:.62}

.say{background:var(--rose-veil);border-radius:14px;padding:13px 16px;
 font-size:14.5px;color:var(--ink2);line-height:1.6}
.say b{color:var(--rose-deep)}
kbd{background:var(--grape-veil);color:var(--grape-deep);padding:3px 9px;
 border-radius:8px;font-weight:700;font-size:13px;
 font-family:ui-monospace,"SF Mono",Consolas,monospace;border:1.5px solid var(--edge)}
ol.steps{margin:0;padding-left:20px;line-height:1.95;font-size:14.5px;color:var(--ink2)}
ol.steps::marker{color:var(--rose);font-weight:800}
ol.steps b{color:var(--ink)}
.fine{color:var(--ink3);font-size:13px;line-height:1.7;border-top:2px solid var(--edge);
 padding-top:16px;margin-top:8px}
@media(max-width:520px){
  .dk{padding:16px 12px 40px} .mark{font-size:21px} .vhead{font-size:21px}
  .grid{grid-template-columns:1fr 1fr} .tv{font-size:18px}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def _apill(state: str, held: str = "") -> str:
    if held:
        return '<span class="pill p-held">holding</span>'
    cls = {"triggered": "p-trig", "forming": "p-form", "none": "p-none"}[state]
    txt = {"triggered": "TRIGGERED", "forming": "forming", "none": "quiet"}[state]
    return f'<span class="pill {cls}">{txt}</span>'


def render_artifact(book: dict) -> str:
    """The claude.ai companion page: a narrow-column view of the SAME book that
    rh_desk.html renders, meant to sit beside a TradingView chart.

    It is a SNAPSHOT, deliberately. The page has no broker access and no live
    feed -- claude.ai artifacts get no connector grant in this setup -- so the
    as-of stamp is a first-class element and goes amber once the data is stale.
    A trading page that looks live but is not is the dangerous failure mode."""
    s, reg = book["settings"], book["regime"]
    reads = [Read(**r) for r in book["reads"]]
    tickets = [Read(**r) for r in book["tickets"]]
    sup = book.get("suppressed") or []
    budget = s["book_usd"] * s["sizing_pct"] / 100.0
    trig_m = sum(1 for r in reads if r.mom_state == "triggered")
    trig_r = sum(1 for r in reads if r.mr_state == "triggered")
    names = ", ".join(r.symbol for r in reads) if len(reads) <= 4 \
        else f"{len(reads)} names"

    h = [f"<style>{ART_CSS}</style>", '<div class="dk"><div class="col">']
    h.append(f'<div class="top"><h1 class="mark">iAPE Desk</h1>'
             f'<span class="tag">Robinhood {book["account"]}</span>'
             f'<span class="tag">{names}</span></div>')

    # ---- the answer, before any detail ----
    if tickets:
        t = tickets[0]
        head = (f'{len(tickets)} ticket{"s" if len(tickets) > 1 else ""} ready'
                if len(tickets) > 1 else f'Buy {t.symbol}')
        sub = ('The system triggered. Levels below — nothing is placed until '
               'you say go in chat.')
        cls = "verdict go"
    elif sup:
        head = "Nothing new to place"
        why = ", ".join(f'{x["symbol"]}' for x in sup)
        sub = (f'{why} triggered again, but you already hold it. A re-signal '
               f'is not a second entry.')
        cls = "verdict"
    else:
        head = "No trade today"
        n = len(reads)
        rate = ("this engine fires about once every 6 months on a single name"
                if n == 1 else
                f"this engine fires ~{0.4 * n / 13:.2f} times a week across {n} names")
        sub = f'Nothing triggered on the last close — {rate}, so quiet is normal.'
        cls = "verdict"
    h.append(f'<div class="{cls}"><h2 class="vhead">{head}</h2>'
             f'<p class="vsub">{sub}</p>'
             f'<span class="stamp" id="stamp" data-gen="{book["generated"]}">'
             f'<span class="dot"></span><span id="stamptxt">as of '
             f'{book["generated"][:16].replace("T", " ")}</span></span></div>')

    # ---- book tiles ----
    h.append('<div class="grid">')
    for k, v in [("Book", f"${s['book_usd']:,.2f}"),
                 ("Per position", f"${budget:,.2f}"),
                 ("Sizing", f"{s['sizing_pct']:.0f}%"),
                 ("Regime", "momentum" if reg["favours"] == "momentum"
                            else "mean&#8209;rev"),
                 ("Triggered", f"{trig_m}·{trig_r}")]:
        h.append(f'<div class="tile"><div class="tk">{k}</div>'
                 f'<div class="tv num">{v}</div></div>')
    h.append('</div>')

    # ---- tickets ----
    if tickets:
        h.append('<h2 class="sec">The ticket</h2>')
        for t in tickets:
            h.append('<div class="sig hot">')
            h.append(f'<div class="sigtop"><span class="tick">{t.symbol}</span>'
                     f'{_apill("triggered")}'
                     f'<span class="px num">{t.qty:g} sh · '
                     f'${t.notional:,.2f}</span></div>')
            h.append('<div class="facts">')
            for lbl, val in [("Entry", _f(t.mom_entry)), ("Stop", _f(t.mom_stop)),
                             ("Target", _f(t.mom_target)),
                             ("Risk/sh", f"{_f(t.mom_risk_pct, 1)}%"),
                             ("At risk", f"${_f(t.risk_usd)}")]:
                h.append(f'<div class="fact"><div class="fl">{lbl}</div>'
                         f'<div class="fv num">{val}</div></div>')
            h.append('</div>')
            if t.note:
                h.append(f'<div class="lvls">{t.note}</div>')
            h.append(f'<div class="say">Say <b>“buy {t.symbol} on the agentic '
                     f'account”</b> in chat. Claude pulls a live quote, runs the '
                     f'broker’s pre-trade review, shows you the ticket, and '
                     f'places it only after you say go.</div>')
            h.append('</div>')

    # ---- watchlist as signal cards ----
    h.append('<h2 class="sec">Watchlist</h2>')
    for r in reads:
        hot = " hot" if (r.mom_state == "triggered" and not r.held) else ""
        h.append(f'<div class="sig{hot}">')
        h.append(f'<div class="sigtop"><span class="tick">{r.symbol}</span>'
                 f'{_apill(r.mom_state, r.held)}'
                 f'{_apill(r.mr_state) if r.mr_state != "none" else ""}'
                 f'<span class="px num">{_f(r.price)}</span></div>')
        h.append('<div class="facts">')
        for lbl, val, cl in [
                ("RSI(3)", _f(r.rsi3, 1), ""),
                ("ADX", _f(r.adx, 1), ""),
                ("Trend", "✓" if r.above_trend else "✕",
                 "on" if r.above_trend else "off"),
                ("Market", "✓" if r.market_ok else "✕",
                 "on" if r.market_ok else "off")]:
            h.append(f'<div class="fact"><div class="fl">{lbl}</div>'
                     f'<div class="fv num {cl}">{val}</div></div>')
        h.append('</div>')
        hyp = "" if r.mom_state == "triggered" else " hyp"
        h.append(f'<div class="lvls{hyp}">'
                 f'<span>entry <b class="num">{_f(r.mom_entry)}</b></span>'
                 f'<span>stop <b class="num">{_f(r.mom_stop)}</b></span>'
                 f'<span>target <b class="num">{_f(r.mom_target)}</b></span>'
                 f'<span>risk <b class="num">{_f(r.mom_risk_pct, 1)}%</b></span>'
                 f'</div>')
        h.append('</div>')
    h.append('<div class="note">Levels are shown faded unless the name actually '
             '<b>triggered</b> — on a quiet bar they are just where the stop and '
             'target <i>would</i> sit, and they move with every close.</div>')

    # ---- regime ----
    h.append('<h2 class="sec">Regime</h2>')
    h.append(f'<div class="panel">SPY <b class="num">{_f(reg["spy"])}</b> vs its '
             f'50-day <b class="num">{_f(reg["sma50"])}</b> — '
             f'{"above" if reg["above_50d"] else "below"}, and the 50-day is '
             f'{"rising" if reg["sma50_rising"] else "flat or falling"}. '
             f'The frozen switch classifier favours '
             f'<b>{reg["favours"]}</b> right now.<br><br>'
             f'<span style="color:var(--ink3)">That classifier won its '
             f'pre-registered test in sample (+59.7% MAR) but is still in '
             f'forward shadow and has not graduated. Read it as context for '
             f'which engine deserves your attention — not as an '
             f'instruction.</span></div>')

    # ---- how to actually trade from here ----
    h.append('<h2 class="sec">Trading from this page</h2>')
    h.append('<div class="panel"><ol class="steps">'
             '<li><b>This page cannot place orders.</b> It has no broker '
             'connection — it is a read-out of the system.</li>'
             '<li>To trade, type it in the chat next to this panel: '
             '<kbd>buy PRI on the agentic account</kbd>.</li>'
             '<li>Claude pulls the live quote and runs the broker’s pre-trade '
             'review, then shows you shares, notional, and any warnings.</li>'
             '<li><b>You say go.</b> Nothing is placed without that, every '
             'time.</li>'
             '<li>Ask for <kbd>refresh the desk</kbd> to re-scan and update '
             'this page.</li></ol></div>')

    if s.get("symbols"):
        h.append(f'<div class="note care"><b>Focused on '
                 f'{", ".join(s["symbols"])}.</b> Nothing else is scanned, so '
                 f'signals elsewhere will not appear here. The iAPE paper '
                 f'audition is unaffected — it still scans its own basket.</div>')

    cheapest = min((r.price for r in reads if not math.isnan(r.price)),
                   default=float("nan"))
    if not math.isnan(cheapest) and cheapest > budget:
        h.append(f'<div class="note care"><b>Fractional-only book.</b> The '
                 f'cheapest name here is ${cheapest:,.2f} against a '
                 f'${budget:,.2f} budget, so entries must be <b>market orders '
                 f'in regular hours</b> — Robinhood has no fractional limit '
                 f'orders and no fractional extended-hours fills. You accept '
                 f'the spread.</div>')

    h.append('<div class="fine">Stops and targets here are <b>levels, not '
             'resting orders</b> — nothing sits at the broker, so a position is '
             'only protected if you act. The daily engine is 30-year validated '
             '(PF 1.47 / 2.03 / 2.45 by decade, 1,090 trades) but its forward '
             'audition is separate and still open, and PRI itself is outside '
             'the validated basket — 30 trades since 2010, which is a sanity '
             'check, not proof. A ticket is what the system says, not a '
             'promise about what happens next.</div>')

    h.append('</div></div>')
    # Staleness is a safety feature, not decoration: a snapshot that looks live
    # is the dangerous failure mode, so age is computed in the viewer.
    h.append("""<script>
(function(){
  var el=document.getElementById('stamp'),tx=document.getElementById('stamptxt');
  if(!el||!tx)return;
  var gen=new Date(el.getAttribute('data-gen'));
  if(isNaN(gen))return;
  var mins=Math.round((Date.now()-gen.getTime())/60000);
  var ago = mins<2?'just now'
          : mins<60?mins+' min ago'
          : mins<1440?Math.round(mins/60)+'h ago'
          : Math.round(mins/1440)+'d ago';
  tx.textContent='as of '+gen.toLocaleString(undefined,{month:'short',day:'numeric',
    hour:'numeric',minute:'2-digit'})+' · '+ago;
  if(mins>1440){el.className='stamp old';
    tx.textContent+=' · stale, ask Claude to refresh';}
})();
</script>""")
    return "\n".join(h)


def render(book: dict) -> str:
    s, reg = book["settings"], book["regime"]
    reads = [Read(**r) for r in book["reads"]]
    tickets = [Read(**r) for r in book["tickets"]]
    budget = s["book_usd"] * s["sizing_pct"] / 100.0

    trig_m = sum(1 for r in reads if r.mom_state == "triggered")
    trig_r = sum(1 for r in reads if r.mr_state == "triggered")

    # Full document head: this file is opened straight off disk, so it needs
    # its own charset (the table uses ✓/✕/— glyphs) and a viewport tag.
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>iAPE Desk</title>',
         f"<style>{CSS}</style></head><body>", '<div class="wrap">']
    h.append(f'<div class="hd"><h1>iAPE Desk</h1>'
             f'<span class="acct">Robinhood {book["account"]}</span></div>')
    h.append(f'<p class="sub">Generated {book["generated"]} · '
             f'signals on completed daily bars · '
             f'{len(reads)} name{"" if len(reads) == 1 else "s"} scanned</p>')

    # On a small book almost everything is fractional-only, and fractional
    # orders are market + regular-hours only. That is a real operating
    # constraint, not a footnote: it means no limit orders and no pre/post
    # market entries for these names.
    cheapest = min((r.price for r in reads if not math.isnan(r.price)),
                   default=float("nan"))
    notes = []   # caveat banners, emitted BELOW the numbers (see below)
    if not math.isnan(cheapest) and cheapest > budget:
        notes.append(f'<div class="banner warn"><b>Everything here is '
                 f'fractional-only.</b> The cheapest name in the universe is '
                 f'${cheapest:,.2f} against a ${budget:,.2f} per-position '
                 f'budget, so every entry must be a <b>market order in regular '
                 f'hours</b> — Robinhood does not do fractional limit orders or '
                 f'fractional extended-hours fills. Practically: entries happen '
                 f'between 9:30 and 16:00 ET at the market, and you accept the '
                 f'spread. Raising the book above ${cheapest:,.0f} per position '
                 f'is what buys back limit orders.</div>')

    if s.get("symbols"):
        notes.append(f'<div class="banner warn"><b>Focused on '
                 f'{", ".join(s["symbols"])}.</b> Nothing else is being '
                 f'scanned — signals in the rest of the universe will not '
                 f'appear here, and a single name means long stretches with no '
                 f'ticket at all. Clear it with '
                 f'<code>py rh_desk.py --symbols ""</code>. The iAPE paper '
                 f'audition is unaffected; it still scans its own basket.</div>')

    notes.append('<div class="banner">This page reads and computes. It places no '
             'orders — it holds no broker credentials and there is no local '
             'code path to the account. Tickets are executed by Claude through '
             'the Robinhood connector only after you confirm each one in chat.</div>')

    # top tiles
    h.append('<div class="row">')
    for k, v in [("Book", f"${s['book_usd']:,.2f}"),
                 ("Per position", f"${budget:,.2f} ({s['sizing_pct']:.0f}%)"),
                 ("Slots", str(s["max_positions"])),
                 ("Regime favours",
                  '<span style="font-size:20px">'
                  + ("momentum" if reg["favours"] == "momentum"
                     else "mean&#8209;reversion") + '</span>'),
                 ("Triggered", f"{trig_m} mom · {trig_r} MR")]:
        h.append(f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>')
    h.append('</div>')
    # Caveats go AFTER the tiles: the numbers are what you open this page for,
    # and three paragraphs of framing above them buries the answer.
    h.extend(notes)

    # regime
    h.append('<h2>Regime</h2><div class="card">')
    h.append(f'SPY {_f(reg["spy"])} vs 50d {_f(reg["sma50"])} — '
             f'{"above" if reg["above_50d"] else "below"}, 50d '
             f'{"rising" if reg["sma50_rising"] else "flat/falling"}. '
             f'The frozen switch classifier favours <b>{reg["favours"]}</b>.')
    h.append('<div class="mut" style="margin-top:6px">This classifier won the '
             'pre-registered switch-vs-parallel test in sample (+59.7% MAR) but '
             'is still in forward shadow and has not graduated. Read it as '
             'context for which engine deserves attention, not as an instruction.</div>')
    h.append('</div>')

    # tickets
    h.append('<h2>Tickets — what the system would buy</h2>')
    if not tickets:
        sup = book.get("suppressed") or []
        if sup:
            why = ", ".join(f'{x["symbol"]} — {x["why"]}' for x in sup)
            h.append(f'<div class="card mut">Triggers fired on <b>{why}</b>, so '
                     f'there is nothing new to place. A re-signal on a name you '
                     f'already hold is not a second entry.</div>')
        else:
            # ~0.4 trades/week is the 13-name basket rate. Per name that is
            # ~1.8 trades/YEAR, so a focused desk is idle almost all the time
            # and saying "0.4/week" here would overstate the activity 10x.
            n = len(reads)
            rate = ('roughly one trade every 6 months on a single name'
                    if n == 1 else
                    f'~{0.4 * n / 13:.2f} trades/week across {n} names')
            h.append(f'<div class="card mut">No momentum triggers on the last '
                     f'close. Nothing to do — this engine fires {rate}, so '
                     f'empty is the normal state, and sitting out is a '
                     f'position.</div>')
    for t in tickets:
        h.append('<div class="card ticket">')
        h.append(f'<h3>{t.symbol} · buy {t.qty:g} sh ≈ ${t.notional:,.2f}</h3>')
        h.append('<div class="lv">')
        for lbl, val in [("Entry ref", _f(t.mom_entry)), ("Stop", _f(t.mom_stop)),
                         ("Target (3R)", _f(t.mom_target)),
                         ("Risk/share", f"{_f(t.mom_risk_pct)}%"),
                         ("$ at risk", f"${_f(t.risk_usd)}")]:
            h.append(f'<div>{lbl}<b>{val}</b></div>')
        h.append('</div>')
        if t.note:
            h.append(f'<div class="mut">{t.note}</div>')
        h.append(f'<div class="say">To take it, say: '
                 f'<code>buy {t.symbol} on the agentic account</code> — '
                 f'Claude will pull a live quote, run the broker\'s pre-trade '
                 f'review, show you the ticket, and place it only after you '
                 f'say go.</div>')
        h.append('</div>')

    # watchlist
    h.append('<h2>Watchlist</h2><div class="scroll">')
    h.append('<table><thead><tr><th>Symbol</th><th class="num">Last</th>'
             '<th>Momentum</th><th>MR-1</th><th class="num">RSI(3)</th>'
             '<th class="num">ADX</th><th>Trend</th><th>Market</th>'
             '<th class="num">Entry</th><th class="num">Stop</th>'
             '<th class="num">Target</th><th class="num">Risk</th></tr>'
             '</thead><tbody>')
    for r in reads:
        # levels on a bar that did not trigger are hypothetical -- what the
        # stop and target WOULD be if it fired here. Muted so the eye does not
        # read them as live orders.
        lv = "num" if r.mom_state == "triggered" else "num mut"
        h.append('<tr>')
        h.append(f'<td class="sym">{r.symbol}</td>')
        h.append(f'<td class="num">{_f(r.price)}</td>')
        h.append(f'<td>{_pill(r.mom_state, r.held)}</td>')
        h.append(f'<td>{_pill(r.mr_state)}</td>')
        h.append(f'<td class="num">{_f(r.rsi3, 1)}</td>')
        h.append(f'<td class="num">{_f(r.adx, 1)}</td>')
        h.append(f'<td><span class="{"yes" if r.above_trend else "no"}">'
                 f'{"✓" if r.above_trend else "✕"}</span></td>')
        h.append(f'<td><span class="{"yes" if r.market_ok else "no"}">'
                 f'{"✓" if r.market_ok else "✕"}</span></td>')
        h.append(f'<td class="{lv}">{_f(r.mom_entry)}</td>')
        h.append(f'<td class="{lv}">{_f(r.mom_stop)}</td>')
        h.append(f'<td class="{lv}">{_f(r.mom_target)}</td>')
        h.append(f'<td class="{lv}">{_f(r.mom_risk_pct, 1)}%</td>')
        h.append('</tr>')
    h.append('</tbody></table></div>')
    h.append('<div class="card mut" style="margin-top:12px">Greyed levels are '
             'hypothetical — where the stop and target would sit if that name '
             'triggered on this bar. They move with every close. Only the '
             'levels on a <span class="pill trig">triggered</span> row are the '
             'system\'s actual numbers.</div>')

    # real account
    rh = book.get("rh_held") or []
    h.append('<h2>Open in the real account</h2><div class="card">')
    if rh:
        h.append(f'Holding <b>{", ".join(rh)}</b> on {book["account"]} — '
                 f'{len(rh)} of {s["max_positions"]} slots used. Those names '
                 f'are suppressed as tickets; a re-signal is not a second entry.')
    else:
        h.append('<span class="mut">Flat, or the live position list was not '
                 'passed to this scan. This module cannot query the broker — '
                 'ask Claude to run the desk and it will fold in the real '
                 'positions from the connector.</span>')
    h.append('</div>')

    # paper cross-reference
    if book["paper_held"] or book["paper_queued"]:
        h.append('<h2>iAPE paper track (for reference)</h2><div class="card">')
        if book["paper_held"]:
            h.append(f'Open on the paper books: <b>{", ".join(book["paper_held"])}</b>. ')
        if book["paper_queued"]:
            q = ", ".join(f'{k} (fills {v.get("fill_date","?")})'
                          for k, v in book["paper_queued"].items())
            h.append(f'Queued for next open: <b>{q}</b>.')
        h.append('<div class="mut" style="margin-top:6px">The paper track keeps '
                 'running its own audition on its own venue. These are shown so '
                 'you can see when the real account and the experiment agree — '
                 'they are not tickets.</div>')
        h.append('</div>')

    if book["errors"]:
        h.append('<div class="banner warn"><b>Data gaps this scan:</b> '
                 + "; ".join(book["errors"][:8]) + '</div>')

    h.append('<h2>How to run a session</h2><div class="card">')
    h.append('<ol style="margin:0;padding-left:20px;line-height:1.9">'
             '<li>Refresh this page after the close (<code>py rh_desk.py</code>) '
             'or ask Claude to run the desk.</li>'
             '<li>Read the regime, then the tickets. Most days there are none.</li>'
             '<li>For a ticket you want, say so in chat. Claude pulls the live '
             'quote, runs <code>review_equity_order</code>, and shows you shares, '
             'notional, and the broker\'s pre-trade alerts.</li>'
             '<li>You say go. Claude places it. Nothing is placed without that.</li>'
             '<li>Stops are not resting orders here — the level is the '
             'system\'s, and exiting is a decision you make the same way.</li></ol>')
    h.append('</div>')

    h.append('<footer>iAPE · real money, small book, freely testable. The '
             'daily engine is 30y-validated (PF 1.47/2.03/2.45 by decade, 1,090 '
             'trades); its forward audition is separate and still open. A ticket '
             'is what the system says, not a promise about what happens next. '
             'Sizing is flat %-of-book with fractional shares; $ at risk assumes '
             'the stop fills at its level, which gaps do not respect.</footer>')
    h.append('</div></body></html>')
    return "\n".join(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", type=float, default=None,
                    help="account book size in USD (from get_portfolio)")
    ap.add_argument("--universe", choices=["daily", "all"], default=None)
    ap.add_argument("--symbols", default=None,
                    help="comma-separated tickers to scan INSTEAD of the "
                         "universe (e.g. PRI). Desk-only: does not touch "
                         "botconfig focus_symbols or the paper audition. "
                         "Pass '' to clear and go back to the full universe.")
    ap.add_argument("--held", default="",
                    help="comma-separated symbols open in the real Robinhood "
                         "account (from get_equity_positions); suppresses them "
                         "as tickets and consumes their slots")
    ap.add_argument("--open", action="store_true", help="open the desk page")
    ap.add_argument("--json", action="store_true", help="print the ticket book")
    ap.add_argument("--artifact", metavar="PATH", default=None,
                    help="also write the claude.ai companion page (an HTML "
                         "fragment for the Artifact tool) to PATH")
    a = ap.parse_args()

    book = scan(book_usd=a.book, universe=a.universe,
                rh_held=a.held.split(",") if a.held else None,
                symbols=a.symbols.split(",") if a.symbols is not None else None)
    HTML_F.write_text(render(book), encoding="utf-8")
    if a.artifact:
        Path(a.artifact).write_text(render_artifact(book), encoding="utf-8")
        print(f"artifact page -> {a.artifact}")

    if a.json:
        print(json.dumps(book, indent=1))
        return

    reg = book["regime"]
    print(f"iAPE desk · Robinhood {book['account']} · "
          f"${book['settings']['book_usd']:,.2f} book")
    print(f"regime favours {reg['favours']} "
          f"(SPY {reg['spy']} vs 50d {reg['sma50']})")
    print(f"{len(book['reads'])} scanned · {len(book['tickets'])} ticket(s)")
    for t in book["tickets"]:
        print(f"  BUY {t['symbol']:5s} {t['qty']:>10.6f} sh  "
              f"${t['notional']:>8.2f}  entry {t['mom_entry']:.2f}  "
              f"stop {t['mom_stop']:.2f}  target {t['mom_target']:.2f}")
    if book["errors"]:
        print(f"  data gaps: {'; '.join(book['errors'][:5])}")
    print(f"-> {HTML_F}")
    if a.open:
        webbrowser.open(HTML_F.as_uri())


if __name__ == "__main__":
    main()
