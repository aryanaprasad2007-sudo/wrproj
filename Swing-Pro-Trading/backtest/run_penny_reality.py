"""
run_penny_reality.py -- what a sub-$5 book can and cannot do on Ari's REAL
Robinhood agentic account, over a trailing 30-day window.

WHY THIS IS NOT A BACKTEST
--------------------------
Ari selects penny names by his own AI-assisted research, not by a mechanical
rule. There is therefore NO rule to replay, and any "you would have made $X"
figure would be an invented strategy credited with invented returns. This
module refuses to produce that number. Instead it measures the three things
that are true regardless of which names he picks:

  1. WHAT THE UNIVERSE DID       -- the realized 30d return distribution of
                                    listed sub-$5 names. This is the null
                                    hypothesis: what a blindfolded pick made.
                                    His research has to beat THIS, not zero.
  2. WHAT FRICTION COSTS         -- real bid/ask on cheap stock, doubled for a
                                    round trip, against a $45 position. Drives
                                    the breakeven win rate at 3:1 payoff.
  3. HOW MANY SHOTS HE GETS      -- a CASH account settles T+1. Unsettled
                                    proceeds cannot be reused without a good
                                    faith violation, so the trade count over
                                    30 days is capped by settlement, not by
                                    how many ideas he has.

Then it runs a Monte Carlo that is explicitly a FUNCTION OF HIS SKILL: for
each hypothetical hit rate, the distribution of ending equity. That answers
"how much would I have made" honestly -- as a conditional, not a claim.

SURVIVORSHIP WARNING: the universe is built from names listed TODAY. Sub-$5
names that were delisted, reverse-split, or halted out of existence during the
window are absent by construction, which biases every universe statistic
OPTIMISTIC. Real blindfolded results would be worse than what this prints.

Usage:
    py -3.12 run_penny_reality.py [--book 225.37] [--days 30]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import forward_trader as ft

HERE = Path(__file__).parent
OUT = HERE / "cache" / "penny_reality.json"

# Candidate listed low-priced names. Deliberately broad and DISCLOSED -- the
# sub-$5 filter below is applied from data, not from this list. Anything that
# priced >= $5 at the window open is dropped and reported as excluded.
CANDIDATES = [
    "PLUG", "SNDL", "GEVO", "WKHS", "CLOV", "BBAI", "AMC", "NIO", "LCID", "CHPT",
    "TLRY", "ACB", "GRAB", "OPEN", "WULF", "CIFR", "BITF", "AUR", "LAZR", "MVIS",
    "EOSE", "BLNK", "EVGO", "QS", "DNN", "UEC", "NAK", "SPWR", "ENVX", "PTON",
    "RIG", "FCEL", "SOUN", "HTZ", "PSNY", "MARA", "RIOT", "VTRS", "F", "SIRI",
]

PRICE_CEILING = 5.00

# Measured round-trip friction bands (spread paid twice, market orders only --
# fractional cannot post inside the spread). Post-close quotes on 2026-08-17
# ranged 0.5% (RIG) to 9.4% (GEVO); intraday is tighter, so model a band.
FRICTION_BANDS = {"tight": 0.010, "typical": 0.025, "wide": 0.050}

# Payoff geometry copied from the validated engine: pure stop + 3R target.
RR = 3.0
STOP_PCT = 0.10          # a structural stop on a cheap, volatile name

SKILL_LEVELS = [0.20, 0.25, 0.30, 0.40, 0.50]
TRADE_COUNTS = [6, 12, 20]
N_SIMS = 20000


# A reverse split shows up in an UNADJUSTED feed as an overnight price jump
# with no trade behind it. Alpaca's daily bars are unadjusted, so MVIS printed
# 0.2659 -> 4.2000 across 2026-08-03 (1-for-15) and scored as +496% -- a
# corporate action wearing a return's name. Detected and back-adjusted here.
SPLIT_UP = 1.80          # overnight ratio above this = probable reverse split
SPLIT_DN = 0.55          # below this = probable forward split
THIN_VOLUME = 50_000     # median IEX daily volume below this = untrustworthy


def deconstruct_splits(df):
    """Back-adjust prior bars across detected corporate actions.

    Returns (adjusted_df, [events]). Standard back-adjustment: on a ratio r at
    bar i, every bar BEFORE i is multiplied by r so the series is continuous in
    today's share terms -- the same convention Robinhood's split-adjusted feed
    uses, which is what we verified against.
    """
    import numpy as _np
    d = df.copy()
    o = d["open"].to_numpy(dtype=float)
    c = d["close"].to_numpy(dtype=float)
    events = []
    for i in range(1, len(d)):
        if c[i - 1] <= 0:
            continue
        r = o[i] / c[i - 1]
        if r > SPLIT_UP or r < SPLIT_DN:
            events.append({"index": i, "date": str(d.index[i])[:10],
                           "ratio": round(float(r), 3)})
            for col in ("open", "high", "low", "close"):
                # pandas 3.0 copy-on-write hands back a READ-ONLY view here;
                # .copy() is required or the in-place scale raises.
                vals = d[col].to_numpy(dtype=float).copy()
                vals[:i] = vals[:i] * r
                d[col] = vals
            o = d["open"].to_numpy(dtype=float)
            c = d["close"].to_numpy(dtype=float)
    return d, events


def window_stats(days: int):
    """Realized return distribution of the sub-$5 universe over the window.

    `days` is CALENDAR days, not bars. An earlier version used df.tail(days),
    which silently meant 30 *trading* bars = 41 calendar days, while the
    settlement model computed sessions from 30 calendar days -- two different
    windows in one report. The cutoff is now a real date and the actual span
    is reported back so the label can never drift from the data again.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows, excluded, errors = [], [], []
    corporate_actions, thin = [], []
    frames = {}
    for sym in CANDIDATES:
        try:
            df = ft.daily_bars(sym, days + 40)
        except Exception as e:
            errors.append(f"{sym}: {str(e)[:60]}")
            continue
        if df is None or len(df) < 5:
            errors.append(f"{sym}: insufficient bars")
            continue

        df, events = deconstruct_splits(df)
        if events:
            corporate_actions.append({"symbol": sym, "events": events})

        sub = df[df.index.strftime("%Y-%m-%d") >= cutoff]
        med_vol = float(sub["volume"].median()) if len(sub) else 0.0
        if med_vol < THIN_VOLUME:
            # IEX-only feed sees a slice of consolidated volume; on thin names
            # that slice is too small to price against. Excluded, not silently
            # kept -- a stale print would read as a real level.
            thin.append({"symbol": sym, "median_iex_volume": int(med_vol)})
            continue
        if len(sub) < 5:
            errors.append(f"{sym}: only {len(sub)} bars in window")
            continue
        first = float(sub["open"].iloc[0])
        last = float(sub["close"].iloc[-1])
        if first >= PRICE_CEILING:
            excluded.append({"symbol": sym, "price": round(first, 2)})
            continue
        hi = float(sub["high"].max())
        lo = float(sub["low"].min())
        rows.append({
            "symbol": sym,
            "start": round(first, 2),
            "end": round(last, 2),
            "ret_pct": round(100.0 * (last / first - 1.0), 2),
            "max_up_pct": round(100.0 * (hi / first - 1.0), 2),
            "max_dn_pct": round(100.0 * (lo / first - 1.0), 2),
            # did a 3R (+30%) target print before a 1R (-10%) stop, path-wise?
            "hit_3r": bool(hi >= first * (1 + RR * STOP_PCT)),
            "hit_stop": bool(lo <= first * (1 - STOP_PCT)),
            "median_iex_volume": int(med_vol),
        })
        frames[sym] = sub
    span = {}
    if frames:
        any_df = list(frames.values())[0]
        span = {"start": str(any_df.index[0])[:10], "end": str(any_df.index[-1])[:10],
                "sessions": int(len(any_df))}
    return rows, excluded, errors, corporate_actions, thin, frames, span


def path_order(rows, days: int, frames: dict):
    """For names that touched BOTH the 3R target and the 1R stop, which came
    first? Touching both tells you nothing without the order."""
    resolved = {"target_first": 0, "stop_first": 0, "only_target": 0,
                "only_stop": 0, "neither": 0}
    for r in rows:
        if r["hit_3r"] and r["hit_stop"]:
            df = frames.get(r["symbol"])
            if df is None:
                continue
            first = float(df["open"].iloc[0])
            tgt, stp = first * (1 + RR * STOP_PCT), first * (1 - STOP_PCT)
            order = None
            for _, bar in df.iterrows():
                hit_t, hit_s = float(bar["high"]) >= tgt, float(bar["low"]) <= stp
                if hit_t and hit_s:
                    order = "stop_first"     # same-bar ambiguity resolved pessimistically
                    break
                if hit_t:
                    order = "target_first"; break
                if hit_s:
                    order = "stop_first"; break
            if order:
                resolved[order] += 1
        elif r["hit_3r"]:
            resolved["only_target"] += 1
        elif r["hit_stop"]:
            resolved["only_stop"] += 1
        else:
            resolved["neither"] += 1
    return resolved


def breakeven_table():
    """Win rate needed to break even at 3:1, per friction band.

    Per trade: win = +3R - friction, loss = -1R - friction, both on notional.
    Solve p*(RR*STOP - f) = (1-p)*(STOP + f)  ->  p = (STOP+f)/(RR*STOP+STOP)
    """
    out = []
    for name, f in FRICTION_BANDS.items():
        win = RR * STOP_PCT - f
        loss = STOP_PCT + f
        p = loss / (win + loss)
        out.append({
            "band": name,
            "friction_pct": round(100 * f, 2),
            "win_r": round(100 * win, 2),
            "loss_r": round(100 * loss, 2),
            "breakeven_win_rate": round(100 * p, 1),
        })
    return out


def settlement_capacity(days: int, slots: int, hold_days: int, sessions: int = 0):
    """Cash account: proceeds settle T+1, so a slot cycles in hold+1 days.

    Uses the OBSERVED session count from the same window the universe stats
    came from, so the report cannot quote two different \"30 days\".
    """
    trading_days = sessions or int(days * 5 / 7)
    cycle = hold_days + 1
    return {
        "trading_days": trading_days,
        "slots": slots,
        "avg_hold_days": hold_days,
        "cycle_days": cycle,
        "max_round_trips": int(trading_days / cycle) * slots,
    }


def monte_carlo(book: float, sizing_pct: float, rng):
    """Ending equity distribution as a FUNCTION of assumed hit rate."""
    risk_frac = sizing_pct / 100.0
    grid = []
    for f_name, f in FRICTION_BANDS.items():
        win_ret = RR * STOP_PCT - f          # return ON THE POSITION
        loss_ret = -(STOP_PCT + f)
        for p in SKILL_LEVELS:
            for n in TRADE_COUNTS:
                draws = rng.random((N_SIMS, n)) < p
                per = np.where(draws, win_ret, loss_ret)
                # flat $ sizing off the STARTING book (no compounding on a
                # cash account this small -- settlement prevents it)
                pnl = (per * risk_frac * book).sum(axis=1)
                end = book + pnl
                grid.append({
                    "friction": f_name,
                    "win_rate": round(100 * p),
                    "trades": n,
                    "p10": round(float(np.percentile(end, 10)), 2),
                    "median": round(float(np.percentile(end, 50)), 2),
                    "p90": round(float(np.percentile(end, 90)), 2),
                    "mean_pnl": round(float(pnl.mean()), 2),
                    "prob_profit": round(100 * float((pnl > 0).mean()), 1),
                    "prob_down_20pct": round(100 * float((end < book * 0.8).mean()), 1),
                })
    return grid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", type=float, default=225.37)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--sizing", type=float, default=20.0)
    a = ap.parse_args()

    rng = np.random.default_rng(20260817)

    rows, excluded, errors, corp, thin, frames, span = window_stats(a.days)
    rets = [r["ret_pct"] for r in rows]

    universe = None
    if rets:
        pos = [x for x in rets if x > 0]
        universe = {
            "n": len(rows),
            "median_ret_pct": round(st.median(rets), 2),
            "mean_ret_pct": round(st.mean(rets), 2),
            "pct_positive": round(100.0 * len(pos) / len(rets), 1),
            "best": max(rows, key=lambda r: r["ret_pct"]),
            "worst": min(rows, key=lambda r: r["ret_pct"]),
            "p25": round(float(np.percentile(rets, 25)), 2),
            "p75": round(float(np.percentile(rets, 75)), 2),
            # a blindfolded $45 position, held the whole window
            "blind_pos_pnl_median": round(
                (a.book * a.sizing / 100.0) * st.median(rets) / 100.0, 2),
            "blind_pos_pnl_mean": round(
                (a.book * a.sizing / 100.0) * st.mean(rets) / 100.0, 2),
        }

    data = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "window_days": a.days,
        "window": span,
        "book": a.book,
        "sizing_pct": a.sizing,
        "per_position": round(a.book * a.sizing / 100.0, 2),
        "price_ceiling": PRICE_CEILING,
        "rr": RR,
        "stop_pct": round(100 * STOP_PCT, 1),
        "universe": universe,
        "detail": sorted(rows, key=lambda r: r["ret_pct"], reverse=True),
        "excluded_over_ceiling": excluded,
        "corporate_actions": corp,
        "excluded_thin_volume": thin,
        "path": path_order(rows, a.days, frames) if rows else {},
        "breakeven": breakeven_table(),
        "settlement": [settlement_capacity(a.days, 5, h, span.get("sessions", 0))
                       for h in (3, 5, 10)],
        "monte_carlo": monte_carlo(a.book, a.sizing, rng),
        "errors": errors,
        "honesty": ("This is NOT a backtest of Ari's selection process -- that "
                    "process is discretionary and cannot be replayed. Universe "
                    "stats are survivorship-biased optimistic. Monte Carlo is "
                    "conditional on an ASSUMED hit rate, not a predicted one."),
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1))

    print(f"penny reality -> {OUT}")
    if span:
        print(f"  window: {span['start']} -> {span['end']} ({span['sessions']} sessions, {a.days} calendar days)")
    if universe:
        u = universe
        print(f"  universe: {u['n']} sub-${PRICE_CEILING:.0f} names, {a.days}d")
        print(f"    median {u['median_ret_pct']:+.2f}%  mean {u['mean_ret_pct']:+.2f}%  "
              f"positive {u['pct_positive']:.0f}%")
        print(f"    IQR {u['p25']:+.1f}% .. {u['p75']:+.1f}%")
        print(f"    best  {u['best']['symbol']} {u['best']['ret_pct']:+.1f}%")
        print(f"    worst {u['worst']['symbol']} {u['worst']['ret_pct']:+.1f}%")
        print(f"    blindfolded $%.2f position -> median $%.2f / mean $%.2f"
              % (data["per_position"], u["blind_pos_pnl_median"], u["blind_pos_pnl_mean"]))
    print(f"  path: {data['path']}")
    for b in data["breakeven"]:
        print(f"  breakeven [{b['band']:>7}] friction {b['friction_pct']:.1f}%  "
              f"-> need {b['breakeven_win_rate']:.1f}% wins at {RR:.0f}:1")
    for s in data["settlement"]:
        print(f"  settlement: hold {s['avg_hold_days']}d -> max "
              f"{s['max_round_trips']} round trips in {s['trading_days']} sessions")
    for e in errors[:6]:
        print(f"  ERR {e}")


if __name__ == "__main__":
    main()
