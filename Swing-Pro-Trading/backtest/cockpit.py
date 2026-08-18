"""
cockpit.py — iAPE combined live cockpit (formerly SWING_PRO).

ONE HTML view of the whole trading system, side by side:
  • 5m Momentum   (v2.2, intraday)      — REAL paper orders
  • Daily Momentum (iAPE-D)        — REAL paper orders   } one Alpaca
                                                                 paper account
  • Mean-Reversion (MR-1)               — SHADOW audition (no orders yet)

For each: win rate, profit factor, expectancy ($/trade), trades, net — every
number against its PRE-REGISTERED benchmark — plus a portfolio header.

WHY THIS EXISTS (the honest frame):
  Win rate is a dial, not an edge (house rule 4). The momentum core wins ~44-48%
  of the time but its winners are ~3x its losers — that asymmetry IS the edge,
  and every "protective" exit that raises its win rate was measured to clip the
  fat-tail winners (comfort exits cost ~$5,000). More green does NOT come from
  degrading the momentum system. It comes from running a SECOND, structurally
  high-win-rate edge — mean reversion, which wins ~64-66% by construction —
  ALONGSIDE it. The validated 50/50 stack (SP-D + MR) had the best MAR of
  anything tested (0.30 vs 0.18 / 0.27 solo). This cockpit is that portfolio
  made visible: two uncorrelated edges, honestly scored, in one glance.

Metric math is REUSED from forward_review.py (the Friday referee) via
intraday_roundtrips()/daily_roundtrips(), so this view can never disagree with
the official verdict. MR stats come from the shadow audition's own ledger.

Reads:  forward_log.csv, mr_forward_trades.csv, mr_forward_equity.csv, Alpaca acct
Writes: ../cockpit.html   (open in a browser; refresh by re-running)
Usage:  py cockpit.py            # write + print summary
        py cockpit.py --open     # also open it in the default browser
"""
from __future__ import annotations

import html
import json
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from forward_review import (BENCH, DAILY_BENCH, LOG_F, START_EQUITY, _get,
                            daily_roundtrips, intraday_roundtrips, with_fills)

HERE = Path(__file__).parent
OUT = HERE.parent / "cockpit.html"
MR_TRADES = HERE / "mr_forward_trades.csv"
MR_EQ = HERE / "mr_forward_equity.csv"
STATE_F = HERE / "forward_state.json"

# 5m intraday benchmark: forward_review hard-codes ~48% win alongside PF 1.30.
MOM5M_WIN_BENCH = 48.0
# MR-1 benchmark, single-sourced from the shadow auditor (pre-registered from D3
# of the validated baseline, reports/mr_baseline_2026-07-05.md).
try:
    from mr_forward import BENCH as MR_BENCH
except Exception:                                   # keep the cockpit standalone
    MR_BENCH = {"pf": 1.21, "trades_per_wk": 1.8, "exp_pct": 0.34, "win_pct": 64.0}


# ── metrics (same formulas the referee uses) ────────────────────────────────
def stats(pnl) -> dict:
    pnl = pd.Series(pnl, dtype="float64").dropna()
    n = len(pnl)
    if n == 0:
        return dict(n=0, win=None, pf=None, net=0.0, exp=None)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    pf = (wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
    return dict(n=n, win=100 * len(wins) / n, pf=float(pf),
                net=float(pnl.sum()), exp=float(pnl.sum()) / n)


def status(n, pf, bench_pf, judge):
    """Same tiers as forward_review's verdict: audition until >= judge trades,
    then ON TRACK if within 0.85x of the benchmark PF."""
    if n < judge or pf is None:
        return ("audit", f"AUDITING · {n}/{judge}")
    if pf >= bench_pf * 0.85:
        return ("ok", "ON TRACK")
    if pf >= 0.9:
        return ("soft", "SOFT")
    return ("fail", "FAILING")


# ── formatting helpers ──────────────────────────────────────────────────────
def f_pct(x):   return "—" if x is None else f"{x:.1f}%"
def f_pf(x):    return "—" if x is None else ("∞" if x == float("inf") else f"{x:.2f}")
def f_money(x): return f"${x:,.0f}"
def f_exp(x):   return "—" if x is None else f"${x:,.0f}"


# ── data assembly ───────────────────────────────────────────────────────────
def load_log():
    if not LOG_F.exists():
        return pd.DataFrame(columns=["ts", "event", "symbol", "qty",
                                     "ref_price", "stop", "target", "order",
                                     "detail", "fill"]), False, None
    lg = pd.read_csv(LOG_F)
    online, err = False, None
    try:                              # venue-aware real fills (Alpaca + Webull)
        lg = with_fills(lg)           # => cockpit agrees with the Friday referee
        online = True
    except Exception as e:
        err = str(e)[:120]
        lg["fill"] = np.nan
    return lg, online, err


def account_equity():
    try:
        import broker
        if broker.BROKER != "alpaca":
            return broker.account()[0], None    # Webull: the $-book the bot sizes on
        return float(_get("/v2/account")["equity"]), None
    except Exception as e:
        return None, str(e)[:120]


def load_mr():
    """MR-1 shadow ledger + equity. Files are rewritten wholesale each run and
    may be header-only before the first closed shadow trade."""
    try:
        tr = pd.read_csv(MR_TRADES)
    except Exception:
        tr = pd.DataFrame()
    eq = None
    try:
        e = pd.read_csv(MR_EQ)
        if "equity" in e.columns and len(e):
            eq = float(e["equity"].iloc[-1])
    except Exception:
        pass
    return tr, eq


def read_state():
    """The live book, straight from forward_state.json — the same file the
    trader writes. Read-only here: the cockpit never mutates it or places an
    order. Missing/locked file degrades to an empty book."""
    try:
        st = json.loads(STATE_F.read_text())
    except Exception:
        st = {}
    for k in ("positions", "daily_positions", "daily_pending"):
        st.setdefault(k, {})
    return st


def action_rows(st):
    """The actionable levels the VALIDATED tracks are working right now, for a
    human to place by hand. Open positions carry a live stop (breakeven once the
    5m track has moved its stop up); queued daily entries fire at the next open.
    STRICT/shadow signals are deliberately excluded — they are unvalidated and
    must not read as 'go trade this'."""
    rows = []
    for sym, p in st.get("positions", {}).items():
        live_stop = p["entry_ref"] if p.get("be_done") else p["sl"]
        rows.append(dict(track="5m Momentum", kind="OPEN", sym=sym,
                         when="holding", entry=p["entry_ref"], stop=live_stop,
                         target=p["tp"], qty=p.get("qty"), be=bool(p.get("be_done"))))
    for sym, p in st.get("daily_positions", {}).items():
        rows.append(dict(track="Daily Momentum", kind="OPEN", sym=sym,
                         when="holding", entry=p["entry_ref"], stop=p["sl"],
                         target=p["tp"], qty=p.get("qty"), be=False))
    for sym, q in st.get("daily_pending", {}).items():
        rows.append(dict(track="Daily Momentum", kind="QUEUED", sym=sym,
                         when=f"buy at {q['fill_date']} open", entry=q["ref"],
                         stop=q["sl"], target=q["tp"], qty=q.get("qty"), be=False))
    # OPEN before QUEUED, then by symbol — a stable, scannable order
    rows.sort(key=lambda r: (r["kind"] != "OPEN", r["sym"]))
    return rows


def action_board(rows):
    if not rows:
        return ('<div class="board-empty">The validated tracks are flat and have '
                'nothing queued right now. When the system finds a setup, its exact '
                'entry, stop and target appear here — you place it yourself, in your '
                'own broker.</div>')
    trs = []
    for r in rows:
        entry, stop, tgt = r["entry"], r["stop"], r["target"]
        risk_pct = 100 * (entry - stop) / entry if entry else float("nan")
        rr = (tgt - entry) / (entry - stop) if entry > stop else float("nan")
        kp = ('<span class="kp open">HOLDING</span>' if r["kind"] == "OPEN"
              else '<span class="kp queued">NEXT OPEN</span>')
        stoplbl = f"${stop:,.2f}" + (" · BE" if r["be"] else "")
        qty = "—" if r.get("qty") in (None, "") else f'{int(r["qty"])}'
        trs.append(
            f"<tr><td>{kp}</td><td class='sym'>{html.escape(r['sym'])}</td>"
            f"<td class='dim'>{html.escape(r['track'])}</td>"
            f"<td class='dim'>{html.escape(r['when'])}</td>"
            f"<td class='num'>${entry:,.2f}</td>"
            f"<td class='num stop'>{stoplbl}</td>"
            f"<td class='num tgt'>${tgt:,.2f}</td>"
            f"<td class='num'>{risk_pct:.1f}%</td>"
            f"<td class='num'>{rr:.1f}R</td>"
            f"<td class='num dim'>{qty}</td></tr>")
    return ("<div class='board-wrap'><table class='board'><thead><tr>"
            "<th></th><th>Symbol</th><th>Track</th><th>Timing</th><th>Entry</th>"
            "<th>Stop</th><th>Target</th><th>Risk</th><th>R:R</th>"
            "<th>Bot qty*</th></tr></thead>"
            f"<tbody>{''.join(trs)}</tbody></table></div>")


def health(lg):
    """Feed-health line: today's error events. SSL/reset bursts at wake-from-
    sleep are benign one-offs; a large count means a real network problem."""
    if not len(lg):
        return "no events logged yet"
    today = date.today().isoformat()
    todays = lg[lg.ts.astype(str).str.startswith(today)]
    ticks = int((todays.event == "TICK_ERROR").sum())
    scan = int((lg.event == "DAILY_SCAN_ERROR").sum())
    bits = [f"{ticks} TICK_ERROR today (SSL/reset at wake — benign unless bursting)"]
    if scan:
        last = lg[lg.event == "DAILY_SCAN_ERROR"].iloc[-1]
        bits.append(f"{scan} DAILY_SCAN_ERROR (last: {last.symbol} "
                    f"{str(last.ts)[:10]} — watch today's 13:05 scan)")
    return " · ".join(bits)


def build_strategies(lg):
    ic, iopen = intraday_roundtrips(lg)
    dc, dopen, dcnt = daily_roundtrips(lg)
    mr, _ = load_mr()

    s5 = stats(ic.pnl if len(ic) else [])
    sd = stats(dc.pnl if len(dc) else [])
    sm = stats(mr.pnl if len(mr) and "pnl" in mr else [])

    return [
        dict(key="mom5m", name="5m Momentum", sub="v2.2 · intraday · stop + 3R",
             edge="Fat-tail momentum", role="Big winners, low hit-rate",
             real=True, book="shared paper account",
             s=s5, open=list(iopen),
             bench_win=MOM5M_WIN_BENCH, bench_pf=BENCH["pf"], judge=BENCH["min_trades_to_judge"],
             note="Wins less than half the time on purpose — 3R targets let winners run 3x the losers."),
        dict(key="momD", name="Daily Momentum", sub="iAPE-D · daily · stop + 3R",
             edge="Fat-tail momentum", role="30y / 22-symbol flagship",
             real=True, book="shared paper account",
             s=sd, open=list(dopen),
             bench_win=DAILY_BENCH["win"], bench_pf=DAILY_BENCH["pf"], judge=DAILY_BENCH["min_trades_to_judge"],
             note=f"Slow by design (~{DAILY_BENCH['trades_per_week']}/wk) — the ≥30-trade verdict is months out. "
                  f"Queued {dcnt['queued']} · filled {dcnt['fills']} · expired {dcnt['expired']}."),
        dict(key="mr", name="Mean-Reversion", sub="MR-1 · daily · RSI(3) dip-buy",
             edge="Mean reversion", role="YOUR HIGH-WIN-RATE ENGINE",
             real=False, book="shadow — no real orders yet",
             s=sm, open=[],
             bench_win=MR_BENCH["win_pct"], bench_pf=MR_BENCH["pf"], judge=30,
             note="Wins ~64-66% by construction — sells into strength fast. Small winners, "
                  "but its green is smooth and uncorrelated with the momentum core."),
    ]


# ── HTML rendering ──────────────────────────────────────────────────────────
def card(st):
    cls, label = status(st["s"]["n"], st["s"]["pf"], st["bench_pf"], st["judge"])
    real_pill = ('<span class="pill real">REAL ORDERS</span>' if st["real"]
                 else '<span class="pill shadow">SHADOW</span>')
    openp = (f'<div class="open">open now: {", ".join(st["open"])}</div>'
             if st["open"] else '<div class="open">no open positions</div>')

    def metric(lbl, val, bench):
        return (f'<div class="metric"><div class="mlbl">{lbl}</div>'
                f'<div class="mval">{val}</div>'
                f'<div class="mbench">bench {bench}</div></div>')

    s = st["s"]
    metrics = "".join([
        metric("WIN RATE", f_pct(s["win"]), f_pct(st["bench_win"])),
        metric("Profit factor", f_pf(s["pf"]), f"{st['bench_pf']:.2f}"),
        metric("Expectancy", f_exp(s["exp"]), "positive"),
        metric("Trades", str(s["n"]), f"≥{st['judge']}"),
        metric("Net P/L", f_money(s["net"]), "—"),
    ])
    return f"""
    <div class="card {st['key']}">
      <div class="chead">
        <div><div class="cname">{html.escape(st['name'])}</div>
             <div class="csub">{html.escape(st['sub'])}</div></div>
        <div class="ctags">{real_pill}<span class="pill st-{cls}">{label}</span></div>
      </div>
      <div class="edge"><span class="tag">{html.escape(st['edge'])}</span>
           <span class="tag ghost">{html.escape(st['role'])}</span></div>
      <div class="metrics">{metrics}</div>
      {openp}
      <div class="cnote">{html.escape(st['note'])}</div>
      <div class="cbook">{html.escape(st['book'])}</div>
    </div>"""


def render(strategies, equity, eq_err, mr_eq, health_line, online, action_html):
    total_closed = sum(s["s"]["n"] for s in strategies)
    wr = " · ".join(f"{s['name'].split()[0]} {f_pct(s['s']['win']) if s['s']['win'] is not None else f_pct(s['bench_win'])+'*'}"
                    for s in strategies)
    acct = f_money(equity) if equity is not None else "unreachable"
    mrbook = f_money(mr_eq) if mr_eq is not None else f_money(START_EQUITY)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    offline_banner = ("" if online else
        f'<div class="banner">⚠ Alpaca account unreachable ({html.escape(eq_err or "")}). '
        f'Live fills/equity omitted; benchmarks + structure still shown.</div>')

    cards = "\n".join(card(s) for s in strategies)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>iAPE — Combined Cockpit</title>
<style>
:root{{--bg:#0b0e14;--panel:#141922;--panel2:#1b2230;--ink:#e6edf3;--dim:#8b98a9;
--line:#232c3b;--amber:#f0a848;--teal:#3fd0c9;--green:#4ec97a;--red:#e5646e;--blue:#6ea8fe;}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#12203a 0,transparent 60%),var(--bg);
color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:26px}}
h1{{font-size:20px;margin:0;letter-spacing:.3px}}
.top{{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;margin-bottom:18px}}
.sub{{color:var(--dim);font-size:12.5px;margin-top:4px}}
.kpis{{display:flex;gap:22px;flex-wrap:wrap}}
.kpi .v{{font-size:19px;font-weight:600}} .kpi .l{{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.6px}}
.thesis{{background:linear-gradient(90deg,rgba(78,201,122,.10),rgba(240,168,72,.06));
border:1px solid var(--line);border-left:3px solid var(--green);border-radius:10px;
padding:13px 16px;margin:0 0 18px;font-size:13px}}
.thesis b{{color:var(--green)}}
.banner{{background:rgba(229,100,110,.12);border:1px solid rgba(229,100,110,.4);
border-radius:8px;padding:9px 13px;margin-bottom:14px;font-size:12.5px;color:#ffd7da}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}}
.card{{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
border-radius:14px;padding:16px 16px 14px;border-top:3px solid var(--line)}}
.card.mom5m{{border-top-color:var(--amber)}} .card.momD{{border-top-color:var(--teal)}}
.card.mr{{border-top-color:var(--green)}}
.chead{{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}}
.cname{{font-size:16px;font-weight:650}} .csub{{color:var(--dim);font-size:11.5px;margin-top:2px}}
.ctags{{display:flex;flex-direction:column;gap:5px;align-items:flex-end}}
.pill{{font-size:10px;font-weight:700;letter-spacing:.5px;padding:3px 8px;border-radius:20px;white-space:nowrap}}
.pill.real{{background:rgba(110,168,254,.16);color:var(--blue)}}
.pill.shadow{{background:rgba(139,152,169,.16);color:var(--dim)}}
.st-audit{{background:rgba(240,168,72,.16);color:var(--amber)}}
.st-ok{{background:rgba(78,201,122,.16);color:var(--green)}}
.st-soft{{background:rgba(110,168,254,.16);color:var(--blue)}}
.st-fail{{background:rgba(229,100,110,.18);color:var(--red)}}
.edge{{margin:12px 0 12px;display:flex;gap:6px;flex-wrap:wrap}}
.tag{{font-size:10.5px;padding:3px 9px;border-radius:6px;background:rgba(255,255,255,.05);color:var(--ink)}}
.tag.ghost{{background:transparent;border:1px dashed var(--line);color:var(--dim)}}
.metrics{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line);
border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.metric{{background:var(--panel);padding:10px 12px}}
.metric:first-child{{grid-column:1/3;background:rgba(255,255,255,.02)}}
.metric:first-child .mval{{font-size:30px}}
.mlbl{{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.6px}}
.mval{{font-size:18px;font-weight:650;margin-top:2px}}
.mbench{{color:var(--dim);font-size:10.5px;margin-top:1px}}
.open{{color:var(--dim);font-size:11.5px;margin:11px 0 8px}}
.cnote{{font-size:12px;color:#c6d2e0;border-top:1px solid var(--line);padding-top:9px}}
.cbook{{font-size:10.5px;color:var(--dim);margin-top:6px;font-style:italic}}
.foot{{margin-top:20px;color:var(--dim);font-size:11.5px;border-top:1px solid var(--line);padding-top:12px}}
.foot code{{background:var(--panel2);padding:1px 6px;border-radius:5px;color:var(--ink)}}
.refbanner{{background:linear-gradient(90deg,rgba(110,168,254,.13),rgba(63,208,201,.05));
border:1px solid rgba(110,168,254,.4);border-left:3px solid var(--blue);border-radius:10px;
padding:12px 16px;margin:0 0 18px;font-size:13px}}
.refbanner b{{color:var(--blue)}}
.section-h{{font-size:12px;text-transform:uppercase;letter-spacing:.7px;color:var(--dim);
margin:8px 0 10px;font-weight:600}}
.board-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:12px}}
.board{{width:100%;border-collapse:collapse;background:var(--panel);font-size:13px;min-width:640px}}
.board th{{text-align:left;color:var(--dim);font-size:10px;text-transform:uppercase;
letter-spacing:.5px;padding:9px 12px;border-bottom:1px solid var(--line);
background:rgba(255,255,255,.02);white-space:nowrap}}
.board td{{padding:11px 12px;border-bottom:1px solid var(--line);white-space:nowrap}}
.board tr:last-child td{{border-bottom:none}}
.board td.sym{{font-weight:700;font-size:14px}}
.board td.dim{{color:var(--dim)}}
.board td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.board td.stop{{color:var(--red)}} .board td.tgt{{color:var(--green)}}
.kp{{font-size:9.5px;font-weight:700;letter-spacing:.5px;padding:3px 8px;border-radius:20px;white-space:nowrap}}
.kp.open{{background:rgba(78,201,122,.16);color:var(--green)}}
.kp.queued{{background:rgba(240,168,72,.16);color:var(--amber)}}
.board-empty{{background:var(--panel);border:1px dashed var(--line);border-radius:12px;
padding:18px;color:var(--dim);font-size:13px}}
</style></head><body>

<div class="top">
  <div><h1>iAPE — Combined Cockpit</h1>
       <div class="sub">Reference dashboard · places no orders · updated {stamp}</div></div>
  <div class="kpis">
    <div class="kpi"><div class="v">{acct}</div><div class="l">Paper account (2 momentum tracks)</div></div>
    <div class="kpi"><div class="v">{mrbook}</div><div class="l">MR shadow book</div></div>
    <div class="kpi"><div class="v">{total_closed}</div><div class="l">Closed trades (all tracks)</div></div>
  </div>
</div>

{offline_banner}

<div class="refbanner">
  <b>Reference only — this dashboard does not trade.</b> It reads the validated
  system's live book and shows you the exact levels it is working. Nothing here
  sends an order; you decide what to place, and you place it yourself in your own
  broker. The levels below are what the tracked strategies are acting on right now.
</div>

<div class="section-h">What the system says right now</div>
{action_html}
<div class="sub" style="margin:8px 0 4px">
  Entry / stop / target are the system's levels. <b>Risk</b> is the stop distance
  as a % of entry — size each trade to your own account off that, not the bot's
  share count. <span style="color:var(--dim)">* Bot qty is the paper-account size;
  shown for reference only.</span>
</div>

<div class="thesis">
  <b>Where your win rate comes from:</b> {wr}. The high win rate lives in
  <b>mean-reversion</b>, by construction — not in the momentum tracks, whose edge
  is their fat-tail winners. Raising win rate on momentum (comfort exits) was
  measured at <b>−$5,000</b>. This cockpit grows your green by <b>running the
  high-win-rate edge alongside</b> the momentum core — the validated 50/50 stack
  (SP-D + MR) had the best MAR of anything tested (0.30 vs 0.18 / 0.27 solo).
  Portfolio unlocks when MR-1 clears its audition (≥30 shadow trades).
  <span style="color:var(--dim)">* benchmark shown until live trades accrue.</span>
</div>

<div class="grid">
{cards}
</div>

<div class="foot">
  Feed health: {html.escape(health_line)}<br>
  This dashboard is <b>read-only</b>: it reads <code>forward_state.json</code> and
  the event log and places no orders. Metric math reused from
  <code>forward_review.py</code> (the Friday referee) so this view can't disagree
  with the official verdict. MR-1 is SHADOW — no real orders — until it graduates.
  Regenerate anytime: <code>py cockpit.py</code>. Not financial advice.
</div>
</body></html>"""


def main():
    lg, online, err = load_log()
    equity, eq_err = account_equity()
    _, mr_eq = load_mr()
    strategies = build_strategies(lg)
    rows = action_rows(read_state())
    doc = render(strategies, equity, eq_err or err, mr_eq,
                 health(lg), online and equity is not None, action_board(rows))
    OUT.write_text(doc, encoding="utf-8")

    print(f"Cockpit -> {OUT}")
    print(f"  account: {'$%.2f' % equity if equity is not None else 'unreachable'}"
          f" · online: {online}")
    for s in strategies:
        st = s["s"]
        print(f"  {s['name']:<16} n={st['n']:>3}  win={f_pct(st['win']):>6}"
              f"  pf={f_pf(st['pf']):>5}  net={f_money(st['net']):>10}"
              f"  [{'REAL' if s['real'] else 'SHADOW'}]")
    print("  --- reference levels (place manually; dashboard trades nothing) ---")
    if rows:
        for r in rows:
            print(f"  {r['kind']:<6} {r['sym']:<5} {r['track']:<15} "
                  f"entry ${r['entry']:.2f}  stop ${r['stop']:.2f}  "
                  f"tgt ${r['target']:.2f}  ({r['when']})")
    else:
        print("  (flat — nothing open or queued)")
    if "--open" in sys.argv:
        webbrowser.open(OUT.as_uri())


if __name__ == "__main__":
    main()
