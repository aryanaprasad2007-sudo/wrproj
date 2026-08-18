"""
iape_morning.py -- the 6:30am board. One command, every engine, plain English.

WHY THIS FILE EXISTS
--------------------
Everything needed to trade a morning already existed, spread across eleven
modules and ten scheduled tasks. Nothing was missing except a front door. This
is the front door: run it once before the open and it answers, in order,

    1. Is the rig actually alive?      (watchdog logic -- see THE DARK-RIG BUG)
    2. Which engine does today favour? (switch_shadow's frozen classifier)
    3. What fired?                     (swing_pro momentum + mean_rev MR-1)
    4. What would it cost and make?    (rh_desk sizing at the REAL book)
    5. What do I confirm on the chart? (iAPE_v4.pine / iAPE_MR.pine)

Every number here comes from a module that was validated on its own. This file
adds no strategy math -- it imports rh_desk's read/sizing functions rather than
reimplementing them, for the same reason cockpit.py imports forward_review's
round-trip logic: two copies of one calculation eventually disagree, and the
one you are looking at is never the one that ran.

THE DARK-RIG BUG -- the reason step 1 comes first
-------------------------------------------------
When the scheduled tasks are dead, every scanner in this project prints "no
signals today." That is indistinguishable from a real no-signal day, and it is
exactly the failure the lifestyle-tracker's CLAUDE.md names: a sensor failure
wearing a state's name. The rig was dark 2026-08-04 -> 2026-08-17 and the desk
said "No trade today" the whole time, truthfully and uselessly.

So a dark rig is its own state here. It never collapses into "no trade."

EXECUTION SPLIT (inherited from rh_desk, do not change)
-------------------------------------------------------
This file holds no broker credentials and cannot place an order. It prints a
board. Claude pulls live quotes + review_equity_order through the MCP
connector; Ari confirms each ticket in chat and places it. No scheduled task
can ever fire real money.

Usage:
    py -3.12 iape_morning.py                    scan, print the board
    py -3.12 iape_morning.py --book 75.37       override book size
    py -3.12 iape_morning.py --universe wide    all 99 validated names
    py -3.12 iape_morning.py --json             machine-readable (for Claude)
    py -3.12 iape_morning.py --quiet            write board.json only (task use)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Reuse the validated read/sizing path wholesale. See the note above about
# never keeping a second copy of a calculation.
import rh_desk
from forward_trader import CFG_D, daily_bars, daily_universe, load_state
from mean_rev import MRConfig
from rh_desk import Read, _mom_read, _mr_read, regime, size_ticket
import botconfig

HERE = Path(__file__).parent
CACHE = HERE / "cache"
BOARD_F = CACHE / "morning_board.json"
STATE_F = HERE / "forward_state.json"

# The 99 names from universe_scan.py, which ran the live config on a universe
# the 22-symbol basket had never included: PF 2.45, t=13.26, 92/99 profitable.
# Whole history is out-of-sample by construction -- none of it was seen when
# the config was tuned. This is the widest evidence-backed watchlist we have.
#
# Fractional shares are what make it usable: on a $75 book, whole-share sizing
# could only buy names under ~$15. Robinhood does 6dp, so price stops deciding
# the universe and the watchlist can be as wide as the evidence supports.
WIDE_UNIVERSE = [
    "BRK-B", "V", "MA", "AXP", "BLK", "SPGI", "MCO", "ICE", "CME", "TRV",
    "PGR", "CB", "MET", "PRU", "AFL", "AIG", "JNJ", "PFE", "MRK", "ABBV",
    "LLY", "TMO", "ABT", "MDT", "BSX", "ISRG", "SYK", "ELV", "CI", "HUM",
    "CVS", "PG", "PEP", "MDLZ", "CL", "KMB", "EL", "TGT", "LOW", "TJX",
    "ROST", "MCD", "SBUX", "YUM", "CMG", "HON", "MMM", "UPS", "FDX", "LMT",
    "RTX", "NOC", "GD", "EMR", "ETN", "ITW", "PH", "ROK", "CSCO", "TXN",
    "QCOM", "ADI", "AMAT", "LRCX", "KLAC", "ADBE", "CRM", "NOW", "INTU",
    "ADP", "PAYX", "SLB", "COP", "EOG", "PSX", "VLO", "MPC", "LIN", "APD",
    "ECL", "NEM", "FCX", "NEE", "DUK", "SO", "D", "AEP", "PLD", "AMT",
    "EQIX", "PSA", "O", "T", "VZ", "CMCSA", "GOOGL", "AMZN", "META", "NFLX",
]

# Names universe_scan measured NEGATIVE over full history. Kept visible rather
# than deleted -- the engine wants trend persistence and these are defensives,
# so a signal here is the engine working outside its character, not a bonus.
WEAK_NAMES = {"VZ", "MDLZ", "SO", "NEM", "KMB", "FCX", "JNJ"}

# Measured on the 99-symbol scan itself -- the honest expectancy for THIS
# universe, not the 22-name basket's rosier 0.648R holdout figure.
EXPECTANCY_R = 0.48

# MR-1 does NOT have an R-multiple expectancy, and applying the momentum
# figure to it overstates the trade by roughly 4x. Its 3xATR stop is a
# DISASTER stop that fires 14.5% of the time -- the normal exit is "first
# close above the 10-day MA", usually within 5-6 sessions. So its edge is
# quoted the way it was measured and registered: percent of position, not
# multiples of a stop that mostly never gets hit.
MR_EXPECTANCY_PCT = 0.34 / 100.0    # registered forward benchmark, 2026-07-05


# --------------------------------------------------------------------------
# 1. is the rig alive
# --------------------------------------------------------------------------

def rig_health() -> dict:
    """Liveness, as its own state. Never folds into 'no signals today'."""
    out = {"state": "ok", "notes": [], "state_age_h": None, "last_tick": None}

    if not STATE_F.exists():
        out["state"] = "dark"
        out["notes"].append("forward_state.json missing -- the trader has never run")
        return out

    mtime = datetime.fromtimestamp(STATE_F.stat().st_mtime)
    age_h = (datetime.now() - mtime).total_seconds() / 3600.0
    out["state_age_h"] = round(age_h, 1)
    out["last_tick"] = mtime.strftime("%Y-%m-%d %H:%M")

    # Only meaningful against trading sessions. A quiet weekend is not a fault.
    sessions_missed = _sessions_since(mtime)
    if sessions_missed >= 1:
        out["state"] = "dark"
        out["notes"].append(
            f"no successful tick in {age_h:.0f}h -- {sessions_missed} trading "
            f"session(s) missed since {out['last_tick']}")
        out["notes"].append(
            "the scanners below still read live market data, but nothing was "
            "queued overnight and no open position had its stop checked")

    alert = CACHE / "WATCHDOG_ALERT.txt"
    if alert.exists():
        a_age = (datetime.now()
                 - datetime.fromtimestamp(alert.stat().st_mtime)).days
        out["notes"].append(f"watchdog alert on disk ({a_age}d old): "
                            f"cache/WATCHDOG_ALERT.txt")
        if out["state"] == "ok":
            out["state"] = "warn"

    try:
        st = load_state()
        open_pos = list(st.get("positions", {})) + list(st.get("daily_positions", {}))
        if open_pos and out["state"] == "dark":
            out["notes"].append(
                f"{len(open_pos)} paper position(s) unmanaged: {', '.join(open_pos)} "
                f"(paper only -- no real money exposed)")
    except Exception as e:  # state file can be mid-write
        out["notes"].append(f"could not read state: {e}")

    return out


def _sessions_since(when: datetime) -> int:
    """Weekday count since `when`, excluding today. Holidays not modelled --
    this only needs to answer 'has it been quiet longer than a weekend'."""
    n, day = 0, when.date() + timedelta(days=1)
    today = datetime.now().date()
    while day < today:
        if day.weekday() < 5:
            n += 1
        day += timedelta(days=1)
    return n


# --------------------------------------------------------------------------
# 2-4. the board
# --------------------------------------------------------------------------

def build_board(book_usd: float, universe: str, rh_held: list[str],
                progress: bool = True) -> dict:
    s = rh_desk.settings()
    s["book_usd"] = float(book_usd)
    s["symbols"] = []          # this file never honours the single-name pin

    if universe == "wide":
        syms = list(WIDE_UNIVERSE)
    elif universe == "daily":
        syms = daily_universe(botconfig.load())
    else:
        syms = list(dict.fromkeys(daily_universe(botconfig.load()) + WIDE_UNIVERSE))

    spy = daily_bars("SPY", 460)
    if len(spy) < 300:
        raise RuntimeError(f"SPY returned only {len(spy)} daily bars -- feed problem")
    reg = regime(spy)

    mrcfg = MRConfig()
    held = {x.strip().upper() for x in rh_held if x.strip()}
    reads, errors = [], []

    for n, sym in enumerate(syms, 1):
        if progress:
            print(f"\r  scanning {n}/{len(syms)} {sym:<8}", end="", file=sys.stderr)
        rd = Read(symbol=sym)
        try:
            df = daily_bars(sym, 460)
            if len(df) < 260:
                errors.append(f"{sym}: only {len(df)} bars")
                continue
            _mom_read(df, spy, rd)
            _mr_read(df, rd, mrcfg)
            if sym in held:
                rd.held = "robinhood"
        except Exception as e:
            errors.append(f"{sym}: {type(e).__name__}: {e}")
            continue
        reads.append(rd)
    if progress:
        print("\r" + " " * 40 + "\r", end="", file=sys.stderr)

    # Rank: what actually fired, best engine for the regime first.
    fav = reg.get("favours", "momentum")

    def rank(r: Read) -> tuple:
        mom_hit = r.mom_state == "triggered"
        mr_hit = r.mr_state == "triggered"
        primary = mom_hit if fav == "momentum" else mr_hit
        secondary = mr_hit if fav == "momentum" else mom_hit
        forming = r.mom_state == "forming" or r.mr_state == "forming"
        return (not primary, not secondary, not forming,
                -(r.adx if not math.isnan(r.adx) else 0))

    reads.sort(key=rank)

    slots_left = max(0, s["max_positions"] - len(held))
    tickets = []
    for rd in reads:
        if rd.held or (rd.mom_state != "triggered" and rd.mr_state != "triggered"):
            continue
        size_ticket(rd, s, slots_left - len(tickets))
        if rd.qty > 0:
            tickets.append(rd)

    return {
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "session": str(reads[0].bar) if reads else "",
        "book_usd": s["book_usd"],
        "sizing_pct": s["sizing_pct"],
        "rig": rig_health(),
        "regime": reg,
        "universe": universe,
        "scanned": len(reads),
        "tickets": [_ticket_dict(r, s) for r in tickets],
        "watch": [_ticket_dict(r, s) for r in reads
                  if not r.held and r not in tickets
                  and (r.mom_state == "forming" or r.mr_state == "forming")][:12],
        "held": sorted(held),
        "errors": errors,
        "execution": ("Signals only. Claude quotes + reviews through MCP; Ari "
                      "confirms each ticket in chat and places it."),
    }


def _ticket_dict(r: Read, s: dict) -> dict:
    """Build the ticket for whichever engine actually fired.

    The two engines are NOT interchangeable in their exit structure, and the
    first version of this function quietly mixed them: it printed MR's 3xATR
    stop next to momentum's 3R target and momentum's risk figure. On ITW that
    read "risking $0.22" against a stop 5.8% away -- off by ~4x. Each engine
    now supplies its own stop, its own exit rule, and its own expectancy
    model, and nothing is inherited across the boundary.
    """
    engine = "momentum" if r.mom_state == "triggered" else (
        "mean-reversion" if r.mr_state == "triggered" else
        ("momentum" if r.mom_state == "forming" else "mean-reversion"))
    entry = r.mom_entry if not math.isnan(r.mom_entry) else r.price
    d = {
        "symbol": r.symbol,
        "engine": engine,
        "state": r.mom_state if engine == "momentum" else r.mr_state,
        "price": _r(r.price),
        "entry": _r(entry),
        "adx": _r(r.adx),
        "rsi3": _r(r.rsi3),
        "above_trend": r.above_trend,
        "market_ok": r.market_ok,
        "qty": r.qty,
        "notional": r.notional,
        "whole_share_ok": r.whole_share_ok,
        "note": r.note,
        "weak_name": r.symbol in WEAK_NAMES,
        "chart": "iAPE_v4.pine" if engine == "momentum" else "iAPE_MR.pine",
    }

    if engine == "momentum":
        # Pure stop + 3R target -- the validated v2.2 exit (exit sweep, 64
        # configs: no partial, no breakeven, no trend exit).
        d["stop"] = _r(r.mom_stop)
        d["target"] = _r(r.mom_target)
        d["risk_pct"] = _r(r.mom_risk_pct)
        d["risk_usd"] = _r(r.risk_usd)
        d["exit_rule"] = "hold to stop or 3R target -- no partial, no breakeven"
        if d["risk_usd"] is not None:
            d["expectancy_usd"] = round(EXPECTANCY_R * d["risk_usd"], 2)
    else:
        # MR-1: exit on first close > SMA10, 10-session time stop, and the
        # 3xATR disaster stop as the floor. There is no price target.
        stop = r.mr_stop
        d["stop"] = _r(stop)
        d["target"] = None
        d["exit_rule"] = ("exit on first close above the 10-day MA; hard time "
                          "stop at 10 sessions; 3xATR disaster stop")
        if not math.isnan(stop) and not math.isnan(entry) and entry > 0:
            d["risk_pct"] = round((entry - stop) / entry * 100.0, 2)
            d["risk_usd"] = round(r.qty * (entry - stop), 2) if r.qty else None
        else:
            d["risk_pct"] = d["risk_usd"] = None
        if r.notional:
            d["expectancy_usd"] = round(MR_EXPECTANCY_PCT * r.notional, 2)
    return d


def _r(x, dp=2):
    try:
        return None if x is None or math.isnan(float(x)) else round(float(x), dp)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# TODO(Ari) -- the one decision that is yours, not the engine's
# --------------------------------------------------------------------------

def is_no_trade_morning(board: dict) -> tuple[bool, str]:
    """Should this morning be skipped entirely, regardless of what fired?

    THIS IS A VALUES DECISION, NOT A STRATEGY ONE, which is why it is a stub
    and not something I wrote for you -- same reason should_intervene() in
    mode_log.py is still a stub.

    The engine answers "is there a signal." It cannot answer "should I be
    trading at all today." Those come apart in exactly the situations where
    the answer matters most, and the honest place to decide is now, calm,
    rather than at 6:40am wanting a trade to work.

    Things worth encoding (pick what you actually believe -- 5-10 lines):

      * Capital floor. Below some balance the position is too small for the
        trade to mean anything and the ritual is costing more attention than
        the money justifies. At $75 a 20% position risks ~$0.60. What is the
        number below which you would rather not bother?

      * Money with a job. Rent money and tuition money should not be in here
        at all. Should the desk refuse to ticket if the book exceeds what you
        can genuinely afford to lose?

      * Regime disagreement. If regime favours mean-reversion and the only
        tickets are momentum, that is the engine trading against its own
        classifier. Skip, or take it smaller?

      * Rig honesty. board["rig"]["state"] == "dark" means nothing was queued
        overnight. Trade the live scan anyway, or fix the rig first?

      * Tilt guard. Consecutive losers, or a morning after a bad night. The
        Monte Carlo says streaks of 12 are NORMAL for a working system --
        so a streak is not evidence of breakage, but it is when people
        abandon a system that is fine, or double down on one that isn't.

    Return (True, "reason shown on the board") to skip the morning.
    """
    return False, ""


# --------------------------------------------------------------------------
# 5. render
# --------------------------------------------------------------------------

BAR = "=" * 66


def render(b: dict) -> str:
    L = []
    when = datetime.fromisoformat(b["generated"]).strftime("%a %b %d, %H:%M")
    L += [BAR, f"  iAPE MORNING BOARD          {when}", BAR, ""]

    # --- rig, first, always ------------------------------------------------
    rig = b["rig"]
    if rig["state"] == "dark":
        L += ["  [ RIG DARK ]  the machine is not running.", ""]
        for n in rig["notes"]:
            L.append(f"     - {n}")
        L += ["",
              "  Everything below is a LIVE scan and is still true. What you",
              "  do NOT have is anything queued overnight, or stops being",
              "  watched on open positions.", ""]
    elif rig["state"] == "warn":
        L += [f"  [ RIG WARN ]  last tick {rig['last_tick']}"]
        for n in rig["notes"]:
            L.append(f"     - {n}")
        L.append("")
    else:
        L += [f"  [ RIG OK ]  last tick {rig['last_tick']} "
              f"({rig['state_age_h']}h ago)", ""]

    # --- regime ------------------------------------------------------------
    r = b["regime"]
    arrow = "rising" if r.get("sma50_rising") else "falling"
    L += [f"  REGIME     favours {r.get('favours', '?').upper()}",
          f"             SPY {r.get('spy')} vs 50d {r.get('sma50')} ({arrow})",
          f"             (shadow classifier -- context, not an instruction)", ""]

    # --- book --------------------------------------------------------------
    per = b["book_usd"] * b["sizing_pct"] / 100.0
    L += [f"  BOOK       ${b['book_usd']:,.2f}   ->  ${per:,.2f} per position "
          f"({b['sizing_pct']:.0f}%)",
          f"             {b['scanned']} names scanned ({b['universe']})", ""]

    skip, why = is_no_trade_morning(b)
    if skip:
        L += [BAR, f"  NO-TRADE MORNING: {why}", BAR, ""]
        return "\n".join(L)

    # --- tickets -----------------------------------------------------------
    if not b["tickets"]:
        L += ["  ---- NO TICKETS ----", "",
              "  Nothing triggered. That is the normal state: this engine",
              "  fires roughly every other week per name, and a morning with",
              "  no trade is the system working, not the system failing.", ""]
    else:
        L += [f"  ---- {len(b['tickets'])} TICKET(S) ----", ""]
        for t in b["tickets"]:
            L += _render_ticket(t)

    # --- watch -------------------------------------------------------------
    if b["watch"]:
        names = ", ".join(f"{w['symbol']}({w['engine'][:3]})" for w in b["watch"])
        L += [f"  FORMING    {names}",
              "             not signals -- these are one bar away at most.", ""]

    if b["held"]:
        L += [f"  HELD       {', '.join(b['held'])}  (suppressed as tickets)", ""]

    if b["errors"]:
        L += [f"  DATA       {len(b['errors'])} symbol(s) failed to fetch"]
        for e in b["errors"][:4]:
            L.append(f"             {e}")
        L.append("")

    L += [BAR,
          "  Levels are LEVELS, not resting orders. Nothing sits at the",
          "  broker. A position is protected only if you act.",
          BAR]
    return "\n".join(L)


def _render_ticket(t: dict) -> list[str]:
    L = []
    flag = "  <-- weak name for this engine" if t["weak_name"] else ""
    L.append(f"  {t['symbol']:<7} {t['engine'].upper():<15} {t['state']}{flag}")

    tgt = f"   target {t['target']}" if t.get("target") is not None else ""
    L.append(f"          entry {t['entry']}   stop {t['stop']}{tgt}")
    if t.get("risk_pct") is not None:
        L.append(f"          stop is {t['risk_pct']:.2f}% away")
    L.append(f"          exit: {t['exit_rule']}")

    risk = t.get("risk_usd")
    risk_s = f"risking ${risk:.2f}" if risk is not None else "risk unpriced"
    L.append(f"          buy {t['qty']:.6f} sh = ${t['notional']:.2f}   {risk_s}")

    if "expectancy_usd" in t:
        basis = ("0.48R measured on this universe" if t["engine"] == "momentum"
                 else "+0.34%/trade, MR-1 registered benchmark")
        L.append(f"          expected value at this size: "
                 f"${t['expectancy_usd']:.2f}   ({basis})")
    if not t["whole_share_ok"]:
        L.append(f"          fractional -> MARKET order, regular hours only")
    L.append(f"          confirm on chart: {t['chart']}")
    if t["note"]:
        L.append(f"          note: {t['note']}")
    L.append("")
    return L


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", type=float, default=None,
                    help="book size in USD (default: last saved desk setting)")
    ap.add_argument("--universe", choices=["daily", "wide", "all"], default="wide")
    ap.add_argument("--held", default="",
                    help="comma-separated symbols open in the real RH account")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="write the board file only (for scheduled use)")
    a = ap.parse_args()

    book = a.book if a.book is not None else rh_desk.settings()["book_usd"]
    held = [x for x in a.held.split(",") if x.strip()]

    board = build_board(book, a.universe, held, progress=not a.quiet)
    CACHE.mkdir(exist_ok=True)
    BOARD_F.write_text(json.dumps(board, indent=1, default=str), encoding="utf-8")

    if a.json:
        print(json.dumps(board, indent=1, default=str))
    elif not a.quiet:
        print(render(board))


if __name__ == "__main__":
    main()
