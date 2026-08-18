"""
run_gap_risk.py — GAP-THROUGH-STOP measurement for SWING_PRO-D (pre-registered).

The daily backtests fill stops AT the stop level whenever low <= stop. Overnight
gaps violate that: if the session OPENS below the stop, the real fill is ~the
open, not the stop. Same thing (favorably) for the 3R target when the open gaps
above it. This study REPRICES every stop/target exit of the validated engine at
gap-aware fills and measures the difference. MEASUREMENT ONLY — no strategy
change, no new mining (identical trades to the validated config; only exit
prices move).

Pre-registered metrics (fixed before running):
  M1  stop-gap rate: % of stop exits where the exit-day open < stop level
  M2  slippage per gapped stop: mean/median/worst, in R and in % of entry
  M3  target-gap rate + favorable slippage (same measures)
  M4  repriced PF/net vs reported: full 30y, D1/D2/D3, and the LIVE window
      (13-name control basket, entries >= 2021-07-01; registered PF 1.72)
  M5  tail: stops costing > 1R extra vs backtest; worst single trade

Interpretation bar (stated in advance of the run):
  live-window repriced PF < 1.50 -> forward-test benchmark gets a footnote;
  live-window repriced PF < 1.15 -> the daily validation itself is in question.

Repricing keeps each trade's ORIGINAL qty (no compounding feedback) — this
isolates per-trade gap cost; the portfolio compounding effect is second-order.

Usage: py run_gap_risk.py            (data: cached 30y yfinance parquets)
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from run_daily_30y import SYMBOLS, fetch_daily, D1, D2
from swing_pro import config_v22, run

REPORTS = Path(__file__).parent / "reports"
CONTROL = ["JPM", "GS", "XOM", "CVX", "CAT", "DE", "BA",
           "WMT", "COST", "HD", "UNH", "DIS", "KO"]
LIVE_START = pd.Timestamp("2021-07-01")


def reprice_trades(sym: str, df: pd.DataFrame, trades: list[dict],
                   slip: float, comm: float) -> list[dict]:
    """Attach gap-aware exit pricing to each single-exit trade."""
    out = []
    o = df["open"].to_numpy(float)
    for t in trades:
        if len(t["exits"]) != 1:      # v2.2 has no partials; guard anyway
            continue
        ex_time, old_fill, qty, reason = t["exits"][0]
        rec = {"symbol": sym, "entry_time": t["entry_time"],
               "exit_time": ex_time, "reason": reason, "qty": qty,
               "entry_fill": t["entry_fill"], "risk": t["risk"],
               "old_pnl": t["pnl"], "new_pnl": t["pnl"],
               "gapped": False, "delta": 0.0, "delta_r": 0.0}
        if reason in ("stop", "target"):
            bar = df.index.get_loc(pd.Timestamp(ex_time))
            opn = o[bar]
            # reconstruct the order level from the recorded fill:
            # stop = market sell, fill = level - slip; target = limit, fill = level
            level = old_fill + slip if reason == "stop" else old_fill
            new_fill = old_fill
            if reason == "stop" and opn < level:        # gapped through the stop
                new_fill = opn - slip
            elif reason == "target" and opn > level:    # gapped past the target
                new_fill = opn
            if new_fill != old_fill:
                ef = t["entry_fill"]
                old_pnl = (old_fill - ef) * qty - (abs(old_fill) + abs(ef)) * qty * comm
                new_pnl = (new_fill - ef) * qty - (abs(new_fill) + abs(ef)) * qty * comm
                rec.update(gapped=True, new_pnl=t["pnl"] + (new_pnl - old_pnl),
                           delta=new_pnl - old_pnl,
                           delta_r=(new_pnl - old_pnl) / (t["risk"] * qty)
                                   if t["risk"] > 0 else np.nan,
                           gap_pct=100.0 * (new_fill - old_fill) / ef,
                           open_px=opn, level=level)
        out.append(rec)
    return out


def pf(pnls: np.ndarray) -> float:
    w, l = pnls[pnls > 0], pnls[pnls <= 0]
    return float(w.sum() / -l.sum()) if l.sum() < 0 else np.inf


def block(rows: list[dict], label: str) -> dict:
    old = np.array([r["old_pnl"] for r in rows])
    new = np.array([r["new_pnl"] for r in rows])
    return {"window": label, "n": len(rows),
            "pf_reported": round(pf(old), 3) if len(rows) else np.nan,
            "pf_gap_aware": round(pf(new), 3) if len(rows) else np.nan,
            "net_reported": round(float(old.sum())) if len(rows) else 0,
            "net_gap_aware": round(float(new.sum())) if len(rows) else 0}


def era_of(r: dict) -> str:
    ts = pd.Timestamp(r["entry_time"])
    ts = ts.tz_localize(None) if ts.tzinfo else ts
    return "D1" if ts < D1 else ("D2" if ts < D2 else "D3")


def main():
    REPORTS.mkdir(exist_ok=True)
    spy = fetch_daily("SPY")
    cfg = config_v22(trade_dir="long", use_htf_trend=False)
    slip = cfg.slippage_ticks * cfg.tick_size
    comm = cfg.commission_pct / 100.0

    recs: list[dict] = []
    for s in SYMBOLS:
        try:
            df = fetch_daily(s)
        except Exception as e:
            print(f"  {s}: FAILED ({e})")
            continue
        r = run(df, spy, cfg)
        recs += reprice_trades(s, df, r["trades"], slip, comm)
        print(f"  {s}: {len(r['trades'])} trades")

    stops = [r for r in recs if r["reason"] == "stop"]
    tgts = [r for r in recs if r["reason"] == "target"]
    gstops = [r for r in stops if r["gapped"]]
    gtgts = [r for r in tgts if r["gapped"]]

    # M1/M2 — stops
    sd = np.array([r["delta_r"] for r in gstops])          # negative = extra loss
    sp = np.array([r["gap_pct"] for r in gstops])
    # M3 — targets
    td = np.array([r["delta_r"] for r in gtgts])           # positive = bonus
    tp_ = np.array([r["gap_pct"] for r in gtgts])
    # M5 — tail
    tail = sorted(gstops, key=lambda r: r["delta_r"])[:10]
    n_1r = int((sd <= -1.0).sum())

    # M4 — windows
    blocks = [block(recs, "FULL 30y (22 symbols)")]
    for e, lab in (("D1", "D1 1995-2005"), ("D2", "D2 2005-2015"),
                   ("D3", "D3 2015-2026")):
        blocks.append(block([r for r in recs if era_of(r) == e], lab))
    live = [r for r in recs if r["symbol"] in CONTROL
            and pd.Timestamp(r["entry_time"]) >= LIVE_START]
    blocks.append(block(live, "LIVE window (control basket, 2021-07+)"))
    live_pf = blocks[-1]["pf_gap_aware"]

    verdict = ("CLEAR — benchmark stands"
               if live_pf >= 1.50 else
               "FOOTNOTE — forward benchmark optimistic, annotate it"
               if live_pf >= 1.15 else
               "ALARM — daily validation in question")

    lines = [
        f"# SWING_PRO-D gap-through-stop study — {date.today().isoformat()}",
        "",
        "Measurement only: the validated v2.2-D trades repriced with gap-aware",
        "exit fills (stop exits fill at the open when the session opens through",
        "the stop; 3R targets fill at the open when it gaps past — favorable).",
        "Same trades, same qty. Pre-registered metrics M1-M5; bars: live-window",
        "repriced PF <1.50 -> footnote, <1.15 -> validation in question.",
        "",
        f"## Verdict: **{verdict}** (live-window gap-aware PF {live_pf})",
        "",
        "## M1-M3 — gap rates and slippage",
        "",
        f"- Stop exits: {len(stops)}; gapped through: {len(gstops)} "
        f"(**{100 * len(gstops) / max(len(stops), 1):.1f}%**)",
        f"- Extra loss per gapped stop: mean {sd.mean():+.3f}R / median "
        f"{np.median(sd):+.3f}R / worst {sd.min():+.3f}R"
        if len(gstops) else "- (no gapped stops)",
        f"- In % of entry price: mean {sp.mean():+.2f}% / worst {sp.min():+.2f}%"
        if len(gstops) else "",
        f"- Target exits: {len(tgts)}; gapped past: {len(gtgts)} "
        f"({100 * len(gtgts) / max(len(tgts), 1):.1f}%)",
        f"- Bonus per gapped target: mean {td.mean():+.3f}R / best {td.max():+.3f}R"
        if len(gtgts) else "- (no gapped targets)",
        "",
        "## M4 — reported vs gap-aware",
        "",
        pd.DataFrame(blocks).to_markdown(index=False),
        "",
        "## M5 — tail (worst gapped stops)",
        "",
        f"Gapped stops costing > 1R extra: **{n_1r}** "
        f"of {len(stops)} stop exits "
        f"({100 * n_1r / max(len(stops), 1):.2f}%)",
        "",
        pd.DataFrame([{k: r.get(k) for k in
                       ("symbol", "exit_time", "level", "open_px",
                        "delta_r", "delta")} for r in tail]
                     ).to_markdown(index=False) if tail else "(none)",
        "",
        "*Repricing uses original per-trade qty (no compounding feedback).",
        "yfinance split-adjusted daily bars, same cache as the 30y run.",
        "Entries already fill at the open in the engine — no entry-side bias.*",
    ]
    out = REPORTS / f"gap_risk_{date.today().isoformat()}.md"
    out.write_text("\n".join(str(x) for x in lines), encoding="utf-8")

    print("\n".join(str(x) for x in lines[2:]))
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
