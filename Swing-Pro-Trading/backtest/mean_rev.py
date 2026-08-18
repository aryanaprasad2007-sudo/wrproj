"""
mean_rev.py — MR-1: daily long-only mean-reversion engine (Strategy #2 R&D).

NOT a fork of swing_pro.py — different mechanics — but the fill conventions
deliberately match it so results are comparable:
  • Signals evaluate at bar close; market orders fill at the NEXT bar's open.
  • The disaster stop goes live at the close of the fill bar (so it protects
    from the bar AFTER the fill, like strategy.exit in the Pine emulator).
  • Slippage (1 tick) on market & stop fills; commission per side.
  • Stop wins any intrabar tie (conservative).

What IS different — and why:
  • PORTFOLIO engine, not per-symbol accounts. MR entries cluster in selloffs,
    so the concurrency cap (max positions, most-oversold priority) is part of
    the strategy, not an afterthought. One cash pool, union trading calendar.
  • Exit philosophy inverts v2.2: momentum's validated lesson was "let winners
    run" (pure stop + 3R). Mean reversion's profit IS the snapback — exit on
    the first close above the short mean, time-stop the failures, and keep a
    wide disaster stop that should almost never fire.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np
import pandas as pd

import indicators as ta


@dataclass
class MRConfig:
    # entry
    rsi_len: int = 3
    rsi_entry: float = 15.0        # trigger: RSI(3) below this at the close
    trend_len: int = 200           # regime: close above the 200d SMA
    # exit
    exit_ma_len: int = 10          # mean touch: first close above the 10d SMA
    time_stop_bars: int = 10       # sessions held (fill day = 1) before giving up
    atr_len: int = 14
    stop_atr_mult: float = 3.0     # disaster stop, not trade management
    # portfolio
    max_positions: int = 10
    qty_pct_equity: float = 10.0   # flat sizing — risk-layer study winner
    initial_capital: float = 100_000.0
    commission_pct: float = 0.01   # percent per side (matches swing_pro)
    slippage_ticks: int = 1
    tick_size: float = 0.01


def prep_symbol(df: pd.DataFrame, cfg: MRConfig) -> pd.DataFrame:
    """Indicator columns for one symbol, index = its own trading days."""
    c = df["close"].to_numpy(float)
    out = pd.DataFrame(index=df.index)
    out["open"] = df["open"].to_numpy(float)
    out["high"] = df["high"].to_numpy(float)
    out["low"] = df["low"].to_numpy(float)
    out["close"] = c
    out["trend_ma"] = ta.sma(c, cfg.trend_len)
    out["exit_ma"] = ta.sma(c, cfg.exit_ma_len)
    out["rsi"] = ta.rsi(c, cfg.rsi_len)
    out["atr"] = ta.atr(df["high"].to_numpy(float), df["low"].to_numpy(float),
                        c, cfg.atr_len)
    return out


@dataclass
class _Pos:
    qty: float
    fill_px: float
    entry_ref: float          # signal-bar close (risk-math anchor)
    risk: float               # per-share = stop_atr_mult × ATR at signal
    stop: float
    stop_live: bool = False   # goes live at the close of the fill bar
    bars_held: int = 0        # closes seen since fill (fill day = 1)
    entry_time: object = None
    last_mark: float = np.nan


def run_portfolio(symbol_dfs: dict[str, pd.DataFrame], cfg: MRConfig = None,
                  start: pd.Timestamp = None, **overrides) -> dict:
    """`start`: no entries are queued before this date (bars before it only
    warm up indicators). Lets the forward tracker recompute the audition
    deterministically from a fixed start instead of persisting engine state."""
    cfg = replace(cfg or MRConfig(), **overrides) if overrides else (cfg or MRConfig())
    data = {s: prep_symbol(df, cfg) for s, df in symbol_dfs.items()}
    calendar = sorted(set().union(*[d.index for d in data.values()]))
    # fast row lookup: date -> positional index, per symbol
    locs = {s: {ts: i for i, ts in enumerate(d.index)} for s, d in data.items()}
    arrs = {s: {k: d[k].to_numpy() for k in d.columns} for s, d in data.items()}

    slip = cfg.slippage_ticks * cfg.tick_size
    comm = cfg.commission_pct / 100.0
    cash = cfg.initial_capital
    positions: dict[str, _Pos] = {}
    pending_entries: list[tuple[str, float, float, float]] = []  # sym, ref, risk, stop
    pending_exits: dict[str, str] = {}                           # sym -> reason
    trades: list[dict] = []
    eq_vals, eq_dates = [], []
    max_concurrent = 0

    def close_position(sym: str, px: float, ts, reason: str):
        nonlocal cash
        p = positions.pop(sym)
        fill = px - slip                       # long exit = sell, slip against us
        cash += fill * p.qty
        cash -= abs(fill * p.qty) * comm
        pnl = (fill - p.fill_px) * p.qty - abs(p.fill_px * p.qty) * comm \
              - abs(fill * p.qty) * comm
        trades.append({
            "symbol": sym, "side": "long",
            "entry_time": str(p.entry_time), "entry_fill": p.fill_px,
            "exit_time": str(ts), "exit_fill": fill, "qty": p.qty,
            "risk": p.risk, "bars_held": p.bars_held, "reason": reason,
            "pnl": pnl,
            "r": pnl / (p.risk * p.qty) if p.risk > 0 else np.nan,
            "pct": 100.0 * pnl / (p.fill_px * p.qty),
        })

    for ts in calendar:
        # ── 1) open: queued market orders (exits first — they free slots/cash)
        for sym, reason in list(pending_exits.items()):
            if sym in positions and ts in locs[sym]:
                i = locs[sym][ts]
                close_position(sym, arrs[sym]["open"][i], ts, reason)
                del pending_exits[sym]

        if pending_entries:
            # equity for sizing: cash + open positions marked at today's open
            # (falling back to last close where a symbol doesn't trade today)
            mark = cash
            for sym, p in positions.items():
                px = arrs[sym]["open"][locs[sym][ts]] if ts in locs[sym] else p.last_mark
                mark += p.qty * px
            still_pending = []
            for sym, ref, risk, stop in pending_entries:
                if ts not in locs[sym]:
                    still_pending.append((sym, ref, risk, stop))
                    continue
                if sym in positions or len(positions) >= cfg.max_positions:
                    continue                   # admission raced a slot; drop it
                o = arrs[sym]["open"][locs[sym][ts]]
                qty = (cfg.qty_pct_equity / 100.0) * mark / max(o, 1e-9)
                fill = o + slip
                cash -= fill * qty
                cash -= abs(fill * qty) * comm
                positions[sym] = _Pos(qty=qty, fill_px=fill, entry_ref=ref,
                                      risk=risk, stop=stop, entry_time=ts,
                                      last_mark=fill)
            pending_entries = still_pending

        # ── 2) intrabar: disaster stops (live since a prior close)
        for sym in list(positions):
            p = positions[sym]
            if not p.stop_live or ts not in locs[sym]:
                continue
            i = locs[sym][ts]
            if arrs[sym]["low"][i] <= p.stop:
                close_position(sym, p.stop, ts, "disaster_stop")

        # ── 3) close: exits queue, then entry candidates by oversold depth
        candidates: list[tuple[float, str, float, float, float]] = []
        for sym, d in arrs.items():
            if ts not in locs[sym]:
                continue
            i = locs[sym][ts]
            c, trend, ema_x, rsi, atr = (d["close"][i], d["trend_ma"][i],
                                         d["exit_ma"][i], d["rsi"][i], d["atr"][i])
            if sym in positions:
                p = positions[sym]
                p.bars_held += 1
                p.last_mark = c
                p.stop_live = True
                if sym not in pending_exits:
                    if not np.isnan(ema_x) and c > ema_x:
                        pending_exits[sym] = "mean_touch"
                    elif p.bars_held >= cfg.time_stop_bars:
                        pending_exits[sym] = "time_stop"
            else:
                if (not np.isnan(trend) and not np.isnan(rsi) and not np.isnan(atr)
                        and (start is None or ts >= start)
                        and c > trend and rsi < cfg.rsi_entry):
                    candidates.append((rsi, sym, c, cfg.stop_atr_mult * atr,
                                       c - cfg.stop_atr_mult * atr))

        # admission: most-oversold first, into slots free after pending exits
        slots = cfg.max_positions - (len(positions) - len(pending_exits))
        pending_syms = {pe[0] for pe in pending_entries}
        for rsi, sym, ref, risk, stop in sorted(candidates):
            if slots <= 0:
                break
            if sym in pending_syms:
                continue
            pending_entries.append((sym, ref, risk, stop))
            slots -= 1

        # ── 4) mark portfolio equity at the close
        mv = sum(p.qty * p.last_mark for p in positions.values())
        eq_vals.append(cash + mv)
        eq_dates.append(ts)
        max_concurrent = max(max_concurrent, len(positions))

    # snapshot live state (forward tracker reads these), then liquidate
    # anything still open at the last close (reporting only)
    open_at_end = [{"symbol": s, "qty": p.qty, "entry_time": str(p.entry_time),
                    "entry_fill": p.fill_px, "stop": p.stop,
                    "bars_held": p.bars_held, "last_mark": p.last_mark}
                   for s, p in positions.items()]
    queued_at_end = [{"symbol": s, "signal_close": ref, "risk": risk, "stop": stop}
                     for s, ref, risk, stop in pending_entries]
    exits_queued = dict(pending_exits)
    last = calendar[-1]
    for sym in list(positions):
        p = positions[sym]
        i = locs[sym].get(last, len(arrs[sym]["close"]) - 1)
        close_position(sym, arrs[sym]["close"][i], last, "end_of_data")

    equity = pd.Series(eq_vals, index=pd.DatetimeIndex(eq_dates), name="equity")
    return {"trades": trades, "equity": equity, "config": cfg,
            "max_concurrent": max_concurrent, "open_at_end": open_at_end,
            "queued_at_end": queued_at_end, "exits_queued_at_end": exits_queued}


def curve_stats(equity: pd.Series, initial: float) -> dict:
    peak = equity.cummax()
    dd = float(((equity - peak) / peak).min() * 100)
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = float(((equity.iloc[-1] / initial) ** (1 / years) - 1) * 100) if years > 0 else np.nan
    return {"cagr%": round(cagr, 2), "max_dd%": round(dd, 2),
            "mar": round(cagr / abs(dd), 2) if dd < 0 else np.nan}
