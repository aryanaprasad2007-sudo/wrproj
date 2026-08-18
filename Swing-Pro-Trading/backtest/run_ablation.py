"""
run_ablation.py — which SWING_PRO filters actually earn their keep?

Runs the ported strategy on the validation basket (AAPL NVDA TSLA MSFT META, 5m,
SPY as the market-filter reference), first as-configured (baseline), then with each
filter knocked out ONE at a time. If removing a filter doesn't hurt — or helps —
across the whole basket, that filter is curve-fit decoration, not edge.

Also ablates the EXIT layer (condition exits vs pure stop/target, partials,
breakeven) because the realized R:R is set there, not in the entries.

Outputs:
  backtest/reports/ablation_<date>.md   — ranked summary tables
  backtest/reports/trades_<sym>_baseline.csv — trade lists (for TradingView parity)

Usage:  py run_ablation.py [--days 59] [--dir both|long|short]
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_bars
from swing_pro import Config, run

BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]
REPORTS = Path(__file__).parent / "reports"

# name -> (Config overrides, what it tests)
VARIANTS: dict[str, tuple[dict, str]] = {
    "baseline":            ({}, "all defaults, as shipped"),
    "no_trend_gate":       ({"use_trend": False}, "drop price-vs-HTF-trend gate"),
    "no_slope":            ({"use_slope": False}, "drop flat-market (slope) filter"),
    "no_macd":             ({"use_macd": False}, "drop MACD entry gate"),
    "no_impulse":          ({"use_impulse": False}, "drop Impulse MACD gate"),
    "no_rsi_band":         ({"use_rsi": False}, "drop RSI 52/48 band gate"),
    "no_adx":              ({"use_adx": False}, "drop ADX strength filter"),
    "no_volume":           ({"use_vol": False}, "drop above-average-volume filter"),
    "no_market_filter":    ({"use_market_filter": False}, "drop SPY alignment"),
    "no_candle_color":     ({"use_candle": False}, "drop green/red entry-bar rule"),
    "no_anti_chase":       ({"use_avoid_ext": False}, "drop RSI-extreme veto"),
    "exit_stop_tgt_only":  ({"exit_on_macd": False, "exit_on_trend": False},
                            "pure stop/target exits (no condition exits)"),
    "exit_no_macd_flip":   ({"exit_on_macd": False}, "keep trend exit, drop MACD-flip exit"),
    "no_partial":          ({"use_partial": False}, "no TP1 scale-out"),
    "no_breakeven":        ({"use_breakeven": False}, "no breakeven stop move"),
}


def agg_stats(results: dict[str, dict]) -> dict:
    """Aggregate one variant across the basket."""
    all_trades = [t for r in results.values() for t in r["trades"]]
    pnls = np.array([t["pnl"] for t in all_trades]) if all_trades else np.array([])
    rs = np.array([t["r"] for t in all_trades if not np.isnan(t.get("r", np.nan))])
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls <= 0] if len(pnls) else np.array([])
    dd = min((r["stats"]["max_dd_pct"] for r in results.values()), default=0.0)
    pos_syms = sum(1 for r in results.values() if r["stats"]["net_profit"] > 0)
    return {
        "trades": len(all_trades),
        "net_usd": float(pnls.sum()) if len(pnls) else 0.0,
        "exp_r": float(rs.mean()) if len(rs) else np.nan,
        "win_%": float(len(wins) / len(pnls) * 100) if len(pnls) else np.nan,
        "pf": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else np.nan,
        "worst_dd_%": dd,
        "profitable_syms": f"{pos_syms}/{len(results)}",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=59)
    ap.add_argument("--dir", default="both", choices=["both", "long", "short"])
    args = ap.parse_args()

    REPORTS.mkdir(exist_ok=True)
    print(f"Loading 5m bars ({args.days}d): SPY + {', '.join(BASKET)} ...")
    spy = load_bars("SPY", args.days)
    bars = {s: load_bars(s, args.days) for s in BASKET}
    for s, df in bars.items():
        print(f"  {s}: {len(df)} bars  {df.index[0].date()} → {df.index[-1].date()}"
              f"  [{df.attrs.get('source', 'cache')}]")

    base_cfg = Config(trade_dir=args.dir)
    table_rows = []
    baseline_by_sym = {}

    for name, (ovr, desc) in VARIANTS.items():
        results = {s: run(bars[s], spy, base_cfg, **ovr) for s in BASKET}
        a = agg_stats(results)
        a["variant"], a["tests"] = name, desc
        table_rows.append(a)
        print(f"  {name:<22} trades={a['trades']:<4} netUSD={a['net_usd']:>10.0f} "
              f"expR={a['exp_r']:>6.3f} win%={a['win_%']:>5.1f} pf={a['pf']:>5.2f} "
              f"syms+={a['profitable_syms']}")
        if name == "baseline":
            baseline_by_sym = results
            for s, r in results.items():
                rows = []
                for t in r["trades"]:
                    rows.append({
                        "side": t["side"], "entry_time": t["entry_time"],
                        "entry_fill": round(t["entry_fill"], 4),
                        "qty": round(t["qty"], 2),
                        "exit_time": t.get("exit_time"),
                        "exit_reason": t["exits"][-1][3] if t["exits"] else "",
                        "n_fills": len(t["exits"]),
                        "pnl": round(t["pnl"], 2), "r": round(t.get("r", np.nan), 3),
                    })
                pd.DataFrame(rows).to_csv(REPORTS / f"trades_{s}_baseline.csv", index=False)

    # ── markdown report ──────────────────────────────────────────────────────
    tbl = pd.DataFrame(table_rows)
    base = tbl[tbl.variant == "baseline"].iloc[0]
    tbl["Δnet_vs_base"] = tbl["net_usd"] - base["net_usd"]
    tbl["ΔexpR_vs_base"] = tbl["exp_r"] - base["exp_r"]
    cols = ["variant", "tests", "trades", "net_usd", "Δnet_vs_base",
            "exp_r", "ΔexpR_vs_base", "win_%", "pf", "worst_dd_%", "profitable_syms"]
    tbl = tbl[cols]

    per_sym = pd.DataFrame({
        s: {"trades": r["stats"]["trades"],
            "net_usd": round(r["stats"]["net_profit"], 0),
            "net_%": round(r["stats"].get("net_pct", np.nan), 2),
            "win_%": round(r["stats"]["win_rate"], 1),
            "pf": round(r["stats"]["profit_factor"], 2),
            "exp_R": round(r["stats"]["expectancy_r"], 3),
            "maxDD_%": round(r["stats"]["max_dd_pct"], 2)}
        for s, r in baseline_by_sym.items()
    }).T

    out = REPORTS / f"ablation_{date.today().isoformat()}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# SWING_PRO ablation study — {date.today().isoformat()}\n\n")
        f.write(f"Basket: {', '.join(BASKET)} · 5m bars · {args.days}d window · "
                f"direction={args.dir} · market ref=SPY\n\n")
        f.write("**How to read this:** each row removes ONE component from the baseline. "
                "If `Δnet_vs_base` and `ΔexpR_vs_base` are ≥ 0 with similar or more trades, "
                "the removed component was NOT adding edge on this window — candidate for "
                "deletion. If removing it clearly hurts, it earns its keep.\n\n")
        f.write("## Baseline per symbol\n\n")
        f.write(per_sym.to_markdown() + "\n\n")
        f.write("## Ablation (aggregated across basket)\n\n")
        f.write(tbl.round(3).to_markdown(index=False) + "\n\n")
        f.write("*Single 60-day window — treat as a first screen, not proof. "
                "Walk-forward across a longer Alpaca history is the confirmation step. "
                "Not financial advice.*\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
