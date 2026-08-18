"""
run_month_backtest.py — what the CURRENTLY-ARMED bot would have done over the
last ~1 month, on the live book, at the live sizing.

Faithful to the live config:
  * engine   = iAPE-D  (config_v22, use_htf_trend=False, long-only,
               pure stop + 3R) — the daily flagship the AAPL focus routes to
  * symbols  = the bot's focus (AAPL) if set, else the daily control basket
  * book     = the live sizing base (botconfig / broker.account) — $2,000 now
  * sizing   = live sizing_pct, in WHOLE SHARES (the live bot can't buy a
               fraction), so a position that costs more than sizing_pct% of the
               book is simply NOT TAKEABLE — exactly what happens live.

Daily bars come from the SAME Alpaca IEX daily feed the live bot trades on, with
~1.8y of warmup so the indicators are valid; only trades ENTERED in the trailing
window are counted. Writes cache/month_backtest.json for the dashboard.

HONESTY: one month of a ~0.4-trade/week daily system is 0-2 trades — a curiosity,
NOT evidence. The real bar stays >=30 closed trades (see the validation ledger).

Usage: py run_month_backtest.py [--days 30]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import botconfig
import broker
import forward_trader as ft
from swing_pro import config_v22, run

HERE = Path(__file__).parent
OUT = HERE / "cache" / "month_backtest.json"


def _window_trades(sym, spy, cfg, since, book, sizing_pct):
    """Run the daily engine on `sym`, keep trades ENTERED on/after `since`, and
    re-price each at the live WHOLE-SHARE size on `book`."""
    df = ft.daily_bars(sym, 460)
    if len(df) < 250:
        return None
    res = run(df, spy, cfg)
    rows = []
    for t in res["trades"]:
        if not t.get("exits"):
            continue
        entry_date = str(t["entry_time"])[:10]
        if entry_date < since:
            continue
        entry_px = float(t["entry_fill"])
        exit_px = float(t["exits"][-1][1])
        reason = t["exits"][-1][3]
        pps = (t["pnl"] / t["qty"]) if t["qty"] else 0.0     # per-share P/L (net of costs)
        qty_live = int((sizing_pct / 100.0) * book / entry_px)   # WHOLE shares, live rule
        takeable = qty_live >= 1
        rows.append({
            "symbol": sym,
            "entry_date": entry_date,
            "exit_date": str(t.get("exit_time", ""))[:10],
            "entry": round(entry_px, 2),
            "exit": round(exit_px, 2),
            "reason": reason,
            "open": reason == "end_of_data",
            "per_share": round(pps, 2),
            "qty_live": qty_live,
            "takeable": takeable,
            "pnl_live": round(pps * qty_live, 2),      # 0 if not takeable
            "min_book_1sh": round(entry_px / (sizing_pct / 100.0), 0),  # book needed for 1 share
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()

    bc = botconfig.load()
    sizing_pct = float(bc.get("sizing_pct", 10.0))
    eq, _ = broker.account()
    book = botconfig.sizing_equity(eq, broker.BROKER, bc)     # $2,000 in webull mode
    symbols = list(bc.get("focus_symbols") or ft.DAILY_BASKET)
    since = (datetime.now() - timedelta(days=a.days)).strftime("%Y-%m-%d")

    cfg = config_v22(trade_dir="long", use_htf_trend=False,
                     initial_capital=book, qty_pct_equity=sizing_pct)
    spy = ft.daily_bars("SPY", 460)

    all_rows, errors = [], []
    for sym in symbols:
        try:
            r = _window_trades(sym, spy, cfg, since, book, sizing_pct)
            if r is None:
                errors.append(f"{sym}: insufficient daily history")
            else:
                all_rows.extend(r)
        except Exception as e:
            errors.append(f"{sym}: {str(e)[:100]}")

    # affordability: can the live book buy even 1 share of each focus symbol?
    per_trade = (sizing_pct / 100.0) * book
    afford = []
    for sym in symbols:
        try:
            d = ft.daily_bars(sym, 5)
            px = float(d["close"].iloc[-1]) if len(d) else None
        except Exception:
            px = None
        if px:
            afford.append({"symbol": sym, "price": round(px, 2),
                           "min_book_1sh": round(px / (sizing_pct / 100.0), 0),
                           "affordable": per_trade >= px})
    affordable_syms = [x["symbol"] for x in afford if x["affordable"]]
    unaff_syms = [x["symbol"] for x in afford if not x["affordable"]]
    sizing_warning = None
    if afford and not affordable_syms:                       # nothing tradeable
        cheapest = min(afford, key=lambda x: x["price"])
        sizing_warning = (
            f"At {sizing_pct:.0f}% of a ${book:,.0f} book that's ${per_trade:,.0f} per "
            f"trade, but every focus symbol costs more (cheapest {cheapest['symbol']} "
            f"${cheapest['price']:,.2f}) — the bot can't buy even 1 share of any, so as "
            f"configured it would trade NOTHING. Fix: raise the book (>= "
            f"${cheapest['min_book_1sh']:,.0f} for the cheapest), raise sizing %, or add "
            f"cheaper symbols.")
    elif unaff_syms:                                         # some tradeable, some skipped
        sizing_warning = (
            f"On a ${book:,.0f} book at {sizing_pct:.0f}% (${per_trade:,.0f}/trade), "
            f"{len(affordable_syms)}/{len(afford)} symbols are tradeable "
            f"({', '.join(affordable_syms)}); the pricier ones will be SKIPPED at "
            f"signal time: {', '.join(unaff_syms)}.")

    takeable = [r for r in all_rows if r["takeable"] and not r["open"]]
    untakeable = [r for r in all_rows if not r["takeable"]]
    open_rows = [r for r in all_rows if r["open"]]
    wins = [r for r in takeable if r["pnl_live"] > 0]
    net = round(sum(r["pnl_live"] for r in takeable), 2)

    # the headline reason there may be nothing to show
    blocker = None
    if not all_rows:
        blocker = (f"No daily setup fired on {', '.join(symbols)} in the last "
                   f"{a.days} days — at ~0.4 trades/week this is normal, not a fault.")
    elif not takeable and untakeable:
        px = untakeable[0]["entry"]
        need = untakeable[0]["min_book_1sh"]
        blocker = (f"The signal(s) fired, but on a ${book:,.0f} book at {sizing_pct:.0f}% "
                   f"sizing they are UN-TAKEABLE: {untakeable[0]['symbol']} at ~${px:,.2f} "
                   f"needs a ${need:,.0f} book (or higher sizing %) to afford even 1 share. "
                   f"The live bot would place 0 shares — realized P/L $0.")

    data = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "window_days": a.days,
        "symbols": symbols,
        "engine": "iAPE-D v2.2 · daily · long-only · pure stop + 3R",
        "venue": broker.VENUE,
        "book": book,
        "sizing_pct": sizing_pct,
        "trades_signaled": len(all_rows),
        "trades_takeable": len(takeable),
        "trades_untakeable": len(untakeable),
        "open_now": len(open_rows),
        "wins": len(wins),
        "win_rate": round(100.0 * len(wins) / len(takeable), 1) if takeable else None,
        "net": net,
        "net_pct": round(100.0 * net / book, 2) if book else None,
        "sim_equity": round(book + net, 2),
        "per_trade_budget": round(per_trade, 0),
        "affordability": afford,
        "sizing_warning": sizing_warning,
        "blocker": blocker,
        "detail": sorted(all_rows, key=lambda r: r["entry_date"], reverse=True),
        "errors": errors,
        "note": ("One month of a ~0.4-trade/week daily system is a curiosity, not "
                 "evidence. The go/no-go bar stays >=30 closed trades at/above "
                 "benchmark (PF 1.72). Not financial advice."),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1))

    print(f"1-month backtest -> {OUT}")
    print(f"  {broker.VENUE} · book ${book:,.0f} · {sizing_pct:.0f}% · symbols {symbols}")
    print(f"  signaled {len(all_rows)} · takeable {len(takeable)} · "
          f"untakeable {len(untakeable)} · open {len(open_rows)}")
    print(f"  net (live whole-share) = ${net:,.2f}  -> sim equity ${book + net:,.2f}")
    if sizing_warning:
        print(f"  SIZING: {sizing_warning}")
    if blocker:
        print(f"  BLOCKER: {blocker}")
    for r in data["detail"]:
        flag = "OPEN" if r["open"] else ("take" if r["takeable"] else "SKIP<1sh")
        print(f"    {r['entry_date']} {r['symbol']:<5} {r['reason']:<12} "
              f"entry ${r['entry']:.2f} -> ${r['exit']:.2f}  pps ${r['per_share']:.2f}  "
              f"qty {r['qty_live']} [{flag}]  live ${r['pnl_live']:.2f}")
    for e in errors:
        print("  ERR", e)


if __name__ == "__main__":
    main()
