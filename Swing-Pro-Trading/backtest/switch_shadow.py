"""
switch_shadow.py — SWITCH-policy SHADOW forward audition. No orders, ever.

What this tracks: the regime-switch policy from run_switch_vs_parallel.py
(2026-07-09) — hold the momentum portfolio (SWING_PRO-D) when SPY closed above
a RISING 50d SMA on the prior session, else hold the MR-1 portfolio. In-sample
it beat PARALLEL 50/50 by +59.7% MAR (0.369 vs 0.231), robust across four
trend classifiers. This shadow forward-runs the EXACT same comparison on data
that did not exist when the rule was registered.

PRE-REGISTERED (fixed 2026-07-11, before any forward data):
  * AUDITION_START = 2026-07-13 — the first session unknown at registration.
  * Primary metric: MAR(switch) vs MAR(parallel 50/50) on the forward window.
  * Bar (same as in-sample): SWITCH wins only if forward MAR > parallel
    MAR x 1.10. Otherwise parallel/simpler wins and the switcher is buried.
  * Judgment: >= 126 forward sessions (~6 months) MINIMUM — MAR on short
    windows is noise. Adoption is FURTHER gated behind both engines' own
    >= 30-trade auditions (house rule #3); this shadow only accumulates
    evidence, it promotes nothing by itself.
  * Secondary (reported, not decisive): regime-flip count (whipsaw monitor),
    % of days holding momentum, forward momentum-MR return correlation.
  * Classifier is FROZEN as registered: SPY close > 50d SMA AND
    sma50 > sma50 five sessions ago, decided on the PRIOR close. No lookahead,
    no re-tuning mid-audition.

Design: DETERMINISTIC DAILY RECOMPUTE (same architecture as mr_forward.py).
Every run re-executes BOTH validated engines as portfolios from AUDITION_START
on freshly fetched bars (warmup only feeds indicators), rebuilds the switch and
parallel curves, and rewrites outputs wholesale (idempotent, drift-proof):
  reports/switch_shadow.md    — audition dashboard
  switch_shadow_equity.csv    — daily curves (momentum/mr/parallel/switch)
Universe/sizing identical to the registered test: the 22-name 30y basket,
$100k pool per engine, 10% sizing, max 10 concurrent. Shadow-only is fine on
overlapping symbols (no orders). yfinance retro-adjustment caveat as MR shadow.

Scheduled: SwingPro_Switch_Shadow, daily 13:45 PT (after SwingPro_MR_Shadow).
Weekend/holiday runs are harmless no-ops.
Usage:  py switch_shadow.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import indicators as ta
from swing_pro import config_v22, run as run_momentum
from mean_rev import MRConfig, run_portfolio
from run_daily_30y import SYMBOLS

HERE = Path(__file__).parent
REPORTS = HERE / "reports"
AUDITION_START = pd.Timestamp("2026-07-13")
FETCH_START = "2025-01-02"            # ~380 sessions of indicator warmup
INIT, ALLOC_PCT, MAX_POS = 100_000.0, 10.0, 10   # the registered contract
BENCH = {"insample_switch_mar": 0.369, "insample_parallel_mar": 0.231,
         "margin": 1.10, "min_sessions": 126}


def fetch_all() -> tuple[dict[str, pd.DataFrame], pd.DataFrame | None]:
    import yfinance as yf
    raw = yf.download(" ".join(SYMBOLS + ["SPY"]), start=FETCH_START,
                      interval="1d", auto_adjust=False, progress=False,
                      group_by="ticker", threads=True)
    dfs, spy = {}, None
    for s in SYMBOLS + ["SPY"]:
        try:
            df = raw[s].rename(columns=str.lower)[
                ["open", "high", "low", "close", "volume"]].dropna(
                subset=["open", "high", "low", "close"])
            df.index = pd.DatetimeIndex(df.index).tz_localize(None)
            if len(df) < 220:
                print(f"  {s}: only {len(df)} bars — skipped this run")
                continue
            if s == "SPY":
                spy = df
            else:
                dfs[s] = df
        except Exception as e:
            print(f"  {s}: fetch failed ({e}) — skipped this run")
    return dfs, spy


def _naive(t):
    ts = pd.Timestamp(t)
    return ts.tz_localize(None) if ts.tzinfo else ts


def momentum_portfolio(symbol_dfs: dict, spy: pd.DataFrame,
                       start: pd.Timestamp) -> pd.Series:
    """run_switch_vs_parallel.momentum_portfolio with a `start` gate:
    engine runs on full history (warmup), but only trades ENTERED on/after
    `start` replay through the pool, and the curve begins at `start`."""
    cfg = config_v22(trade_dir="long", use_htf_trend=False)
    trades = []
    for sym, df in symbol_dfs.items():
        r = run_momentum(df, spy, cfg)
        for t in r["trades"]:
            if t.get("pnl") is None or not t.get("qty"):
                continue
            if _naive(t["entry_time"]) < start:
                continue
            notional = float(t["entry_fill"]) * float(t["qty"])
            if notional <= 0:
                continue
            trades.append({"symbol": sym,
                           "entry": _naive(t["entry_time"]),
                           "exit": _naive(t["exit_time"]),
                           "entry_fill": float(t["entry_fill"]),
                           "pct": float(t["pnl"]) / notional})
    entries_by, exits_by = {}, {}
    for i, t in enumerate(trades):
        entries_by.setdefault(t["entry"], []).append(i)
        exits_by.setdefault(t["exit"], []).append(i)

    calendar = sorted(d for d in set().union(
        *[set(df.index) for df in symbol_dfs.values()]) if d >= start)
    closes = {s: df["close"] for s, df in symbol_dfs.items()}

    def mark(sym, ts, fallback):
        try:
            return float(closes[sym].loc[ts])
        except KeyError:
            return fallback

    cash, open_pos = INIT, {}
    eq_vals, eq_dates = [], []
    for ts in calendar:
        for i in exits_by.get(ts, []):
            if i in open_pos:
                p = open_pos.pop(i)
                notional = p["entry_fill"] * p["qshares"]
                cash += notional + notional * trades[i]["pct"]
        marked = cash + sum(p["qshares"] * mark(p["symbol"], ts, p["entry_fill"])
                            for p in open_pos.values())
        for i in sorted(entries_by.get(ts, []), key=lambda k: trades[k]["symbol"]):
            if len(open_pos) >= MAX_POS:
                break
            notional = (ALLOC_PCT / 100.0) * marked
            if notional <= 0 or notional > cash:
                continue
            cash -= notional
            open_pos[i] = {"symbol": trades[i]["symbol"],
                           "qshares": notional / max(trades[i]["entry_fill"], 1e-9),
                           "entry_fill": trades[i]["entry_fill"]}
        mv = sum(p["qshares"] * mark(p["symbol"], ts, p["entry_fill"])
                 for p in open_pos.values())
        eq_vals.append(cash + mv)
        eq_dates.append(ts)
    return pd.Series(eq_vals, index=pd.DatetimeIndex(eq_dates), name="momentum")


def stats_from_curve(eq: pd.Series) -> dict:
    ret = eq.pct_change().fillna(0.0)
    peak = eq.cummax()
    dd = float(((eq - peak) / peak).min() * 100)
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    cagr = float(((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1) * 100)
    return {"CAGR%": round(cagr, 2), "maxDD%": round(dd, 2),
            "MAR": round(cagr / abs(dd), 3) if dd < 0 else np.nan,
            "final$": round(float(eq.iloc[-1]))}


def main():
    REPORTS.mkdir(exist_ok=True)
    dfs, spy = fetch_all()
    if not dfs or spy is None:
        print("no data — aborting without touching outputs")
        return
    last_bar = max(d.index[-1] for d in dfs.values())
    live = last_bar >= AUDITION_START

    # regime series, frozen classifier, decided on prior close
    spy_c = spy["close"]
    sma50 = pd.Series(ta.sma(spy_c.to_numpy(float), 50), index=spy_c.index)
    trend_raw = (spy_c > sma50) & (sma50 > sma50.shift(5))

    if live:
        mom_eq = momentum_portfolio(dfs, spy, AUDITION_START)
        mr = run_portfolio(dfs, MRConfig(), start=AUDITION_START)
        mr_eq = mr["equity"]
        idx = mom_eq.index.intersection(mr_eq.index)
        idx = idx[idx >= AUDITION_START]
        mom_eq, mr_eq = mom_eq.reindex(idx).ffill(), mr_eq.reindex(idx).ffill()
        mom_ret = mom_eq.pct_change().fillna(0.0)
        mr_ret = mr_eq.pct_change().fillna(0.0)
        # same order of operations as the registered test: reindex, then shift
        trend = trend_raw.reindex(idx).shift(1).fillna(False).astype(bool)
        sw_ret = pd.Series(np.where(trend.to_numpy(), mom_ret.to_numpy(),
                                    mr_ret.to_numpy()), index=idx)
        par_ret = 0.5 * mom_ret + 0.5 * mr_ret
        sw_eq = INIT * (1.0 + sw_ret).cumprod()
        par_eq = INIT * (1.0 + par_ret).cumprod()
        flips = int(trend.astype(int).diff().abs().sum())
        n_sess = len(idx)
        corr = float(mom_ret.corr(mr_ret)) if n_sess > 2 else np.nan
        pd.DataFrame({"momentum": mom_eq, "mr": mr_eq, "parallel": par_eq,
                      "switch": sw_eq, "in_momentum": trend.astype(int)}
                     ).to_csv(HERE / "switch_shadow_equity.csv")
    else:
        n_sess, flips, corr = 0, 0, np.nan

    regime_now = bool(trend_raw.iloc[-1])
    can_judge = n_sess >= BENCH["min_sessions"]
    mar_ok = n_sess >= 60          # below this, MAR is pure noise — don't print

    out = REPORTS / "switch_shadow.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# SWITCH-policy shadow audition — refreshed {date.today().isoformat()}\n\n")
        f.write(f"Status: **{'LIVE' if live else 'ARMED'}** · audition start "
                f"{AUDITION_START.date()} · last completed bar {last_bar.date()} · "
                f"{len(dfs)}/{len(SYMBOLS)} symbols · SHADOW ONLY — no orders.\n\n")
        f.write("Registered 2026-07-11: forward MAR(switch) must beat "
                "MAR(parallel 50/50) by >10% at >=126 sessions (in-sample: "
                f"{BENCH['insample_switch_mar']} vs {BENCH['insample_parallel_mar']}, "
                "+59.7%). Adoption further gated behind both engines' >=30-trade "
                "auditions. Classifier frozen: SPY > rising 50d, prior close.\n\n")
        f.write(f"**Regime right now: {'MOMENTUM (SPY above rising 50d)' if regime_now else 'MEAN-REVERSION (SPY not in uptrend)'}**\n\n")
        if live and n_sess:
            rows = []
            for name, eq in (("Momentum only", mom_eq), ("MR only", mr_eq),
                             ("PARALLEL 50/50", par_eq), ("SWITCH (regime)", sw_eq)):
                st = stats_from_curve(eq)
                if not mar_ok:
                    st["MAR"] = "(too early)"
                rows.append({"track": name, **st})
            judge_lbl = "judgeable" if can_judge \
                else f"judge at {BENCH['min_sessions']} sessions"
            f.write(f"## Forward window — {n_sess} sessions ({judge_lbl})\n\n")
            f.write(pd.DataFrame(rows).to_markdown(index=False))
            f.write(f"\n\nRegime flips so far: {flips} · days in momentum: "
                    f"{100 * float(trend.mean()):.0f}% · forward momentum-MR "
                    f"corr: {corr:+.2f}\n" if n_sess > 2 else "\n")
            if can_judge:
                sw_mar = stats_from_curve(sw_eq)["MAR"]
                par_mar = stats_from_curve(par_eq)["MAR"]
                win = isinstance(sw_mar, float) and isinstance(par_mar, float) \
                    and par_mar > 0 and sw_mar > par_mar * BENCH["margin"]
                f.write(f"\n**VERDICT-READY: switch MAR {sw_mar} vs parallel "
                        f"{par_mar} -> {'SWITCH holds up' if win else 'SWITCH fails forward — bury it'}**\n")
        else:
            f.write("*(armed — first forward session not yet complete)*\n")
        f.write("\n*Deterministic recompute from audition start each run; engines "
                "= swing_pro/mean_rev exactly as validated; sizing contract "
                "identical to the registered in-sample test. Not financial "
                "advice.*\n")

    print(f"Switch shadow: {'LIVE' if live else 'ARMED'} · last bar "
          f"{last_bar.date()} · {n_sess} forward sessions · regime now: "
          f"{'momentum' if regime_now else 'MR'} · flips: {flips}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
