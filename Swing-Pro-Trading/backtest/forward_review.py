"""
forward_review.py — weekly verdict on the paper forward test (Fridays 13:30 PT).

Reads forward_log.csv + actual Alpaca paper fills (by order id), reconstructs
closed round-trips, and compares reality against the PRE-REGISTERED benchmark:

    2y backtest of variant B long-only:  PF ~ 1.10,  ~5 trades/week,
    judgment deferred until >= 30 closed trades (4-6 weeks).

Also measures what backtests can only assume: REALIZED SLIPPAGE — logged
signal reference price vs the actual paper fill on every order.

Output: reports/weekly_review_<date>.md  (one page, verdict up top)

Usage:  py forward_review.py
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import broker
from data import _env

PAPER = "https://paper-api.alpaca.markets"
HERE = Path(__file__).parent
LOG_F = HERE / "forward_log.csv"
REPORTS = HERE / "reports"
START_EQUITY = 100_000.0
BENCH = {"pf": 1.30, "trades_per_week": 8.4, "min_trades_to_judge": 30}
# benchmark re-registered 2026-07-02 after adopting the exit-sweep winner (v2.2)
# and the two-basket forward test: v2.2 long-only 2y = PF 1.30 (~4.2 trades/wk per
# 5-name basket; ~8.4/wk across both baskets).
BASKETS = {"current":   ["AAPL", "NVDA", "TSLA", "MSFT", "META"],
           "candidate": ["MSTR", "ORCL", "NFLX", "AVGO", "CRWD"]}
BASKET_BENCH = {"current": 1.30, "candidate": 1.40}
# Monte Carlo panic thresholds (montecarlo_2026-07-02.md, 10k shuffles of 857
# trades): for a WORKING v2.2, over any ~50-trade window these are NORMAL:
MC = {"max_streak_ok": 12, "window_net_5pct": -1030, "p_losing_window": 17.5}
# DAILY track (iAPE-D on the control basket, live 2026-07-06). Benchmark
# pre-registered 2026-07-05 from the decade-test control run, H2 2021-07 →
# 2026-07: PF 1.72, 102 trades in 261 wks (~0.4/wk), 43.1% win. At that pace
# the ≥30-trade judgment is months out — expected, not a malfunction.
DAILY_BENCH = {"pf": 1.72, "trades_per_week": 0.4, "win": 43.1,
               "min_trades_to_judge": 30}


def _get(path, **q):
    url = PAPER + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY")})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def fills_by_id():
    out = {}
    for o in _get("/v2/orders", status="closed", limit=500, direction="desc"):
        if o.get("filled_avg_price"):
            out[o["id"]] = float(o["filled_avg_price"])
    return out


def all_fills(lg):
    """Venue-aware order-id → actual-fill-price map: Alpaca paper fills (by
    order id) merged with Webull paper fills (order_detail per client_order_id,
    cached in webull_fills.py). A venue that errors contributes nothing — those
    rows then score at the logged reference price instead of crashing the
    review."""
    fills = {}
    try:
        fills.update(fills_by_id())
    except Exception:
        pass
    try:
        import webull_fills
        ids = [o for o in lg["order"].dropna().astype(str)
               if webull_fills.looks_webull(o)]
        if ids:
            fills.update(webull_fills.fill_map(ids))
    except Exception:
        pass
    return fills


def with_fills(lg):
    """Attach the 'fill' column (actual fill by order id; NaN where unmatched)
    that the roundtrip reconstructors expect — then null out shared-sim
    garbage: the Webull UAT simulator has printed a $10.00 fill on a ~$425
    stock, so a fill >15% from the logged reference is venue noise, not
    information, and that row scores at reference. Shared with cockpit.py so
    both views stay identical."""
    lg = lg.copy()
    fills = all_fills(lg)
    lg["fill"] = (lg["order"].map(fills) if len(lg)
                  else pd.Series(dtype="float64"))
    if len(lg):
        ref = pd.to_numeric(lg["ref_price"], errors="coerce")
        bad = lg["fill"].notna() & (ref > 0) & ((lg["fill"] / ref - 1).abs() > 0.15)
        lg.loc[bad, "fill"] = np.nan
    return lg


def intraday_roundtrips(lg):
    """Closed 5m-track round-trips from the event log, REAL orders only
    (SHADOW_*/RECONCILE_*/TICK_*/DAILY_* excluded). `lg` must already carry a
    'fill' column (actual paper fills mapped by order id; NaN where unmatched).
    Returns (closed_df, still_open_dict). Imported by cockpit.py so the live
    cockpit and this Friday referee reconstruct trades identically."""
    trades, open_t = [], {}
    real = lg[~lg.event.astype(str).str.startswith(
        ("SHADOW", "RECONCILE", "TICK", "DAILY"))]
    for _, r in real.sort_values("ts").iterrows():
        s = r.symbol
        if r.event == "BUY":
            open_t[s] = {"symbol": s, "entry_ts": r.ts, "qty": r.qty,
                         "cost": r.qty * (r.fill or r.ref_price),
                         "proceeds": 0.0, "events": ["BUY"]}
        elif s in open_t:
            t = open_t[s]
            t["proceeds"] += r.qty * (r.fill if not np.isnan(r.fill) else r.ref_price)
            t["events"].append(r.event)
            if r.event in ("STOP", "BREAKEVEN", "TARGET", "TREND_EXIT"):
                t["exit_ts"] = r.ts
                t["pnl"] = t["proceeds"] - t["cost"]
                trades.append(t)
                del open_t[s]
    return pd.DataFrame(trades), open_t


def daily_roundtrips(lg):
    """Closed iAPE-D round-trips (real paper orders on the control basket)
    from the event log, plus queue counts. `lg` must carry a 'fill' column.
    Returns (closed_df, still_open_dict, counts). Shared with cockpit.py."""
    dl = lg[lg.event.astype(str).str.startswith("DAILY")]
    dtr, dopen = [], {}
    for _, r in dl.sort_values("ts").iterrows():
        s = r.symbol
        if r.event == "DAILY_BUY":
            dopen[s] = {"symbol": s, "entry_ts": r.ts, "qty": r.qty,
                        "cost": r.qty * (r.fill if not np.isnan(r.fill)
                                         else r.ref_price)}
        elif r.event in ("DAILY_STOP", "DAILY_TARGET") and s in dopen:
            t = dopen.pop(s)
            fillpx = r.fill if not np.isnan(r.fill) else r.ref_price
            t["exit_ts"], t["exit"] = r.ts, r.event
            t["pnl"] = r.qty * fillpx - t["cost"]
            # >0 = market gapped/slipped through the stop: the daily backtest's
            # blind spot, now measured live
            t["gap"] = (r.ref_price - fillpx) if r.event == "DAILY_STOP" else np.nan
            dtr.append(t)
    counts = {"queued": int((dl.event == "DAILY_QUEUE").sum()),
              "fills": int((dl.event == "DAILY_BUY").sum()),
              "expired": int(dl.event.isin(["DAILY_EXPIRE", "DAILY_SKIP"]).sum())}
    return pd.DataFrame(dtr), dopen, counts


def main():
    REPORTS.mkdir(exist_ok=True)
    today = date.today().isoformat()
    out = REPORTS / f"weekly_review_{today}.md"
    if broker.BROKER == "alpaca":
        equity_row = f"${float(_get('/v2/account')['equity']):,.2f}"
        equity_bench = "$100,000 start"
    else:
        book, _ = broker.account()
        equity_row = f"${book:,.0f} sim book"
        equity_bench = ("scored from fills/levels — the shared Webull UAT "
                        "balance is not meaningful")

    if not LOG_F.exists() or len(pd.read_csv(LOG_F)) == 0:
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# Forward-test weekly review — {today}\n\n"
                    f"**Verdict: NO TRADES YET.** Book {equity_row}. Either the "
                    f"market gave no v2-long setups (plausible — ~5/week expected "
                    f"across 5 symbols) or the scheduled task isn't firing: check "
                    f"forward_task.log and that the machine is awake in market hours.\n")
        print(f"Report: {out}")
        return

    lg = with_fills(pd.read_csv(LOG_F))

    # realized slippage per event (buys pay fill-ref; sells lose ref-fill)
    lg["slip"] = np.where(lg.event.astype(str).str.endswith("BUY"),
                          lg.fill - lg.ref_price, lg.ref_price - lg.fill)

    # reconstruct INTRADAY round-trips (REAL 5m-track orders only). Shared with
    # cockpit.py via intraday_roundtrips() so the two views can never disagree.
    closed, open_t = intraday_roundtrips(lg)
    n = len(closed)
    weeks = max((datetime.now() - pd.Timestamp(lg.ts.min()).to_pydatetime()).days, 1) / 7.0
    wins = closed[closed.pnl > 0] if n else pd.DataFrame()
    losses = closed[closed.pnl <= 0] if n else pd.DataFrame()
    pf = (wins.pnl.sum() / -losses.pnl.sum()) if n and len(losses) and losses.pnl.sum() < 0 else np.nan
    tpw = n / weeks
    med_slip = lg.slip.median() if lg.slip.notna().any() else np.nan

    if n < BENCH["min_trades_to_judge"]:
        verdict = (f"TOO EARLY TO JUDGE ({n}/{BENCH['min_trades_to_judge']} closed trades). "
                   f"Keep running.")
    elif pf >= BENCH["pf"] * 0.85:
        verdict = (f"ON TRACK: PF {pf:.2f} vs backtest {BENCH['pf']}. The backtest "
                   f"pipeline is holding up in reality.")
    elif pf >= 0.9:
        verdict = (f"UNDERPERFORMING: PF {pf:.2f} vs expected {BENCH['pf']}. Watch "
                   f"slippage line below — if slippage explains the gap, the signal "
                   f"logic is fine and execution needs work.")
    else:
        verdict = (f"FAILING: PF {pf:.2f} over {n} trades. If this persists past "
                   f"{BENCH['min_trades_to_judge']} trades, stop the test and accept "
                   f"the verdict — reality outvotes the backtest.")

    # variance context: is the current losing streak / net normal for a working system?
    streak = 0
    for p in reversed(list(closed.pnl)) if n else []:
        if p <= 0:
            streak += 1
        else:
            break
    var_note = (f"Variance context (Monte Carlo): current losing streak {streak} "
                f"(normal up to {MC['max_streak_ok']}); a window net down to "
                f"${MC['window_net_5pct']:,} is normal; {MC['p_losing_window']}% of "
                f"6-week windows lose money even when the system works.")

    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Forward-test weekly review — {today}\n\n")
        f.write(f"Venue: **{broker.VENUE}**\n\n")
        f.write(f"## Verdict\n\n**{verdict}**\n\n")
        f.write(var_note + "\n\n")
        f.write(f"| metric | actual | benchmark |\n|---|---|---|\n")
        f.write(f"| Equity | {equity_row} | {equity_bench} |\n")
        f.write(f"| Closed trades | {n} | judge at ≥{BENCH['min_trades_to_judge']} |\n")
        f.write(f"| Win rate | {100 * len(wins) / n:.1f}% |" if n else "| Win rate | — |")
        f.write(" ~48% |\n")
        f.write(f"| Profit factor | {pf:.2f} |" if not np.isnan(pf) else "| Profit factor | — |")
        f.write(f" {BENCH['pf']} |\n")
        f.write(f"| Trades/week | {tpw:.1f} | ~{BENCH['trades_per_week']} |\n")
        f.write(f"| Median slippage/share | {'$%.4f' % med_slip if not np.isnan(med_slip) else '—'} "
                f"| $0.01 assumed in backtest |\n\n")
        if n:
            f.write("## Basket vs basket (the universe-scan question)\n\n")
            f.write("| basket | closed | net | PF | benchmark PF |\n|---|---|---|---|---|\n")
            for bname, syms in BASKETS.items():
                sub = closed[closed.symbol.isin(syms)]
                if len(sub):
                    w = sub.pnl[sub.pnl > 0].sum()
                    l = -sub.pnl[sub.pnl <= 0].sum()
                    bpf = w / l if l > 0 else np.inf
                    f.write(f"| {bname} | {len(sub)} | ${sub.pnl.sum():,.0f} | "
                            f"{bpf:.2f} | {BASKET_BENCH[bname]} |\n")
                else:
                    f.write(f"| {bname} | 0 | — | — | {BASKET_BENCH[bname]} |\n")
            f.write("\n## Closed round-trips\n\n")
            show = closed[["symbol", "entry_ts", "exit_ts", "qty", "pnl", "events"]].copy()
            show["pnl"] = show["pnl"].round(2)
            f.write(show.to_markdown(index=False) + "\n\n")
        if len(open_t):
            f.write(f"## Still open: {', '.join(open_t)}\n\n")

        # DAILY track (iAPE-D: real paper orders on the control basket)
        dl = lg[lg.event.astype(str).str.startswith("DAILY")]
        if len(dl):
            f.write("## DAILY track — iAPE-D on the control basket\n\n")
            dc, dopen, _ = daily_roundtrips(lg)
            nd = len(dc)
            f.write(f"Queued signals to date: {int((dl.event == 'DAILY_QUEUE').sum())} "
                    f"· fills: {int((dl.event == 'DAILY_BUY').sum())} "
                    f"· expired/skipped: "
                    f"{int(dl.event.isin(['DAILY_EXPIRE', 'DAILY_SKIP']).sum())} "
                    f"· still open: {', '.join(dopen) if dopen else 'none'}\n\n")
            if nd:
                dw = dc.pnl[dc.pnl > 0].sum()
                dl_ = -dc.pnl[dc.pnl <= 0].sum()
                dpf = dw / dl_ if dl_ > 0 else np.inf
                f.write(f"{nd} closed · net ${dc.pnl.sum():,.0f} · PF {dpf:.2f} "
                        f"vs pre-registered {DAILY_BENCH['pf']} (control basket "
                        f"H2 2021-26) · win {100 * (dc.pnl > 0).mean():.0f}% vs "
                        f"~{DAILY_BENCH['win']}% · expected pace "
                        f"~{DAILY_BENCH['trades_per_week']}/wk — judge at "
                        f"≥{DAILY_BENCH['min_trades_to_judge']} closed (months, "
                        f"by design).\n\n")
                gaps = dc.gap.dropna()
                if len(gaps):
                    f.write(f"Gap-through-stop (the daily backtest's blind spot): "
                            f"median ${gaps.median():.2f}/sh, worst "
                            f"${gaps.max():.2f}/sh beyond the stop across "
                            f"{len(gaps)} stop exits.\n\n")
                show = dc[["symbol", "entry_ts", "exit_ts", "qty", "pnl", "exit"]].copy()
                show["pnl"] = show["pnl"].round(2)
                f.write(show.to_markdown(index=False) + "\n\n")
            else:
                f.write(f"No closed daily trades yet — at ~"
                        f"{DAILY_BENCH['trades_per_week']}/wk that is expected "
                        f"for the first weeks.\n\n")

        # STRICT shadow track (hypothetical higher-win-rate variant, no orders)
        sh = lg[lg.event == "SHADOW_EXIT"]
        if len(sh):
            pps = sh.detail.astype(str).str.extract(r"pps=(-?\d+\.?\d*)")[0].astype(float)
            sw = int((pps > 0).sum())
            f.write("## STRICT shadow track (same 7 indicators, tighter gates — "
                    "hypothetical, not traded)\n\n")
            f.write(f"{len(sh)} closed shadow trades · win rate "
                    f"{100 * sw / len(sh):.1f}% · net {pps.sum():+.2f} per share-unit. "
                    f"Promotion bar: beat live v2.2 on BOTH win rate and per-share "
                    f"expectancy over ≥30 shadow trades — judged on live prices, "
                    f"never on the retired backtest data.\n\n")
        f.write("*Benchmark pre-registered 2026-07-02 from the 2y variant-B backtest. "
                "Not financial advice.*\n")
    print(f"Verdict: {verdict}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
