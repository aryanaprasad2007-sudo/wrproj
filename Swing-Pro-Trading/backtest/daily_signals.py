"""
daily_signals.py — post-close signal scan for the iAPE-D DAILY paper track.

The 30y-validated daily engine (PF 1.47/2.03/2.45 by decade, 1,090 trades, all
22 symbols profitable) gets its own forward audition: v2.2-D config
(config_v22, use_htf_trend=False, long-only) on completed DAILY bars, trading
`daily_universe()` — the survivorship CONTROL basket (13 names) PLUS any
operator focus symbols (e.g. AAPL). The intraday track skips whatever the daily
track owns, so the two never collide on one account (the disjoint invariant,
now maintained dynamically rather than by two hardcoded lists).

Backtest semantics preserved: a signal on today's daily close fills at the
NEXT session's open. This script runs after the close (scheduled 13:05 PT),
queues entries into forward_state.json ("daily_pending", with the exact
fill_date from the Alpaca calendar); forward_trader.py's minute loop places
the market order at that session's open and manages the pure stop + 3R target
at 1m resolution. A pending whose fill window passes unconsumed (machine off)
is EXPIRED, never filled late — a late fill would drift from next-open
semantics.

Pre-registered benchmark (decade-test control run, H2 2021-07 → 2026-07):
PF 1.72, ~0.4 trades/week, 43% win on this basket. Judge at >= 30 closed
trades — at this pace that is patience measured in months, by design.

SAFETY: orders only ever go to paper-api.alpaca.markets (see forward_trader).
Usage:  py daily_signals.py          (the SwingPro_Daily_Signals task runs this)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from forward_trader import (CFG_D, PAPER, _get, daily_bars, daily_universe, log,
                            load_state, save_state)
from swing_pro import compute_signals


def main():
    clock = _get(PAPER, "/v2/clock")
    if clock.get("is_open"):
        log(event="DAILY_SCAN_SKIP", symbol="-",
            detail="market open - daily scan must run after the close")
        return
    st = load_state()
    today = date.today()

    spy = daily_bars("SPY", 460)
    if len(spy) < 300:
        log(event="DAILY_SCAN_ERROR", symbol="SPY",
            detail=f"only {len(spy)} daily bars")
        return

    # exact next session, so fills match the backtest's next-open rule even
    # across weekends and holidays
    cal = _get(PAPER, "/v2/calendar",
               start=(today + timedelta(days=1)).isoformat(),
               end=(today + timedelta(days=10)).isoformat())
    if not cal:
        log(event="DAILY_SCAN_ERROR", symbol="-", detail="calendar empty")
        return
    next_open = cal[0]["date"]

    # expire any pending whose fill window already passed
    for sym, q in list(st["daily_pending"].items()):
        if q["fill_date"] <= today.isoformat():
            log(event="DAILY_EXPIRE", symbol=sym,
                detail=f"unconsumed at scan; fill window was {q['fill_date']}")
            st["daily_pending"].pop(sym)

    queued = resets = 0
    for sym in daily_universe():
        try:
            df = daily_bars(sym, 460)
            if len(df) < 300:
                log(event="DAILY_SCAN_ERROR", symbol=sym,
                    detail=f"only {len(df)} bars")
                continue
            last_bar = str(df.index[-1].date())
            if st["daily_last_bar"].get(sym) == last_bar:
                continue  # this close was already scanned (weekend/holiday rerun)
            st["daily_last_bar"][sym] = last_bar

            sig = compute_signals(df, spy, CFG_D)
            i = len(df) - 1
            if not sig["go_long"][i]:
                continue
            atr_i, c_i = sig["atr"][i], sig["close"][i]
            raw = c_i - (sig["swing_low"][i] - CFG_D.struct_buf_atr * atr_i)
            r = max(raw, CFG_D.atr_stop_mult * atr_i * 0.5) if (CFG_D.use_struct_stop and raw > 0) \
                else CFG_D.atr_stop_mult * atr_i
            if np.isnan(r) or r <= 0:
                continue
            sl, tp = float(c_i - r), float(c_i + CFG_D.rr_ratio * r)

            pos = st["daily_positions"].get(sym)
            if pos:
                # Pine pyramiding quirk kept on purpose: a re-signal while in a
                # position places no order but resets entry_ref/risk/SL/TP
                pos.update({"entry_ref": float(c_i), "risk": float(r),
                            "sl": sl, "tp": tp})
                log(event="DAILY_RESET", symbol=sym,
                    ref_price=round(float(c_i), 2), stop=round(sl, 2),
                    target=round(tp, 2), detail=f"re-signal {last_bar}")
                resets += 1
            else:
                st["daily_pending"][sym] = {
                    "ref": float(c_i), "risk": float(r), "sl": sl, "tp": tp,
                    "signal_bar": last_bar, "fill_date": next_open}
                log(event="DAILY_QUEUE", symbol=sym,
                    ref_price=round(float(c_i), 2), stop=round(sl, 2),
                    target=round(tp, 2),
                    detail=f"signal {last_bar}, fills {next_open} open")
                queued += 1
        except Exception as e:
            log(event="DAILY_SCAN_ERROR", symbol=sym, detail=str(e)[:120])
    save_state(st)
    print(f"[{datetime.now().isoformat(timespec='seconds')}] daily scan: "
          f"{queued} queued, {resets} reset, next session {next_open}, "
          f"{len(st['daily_positions'])} open, "
          f"{len(st['daily_pending'])} pending")


if __name__ == "__main__":
    main()
