"""
mtf_engine.py — tests the "1m engine, 5m view" theory. LONG-ONLY (where the
validated edge lives).

Two modes, both running their event loop on REAL 1m bars:

  mode="fills1m"   (variant B): the 5m v2 engine's signals, unchanged — but
      stops/targets/partials fill on 1m bars instead of 5m OHLC guesswork.
      Isolates pure fill-resolution effect.

  mode="trigger1m" (variant C): the theory itself. The 5m layer only defines the
      SETUP (slope regime + momentum gates + ADX + SPY alignment, all evaluated on
      the last CLOSED 5m bar — no lookahead). The 1m layer times the entry:
      1m close crosses over 1m EMA9 on a green 1m bar while the setup is active.
      Stops come from 1m swing structure (tighter risk unit -> bigger R per $ move).

Shared with the main engine: market orders fill next bar open, exit orders live
the bar after the fill bar, stop wins any stop-vs-target tie (conservative),
same commission + slippage model, 10% equity sizing.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

import indicators as ta
from data import resample_5m
from swing_pro import Config, compute_signals, stats


def run_mtf(df1m: pd.DataFrame, spy1m: pd.DataFrame, cfg: Config,
            mode: str = "trigger1m", struct_lookback_1m: int = 10,
            cooldown_1m: int = 5) -> dict:
    assert mode in ("fills1m", "trigger1m")
    df5 = resample_5m(df1m)
    spy5 = resample_5m(spy1m)
    sig5 = compute_signals(df5, spy5, cfg)

    o = df1m["open"].to_numpy(float)
    h = df1m["high"].to_numpy(float)
    l = df1m["low"].to_numpy(float)
    c = df1m["close"].to_numpy(float)
    idx = df1m.index
    n = len(df1m)

    # map every 1m bar -> its (forming) 5m bar position; closed bar = pos-1
    floor5 = idx.floor("5min")
    pos5 = df5.index.get_indexer(floor5)                       # -1 if missing
    closes_window = np.zeros(n, bool)                          # bar i is last 1m bar of its 5m window
    closes_window[:-1] = (pos5[:-1] != pos5[1:]) | (np.diff(idx.asi8) > 60_000_000_000)
    closes_window[-1] = True

    # 1m layer
    ema_1m = ta.ema(c, cfg.pullback_ema)
    atr_1m = ta.atr(h, l, c, cfg.atr_len)
    swlow_1m = ta.rolling_min(l, struct_lookback_1m)
    x_up_1m = ta.crossover(c, ema_1m)
    green_1m = c > o

    slip = cfg.slippage_ticks * cfg.tick_size
    comm = cfg.commission_pct / 100.0
    cash = cfg.initial_capital
    trades: list[dict] = []
    equity = np.empty(n)

    pos: Optional[dict] = None
    cur: Optional[dict] = None
    pending_entry = False
    pending_close = False
    pend = {}
    last_sig_1m = None
    last_sig_5m = None

    def book(px, qty, side_mult, is_market):
        nonlocal cash
        fill = px + side_mult * (slip if is_market else 0.0)
        cash -= side_mult * fill * qty
        cash -= abs(fill * qty) * comm
        return fill

    def close_all(px, i, reason, is_market):
        nonlocal pos, cur
        fill = book(px, pos["qty"], -1, is_market)
        cur["exits"].append((str(idx[i]), fill, pos["qty"], reason))
        pnl = sum((e[1] - cur["entry_fill"]) * e[2] for e in cur["exits"])
        gross = sum(abs(e[1] * e[2]) for e in cur["exits"]) + abs(cur["entry_fill"] * cur["qty"])
        cur["pnl"] = pnl - gross * comm
        cur["r"] = cur["pnl"] / (cur["risk"] * cur["qty"]) if cur["risk"] > 0 else np.nan
        cur["exit_time"] = str(idx[i])
        trades.append(cur)
        pos, cur = None, None

    for i in range(n):
        # 1) queued market orders fill at this 1m open
        if pending_close and pos is not None:
            close_all(o[i], i, "cond_exit", True)
        pending_close = False
        if pending_entry:
            if pos is None:
                qty = (cfg.qty_pct_equity / 100.0) * cash / max(o[i], 1e-9)
                fill = book(o[i], qty, 1, True)
                pos = dict(qty=qty, entry_ref=pend["ref"], risk=pend["risk"],
                           sl=pend["sl"], tp=pend["tp"], be_done=False,
                           tp1_done=False, live=False, ws=np.nan, w1=np.nan, w2=np.nan)
                cur = {"side": "long", "entry_time": str(idx[i]), "entry_fill": fill,
                       "qty": qty, "risk": pend["risk"], "exits": []}
            pending_entry = False

        # 2) working stop/limit orders, intrabar on the 1m bar (conservative)
        if pos is not None and pos["live"] and cfg.exit_on_target:
            if l[i] <= pos["ws"]:
                close_all(pos["ws"], i, "stop" if not pos["be_done"] else "breakeven", True)
            else:
                if not np.isnan(pos["w1"]) and not pos["tp1_done"] and h[i] >= pos["w1"]:
                    part = pos["qty"] * (cfg.partial_pct / 100.0)
                    fill = book(pos["w1"], part, -1, False)
                    cur["exits"].append((str(idx[i]), fill, part, "tp1"))
                    pos["qty"] -= part
                    pos["tp1_done"] = True
                if pos is not None and h[i] >= pos["w2"]:
                    close_all(pos["w2"], i, "target", False)

        # 3) close of this 1m bar
        k_closed = pos5[i] - 1  # last fully closed 5m bar (for setup state)

        # breakeven trigger at 1m resolution
        if pos is not None and cfg.use_breakeven and not pos["be_done"]:
            if h[i] >= pos["entry_ref"] + cfg.be_trigger_r * pos["risk"]:
                pos["be_done"] = True

        if closes_window[i] and pos5[i] >= 0:
            k = pos5[i]  # this 5m bar just completed
            # condition exit (v2: trend-line cross on the 5m close)
            if pos is not None and cfg.exit_on_trend and \
               sig5["close"][k] < sig5["trend_ma"][k]:
                pending_close = True
            # variant B: take the 5m engine's own entry signal, fill next 1m open
            if mode == "fills1m" and sig5["go_long"][k] and pos is None and not pending_entry:
                cooled = last_sig_5m is None or (k - last_sig_5m) >= cfg.min_bars_between
                if cooled:
                    last_sig_5m = k
                    atr5 = sig5["atr"][k]
                    raw = sig5["close"][k] - (sig5["swing_low"][k] - cfg.struct_buf_atr * atr5)
                    r = max(raw, cfg.atr_stop_mult * atr5 * 0.5) if (cfg.use_struct_stop and raw > 0) \
                        else cfg.atr_stop_mult * atr5
                    pend = dict(ref=sig5["close"][k], risk=r,
                                sl=sig5["close"][k] - r,
                                tp=sig5["close"][k] + cfg.rr_ratio * r)
                    pending_entry = True

        # variant C: 1m trigger while the (closed) 5m setup is active
        if mode == "trigger1m" and pos is None and not pending_entry and k_closed >= 0:
            setup = sig5["long_state"][k_closed] and sig5["mkt_long_ok"][k_closed]
            cooled = last_sig_1m is None or (i - last_sig_1m) >= cooldown_1m
            if setup and cooled and x_up_1m[i] and (not cfg.use_candle or green_1m[i]):
                atr1 = atr_1m[i]
                if not np.isnan(atr1) and atr1 > 0:
                    raw = c[i] - (swlow_1m[i] - cfg.struct_buf_atr * atr1)
                    r = max(raw, cfg.atr_stop_mult * atr1 * 0.5) if (cfg.use_struct_stop and raw > 0) \
                        else cfg.atr_stop_mult * atr1
                    pend = dict(ref=c[i], risk=r, sl=c[i] - r, tp=c[i] + cfg.rr_ratio * r)
                    pending_entry = True
                    last_sig_1m = i

        # refresh working exit orders (live from the NEXT 1m bar)
        if pos is not None:
            pos["live"] = True
            pos["ws"] = pos["entry_ref"] if (cfg.use_breakeven and pos["be_done"]) else pos["sl"]
            pos["w1"] = (pos["entry_ref"] + cfg.partial_r * pos["risk"]) if cfg.use_partial else np.nan
            pos["w2"] = pos["tp"]

        equity[i] = cash + (pos["qty"] * c[i] if pos is not None else 0.0)

    if pos is not None:
        close_all(c[-1], n - 1, "end_of_data", True)

    res = {"trades": trades, "equity": equity, "config": cfg, "mode": mode}
    res["stats"] = stats(res)
    if trades:
        risks = np.array([t["risk"] / t["entry_fill"] for t in trades])
        res["stats"]["avg_risk_pct"] = float(risks.mean() * 100)
    return res
