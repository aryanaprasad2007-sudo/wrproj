"""
swing_pro.py — faithful Python port of SWING_PRO_strategy.pine (Pine v6) for
validation: walk-forward, multi-symbol robustness, and filter-ablation studies.

Replication notes (matching TradingView's broker emulator, calc_on_every_tick=false):
  • Signals evaluate at bar close; market orders (entries, condition exits,
    reversals) fill at the NEXT bar's open.
  • strategy.exit stop/limit orders are placed at the close of the first bar where
    the position exists — so they are live from the bar AFTER the fill bar.
  • Stop + target inside one bar -> the STOP is assumed (conservative), same as TV.
  • Partial TP1 + final target: both limits in one bar fill both; stop overrides all.
  • Pine quirk kept on purpose: a same-direction re-signal while already in a
    position is blocked by pyramiding=0 but STILL resets entryPx/SL/TP/risk/beDone.
  • Slippage (1 tick) on market & stop fills; none on limit fills. Commission per side.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np
import pandas as pd

import indicators as ta


# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Config:
    # 0) chart timeframe (minutes per bar) — drives the HTF bucket size
    bar_minutes: int = 5
    # 1) trend
    use_trend: bool = True
    use_htf_trend: bool = True
    auto_htf_mult: int = 15
    trend_type: str = "EMA"
    trend_len: int = 50
    use_slope: bool = True
    slope_len: int = 3
    slope_min_atr: float = 0.20
    use_buffer: bool = False
    buffer_atr: float = 0.5
    # 2-3) momentum
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    use_macd: bool = True            # ablation switch (always on in Pine)
    rsi_len: int = 14
    rsi_long_level: int = 52
    rsi_short_level: int = 48
    use_rsi: bool = True             # ablation switch (always on in Pine)
    # 4) impulse
    use_impulse: bool = True
    imp_len: int = 34
    imp_signal: int = 9
    # 5) filters
    use_adx: bool = True
    adx_len: int = 14
    adx_min: int = 20
    use_vol: bool = True
    vol_len: int = 20
    vol_mult: float = 1.5
    # 5b) market alignment
    use_market_filter: bool = True
    market_ma_len: int = 50
    # 6) anti-chase
    min_bars_between: int = 1
    max_ext_atr: float = 0.0        # >0: entry only within this many ATRs of the trend line
    loss_cooldown_bars: int = 0     # >0: after a losing trade, block same-direction re-entry
    use_candle: bool = True
    use_avoid_ext: bool = True
    ob_level: int = 72
    os_level: int = 28
    # 7) risk
    atr_len: int = 14
    atr_stop_mult: float = 1.5
    rr_ratio: float = 2.0
    use_struct_stop: bool = True
    struct_lookback: int = 10
    struct_buf_atr: float = 0.25
    use_partial: bool = True
    partial_pct: int = 50
    partial_r: float = 1.0
    use_breakeven: bool = True
    be_trigger_r: float = 1.0
    # 9) entries & exits
    trade_dir: str = "both"          # "both" | "long" | "short"
    use_state_entry: bool = True
    allow_reentry: bool = True
    use_pullback: bool = True
    pullback_ema: int = 9
    exit_on_macd: bool = True
    exit_on_trend: bool = True
    exit_on_rsi: bool = False
    exit_on_target: bool = True
    long_wins_on_conflict: bool = False
    # 10) reversals (off by default, like the Pine)
    use_reversals: bool = False
    rev_exit_fast: bool = True
    rev_rsi_floor: int = 40
    rev_vol_mult: float = 1.0
    # account
    initial_capital: float = 100_000.0
    qty_pct_equity: float = 10.0
    commission_pct: float = 0.01     # percent per side
    slippage_ticks: int = 1
    tick_size: float = 0.01


# ──────────────────────────────────────────────────────────────────────────────
def _htf_series(df: pd.DataFrame, cfg: Config):
    """Non-repainting HTF trend MA / prev MA / ATR, per Pine:
    request.security(tf, [localMA[1], localMA[1+slopeLen], atr[1]], lookahead_off).
    HTF = chart TF × mult, bucketed within each session from 09:30 (TV behaviour).
    Chart bars in HTF bucket k see values from completed bucket k-1."""
    mins = (df.index.hour * 60 + df.index.minute) - (9 * 60 + 30)
    htf_min = cfg.bar_minutes * cfg.auto_htf_mult  # 1h chart × 15 -> one bucket/day (daily trend)
    bucket_in_day = mins // htf_min
    day = df.index.tz_localize(None).normalize()
    key = pd.Series(list(zip(day, bucket_in_day)), index=df.index)
    # global sequential bucket id, in time order
    codes, _ = pd.factorize(key, sort=False)

    g = df.groupby(codes)
    h_close = g["close"].last().to_numpy()
    h_high = g["high"].max().to_numpy()
    h_low = g["low"].min().to_numpy()

    ma_fn = ta.ema if cfg.trend_type == "EMA" else ta.sma
    h_ma = ma_fn(h_close, cfg.trend_len)
    h_atr = ta.atr(h_high, h_low, h_close, cfg.atr_len)

    def shifted(arr, k):
        out = np.full(len(arr), np.nan)
        if k < len(arr):
            out[k:] = arr[: len(arr) - k]
        return out

    ma_1 = shifted(h_ma, 1)[codes]
    ma_1s = shifted(h_ma, 1 + cfg.slope_len)[codes]
    atr_1 = shifted(h_atr, 1)[codes]
    return ma_1, ma_1s, atr_1


def compute_signals(df: pd.DataFrame, market: pd.DataFrame, cfg: Config) -> dict:
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    v = df["volume"].to_numpy(float)
    n = len(df)

    atr = ta.atr(h, l, c, cfg.atr_len)

    # trend (HTF, non-repainting) + ATR-normalised slope
    local_ma = (ta.ema if cfg.trend_type == "EMA" else ta.sma)(c, cfg.trend_len)
    if cfg.use_htf_trend:
        htf_ma, htf_ma_prev, htf_atr = _htf_series(df, cfg)
        trend_ma = htf_ma
        with np.errstate(divide="ignore", invalid="ignore"):
            slope = np.where(htf_atr > 0, (htf_ma - htf_ma_prev) / htf_atr, 0.0)
    else:
        trend_ma = local_ma
        prev = np.concatenate((np.full(cfg.slope_len, np.nan), local_ma[:-cfg.slope_len]))
        with np.errstate(divide="ignore", invalid="ignore"):
            slope = np.where(atr > 0, (local_ma - prev) / atr, 0.0)

    slope_long_ok = (~np.isnan(slope)) & (slope >= cfg.slope_min_atr) if cfg.use_slope else np.ones(n, bool)
    slope_short_ok = (~np.isnan(slope)) & (slope <= -cfg.slope_min_atr) if cfg.use_slope else np.ones(n, bool)

    buf = cfg.buffer_atr * atr if cfg.use_buffer else np.zeros(n)
    bull = (c > trend_ma + buf) if cfg.use_trend else np.ones(n, bool)
    bear = (c < trend_ma - buf) if cfg.use_trend else np.ones(n, bool)

    # market-index alignment (same TF, aligned on timestamps, ffilled)
    mkt = market.reindex(df.index, method="ffill")
    mc = mkt["close"].to_numpy(float)
    mma = ta.ema(mkt["close"].to_numpy(float), cfg.market_ma_len)
    mkt_long_ok = (mc > mma) if cfg.use_market_filter else np.ones(n, bool)
    mkt_short_ok = (mc < mma) if cfg.use_market_filter else np.ones(n, bool)

    # swing structure
    swing_low = ta.rolling_min(l, cfg.struct_lookback)
    swing_high = ta.rolling_max(h, cfg.struct_lookback)

    # impulse macd
    hlc3 = (h + l + c) / 3.0
    imp_hi = ta.smma(h, cfg.imp_len)
    imp_lo = ta.smma(l, cfg.imp_len)
    mi = ta.zlema(hlc3, cfg.imp_len)
    md = np.where(mi > imp_hi, mi - imp_hi, np.where(mi < imp_lo, mi - imp_lo, 0.0))
    md[np.isnan(imp_hi) | np.isnan(imp_lo) | np.isnan(mi)] = np.nan
    sb = ta.sma(md, cfg.imp_signal)
    imp_bull = (md > sb) if cfg.use_impulse else np.ones(n, bool)
    imp_bear = (md < sb) if cfg.use_impulse else np.ones(n, bool)

    # macd + rsi
    macd_line, macd_sig, macd_hist = ta.macd(c, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    macd_bull = (macd_line > macd_sig) if cfg.use_macd else np.ones(n, bool)
    macd_bear = (macd_line < macd_sig) if cfg.use_macd else np.ones(n, bool)
    rsi = ta.rsi(c, cfg.rsi_len)
    rsi_long_ok = (rsi > cfg.rsi_long_level) if cfg.use_rsi else np.ones(n, bool)
    rsi_short_ok = (rsi < cfg.rsi_short_level) if cfg.use_rsi else np.ones(n, bool)

    # filters
    _, _, adx = ta.dmi(h, l, c, cfg.adx_len, cfg.adx_len)
    adx_ok = (adx >= cfg.adx_min) if cfg.use_adx else np.ones(n, bool)
    vol_avg = ta.sma(v, cfg.vol_len)
    vol_ok = (v >= cfg.vol_mult * vol_avg) if cfg.use_vol else np.ones(n, bool)
    filters_ok = adx_ok & vol_ok

    # quality guards
    candle_buy = (c > o) if cfg.use_candle else np.ones(n, bool)
    candle_sell = (c < o) if cfg.use_candle else np.ones(n, bool)
    not_ext_long = (rsi < cfg.ob_level) if cfg.use_avoid_ext else np.ones(n, bool)
    not_ext_short = (rsi > cfg.os_level) if cfg.use_avoid_ext else np.ones(n, bool)

    # state confluence + trigger
    long_state = bull & slope_long_ok & macd_bull & imp_bull & rsi_long_ok & filters_ok
    short_state = bear & slope_short_ok & macd_bear & imp_bear & rsi_short_ok & filters_ok
    prev_ls = np.concatenate(([False], long_state[:-1]))
    prev_ss = np.concatenate(([False], short_state[:-1]))
    long_trig = long_state & ~prev_ls
    short_trig = short_state & ~prev_ss

    # pullback
    ema_fast = ta.ema(c, cfg.pullback_ema)
    x_up = ta.crossover(c, ema_fast)
    x_dn = ta.crossunder(c, ema_fast)
    pull_long = cfg.use_pullback & long_state & x_up
    pull_short = cfg.use_pullback & short_state & x_dn

    # reversals (default off)
    prev_hist = np.concatenate(([np.nan], macd_hist[:-1]))
    prev_rsi = np.concatenate(([np.nan], rsi[:-1]))
    rev_vol_ok = (v >= cfg.rev_vol_mult * vol_avg) if cfg.use_vol else np.ones(n, bool)
    rev_long = (cfg.use_reversals & (c < trend_ma - buf) & x_up
                & (macd_hist > prev_hist) & (rsi > prev_rsi) & (rsi > cfg.rev_rsi_floor)
                & (rsi < cfg.ob_level) & rev_vol_ok)
    rev_short = (cfg.use_reversals & (c > trend_ma + buf) & x_dn
                 & (macd_hist < prev_hist) & (rsi < prev_rsi) & (rsi < 100 - cfg.rev_rsi_floor)
                 & (rsi > cfg.os_level) & rev_vol_ok)

    st_long = long_trig if cfg.use_state_entry else np.zeros(n, bool)
    st_short = short_trig if cfg.use_state_entry else np.zeros(n, bool)
    trend_buy = (st_long | pull_long) & mkt_long_ok
    trend_sell = (st_short | pull_short) & mkt_short_ok
    rev_buy = rev_long & not_ext_long
    rev_sell = rev_short & not_ext_short

    allow_long = cfg.trade_dir in ("both", "long")
    allow_short = cfg.trade_dir in ("both", "short")
    # extension veto: don't chase entries stretched too far past the FAST EMA
    # (the local anchor — measuring vs the slow HTF trend line in chart-ATR units
    # was a scale error that produced a filter that never engaged)
    if cfg.max_ext_atr > 0:
        ext_long_ok = (c - ema_fast) <= cfg.max_ext_atr * atr
        ext_short_ok = (ema_fast - c) <= cfg.max_ext_atr * atr
    else:
        ext_long_ok = ext_short_ok = np.ones(n, bool)
    go_long = allow_long & (trend_buy | rev_buy) & candle_buy & ext_long_ok
    go_short = allow_short & (trend_sell | rev_sell) & candle_sell & ext_short_ok

    # condition-exit ingredients
    rsi_x_under_50 = ta.crossunder(rsi, np.full(n, 50.0))
    rsi_x_over_50 = ta.crossover(rsi, np.full(n, 50.0))

    return {
        "open": o, "high": h, "low": l, "close": c, "atr": atr,
        "trend_ma": trend_ma, "ema_fast": ema_fast,
        "swing_low": swing_low, "swing_high": swing_high,
        "go_long": go_long, "go_short": go_short,
        "st_long": st_long, "st_short": st_short,
        "pull_long": pull_long, "pull_short": pull_short,
        "rev_long": rev_long, "rev_short": rev_short,
        "macd_bull": macd_bull if cfg.use_macd else (macd_line > macd_sig),
        "macd_bear": macd_bear if cfg.use_macd else (macd_line < macd_sig),
        "rsi_xu50": rsi_x_under_50, "rsi_xo50": rsi_x_over_50,
        # raw gate states (setup-without-trigger), used by the MTF engine
        "long_state": long_state, "short_state": short_state,
        "mkt_long_ok": mkt_long_ok, "mkt_short_ok": mkt_short_ok,
        "index": df.index,
    }


# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Position:
    side: int                 # +1 long, -1 short
    qty: float
    fill_px: float
    entry_ref: float          # Pine entryPx = signal-bar close (risk math anchor)
    risk: float               # per-share risk locked at signal
    sl: float
    tp: float
    is_rev: bool
    be_done: bool = False
    tp1_done: bool = False
    entry_time: object = None
    orders_live: bool = False # strategy.exit live (set at first close while in pos)
    work_stop: float = np.nan # working orders snapshotted at previous close
    work_tp1: float = np.nan
    work_tp2: float = np.nan
    work_tp1_live: bool = False


def backtest(sig: dict, cfg: Config) -> dict:
    o, h, l, c = sig["open"], sig["high"], sig["low"], sig["close"]
    idx = sig["index"]
    n = len(o)
    slip = cfg.slippage_ticks * cfg.tick_size
    comm = cfg.commission_pct / 100.0

    cash = cfg.initial_capital
    pos: Optional[Position] = None
    last_dir = 0
    last_sig_bar: Optional[int] = None
    pending_entry = 0            # -1/0/+1 market entry queued for next open
    pending_close = False        # condition-exit market order queued
    pend_risk = pend_sl = pend_tp = pend_ref = np.nan
    pend_rev = False

    trades: list[dict] = []
    cur: Optional[dict] = None
    equity_curve = np.empty(n)

    def book(px, qty, side_mult, is_market):
        """Execute a fill; side_mult=+1 buy, -1 sell. Returns cash delta."""
        nonlocal cash
        fill = px + side_mult * (slip if is_market else 0.0)
        cash -= side_mult * fill * qty
        cash -= abs(fill * qty) * comm
        return fill

    blocked = {1: -1, -1: -1}    # loss-cooldown: bar until which each direction is locked

    def close_all(px, i, reason, is_market):
        nonlocal pos, cur
        side_closed = pos.side
        fill = book(px, pos.qty, -pos.side, is_market)
        cur["exits"].append((str(idx[i]), fill, pos.qty, reason))
        cur["exit_time"] = str(idx[i])
        pnl = sum((e[1] - cur["entry_fill"]) * e[2] * pos.side for e in cur["exits"])
        gross = sum(abs(e[1] * e[2]) for e in cur["exits"]) + abs(cur["entry_fill"] * cur["qty"])
        cur["pnl"] = pnl - gross * comm
        cur["r"] = cur["pnl"] / (cur["risk"] * cur["qty"]) if cur["risk"] > 0 else np.nan
        trades.append(cur)
        if cfg.loss_cooldown_bars > 0 and cur["pnl"] < 0:
            blocked[side_closed] = i + cfg.loss_cooldown_bars
        pos, cur = None, None

    for i in range(n):
        # ── 1) open: market orders queued at previous close ──────────────────
        if pending_close and pos is not None:
            close_all(o[i], i, "cond_exit", True)
        pending_close = False

        if pending_entry != 0:
            if pos is not None and pos.side != pending_entry:
                close_all(o[i], i, "reverse", True)
            if pos is None:
                eq = cash
                qty = (cfg.qty_pct_equity / 100.0) * eq / max(o[i], 1e-9)
                fill = book(o[i], qty, pending_entry, True)
                pos = Position(side=pending_entry, qty=qty, fill_px=fill,
                               entry_ref=pend_ref, risk=pend_risk,
                               sl=pend_sl, tp=pend_tp, is_rev=pend_rev,
                               entry_time=idx[i])
                cur = {"side": "long" if pending_entry > 0 else "short",
                       "entry_time": str(idx[i]), "entry_fill": fill,
                       "signal_ref": pend_ref, "qty": qty, "risk": pend_risk,
                       "exits": []}
            pending_entry = 0

        # ── 2) intrabar: working stop/limit orders (live since previous close) ─
        if pos is not None and pos.orders_live and cfg.exit_on_target:
            stop, tp1, tp2 = pos.work_stop, pos.work_tp1, pos.work_tp2
            if pos.side > 0:
                stop_hit = l[i] <= stop
                tp1_hit = pos.work_tp1_live and not pos.tp1_done and h[i] >= tp1
                tp2_hit = h[i] >= tp2
            else:
                stop_hit = h[i] >= stop
                tp1_hit = pos.work_tp1_live and not pos.tp1_done and l[i] <= tp1
                tp2_hit = l[i] <= tp2
            if stop_hit:  # conservative: stop wins any tie
                close_all(stop, i, "stop" if not pos.be_done else "breakeven", True)
            else:
                if tp1_hit:
                    part = pos.qty * (cfg.partial_pct / 100.0)
                    fill = book(tp1, part, -pos.side, False)
                    cur["exits"].append((str(idx[i]), fill, part, "tp1"))
                    pos.qty -= part
                    pos.tp1_done = True
                if tp2_hit and pos is not None:
                    close_all(tp2, i, "target", False)

        # ── 3) close of bar i: Pine script run ────────────────────────────────
        in_long = pos is not None and pos.side > 0
        in_short = pos is not None and pos.side < 0

        # breakeven trigger (uses signal-bar close as anchor, like the Pine)
        if pos is not None and cfg.use_breakeven and not np.isnan(pos.entry_ref):
            if in_long and h[i] >= pos.entry_ref + cfg.be_trigger_r * pos.risk:
                pos.be_done = True
            if in_short and l[i] <= pos.entry_ref - cfg.be_trigger_r * pos.risk:
                pos.be_done = True

        # cooldown
        cooled = last_sig_bar is None or (i - last_sig_bar) >= cfg.min_bars_between
        go_l = sig["go_long"][i] and cooled
        go_s = sig["go_short"][i] and cooled
        can_l = go_l and (cfg.allow_reentry or last_dir != 1) and i >= blocked[1]
        can_s = go_s and (cfg.allow_reentry or last_dir != -1) and i >= blocked[-1]
        if cfg.long_wins_on_conflict:
            do_l, do_s = can_l, (can_s and not can_l)
        else:
            do_l, do_s = (can_l and not can_s), (can_s and not can_l)

        # condition exits
        exit_ref = sig["ema_fast"][i] if (cfg.rev_exit_fast and pos is not None and pos.is_rev) \
            else sig["trend_ma"][i]
        exit_l = ((cfg.exit_on_macd and sig["macd_bear"][i])
                  or (cfg.exit_on_trend and c[i] < exit_ref)
                  or (cfg.exit_on_rsi and sig["rsi_xu50"][i]))
        exit_s = ((cfg.exit_on_macd and sig["macd_bull"][i])
                  or (cfg.exit_on_trend and c[i] > exit_ref)
                  or (cfg.exit_on_rsi and sig["rsi_xo50"][i]))

        if in_long and exit_l and not do_s:
            pending_close = True
        if in_short and exit_s and not do_l:
            pending_close = True

        # entries (and the Pine pyramiding-quirk state reset)
        for direction, do_it in ((1, do_l), (-1, do_s)):
            if not do_it:
                continue
            atr_i = sig["atr"][i]
            if direction > 0:
                raw = c[i] - (sig["swing_low"][i] - cfg.struct_buf_atr * atr_i)
                r = max(raw, cfg.atr_stop_mult * atr_i * 0.5) if (cfg.use_struct_stop and raw > 0) \
                    else cfg.atr_stop_mult * atr_i
                sl_, tp_ = c[i] - r, c[i] + cfg.rr_ratio * r
                is_rev = bool(sig["rev_long"][i]) and not (sig["st_long"][i] or sig["pull_long"][i])
            else:
                raw = (sig["swing_high"][i] + cfg.struct_buf_atr * atr_i) - c[i]
                r = max(raw, cfg.atr_stop_mult * atr_i * 0.5) if (cfg.use_struct_stop and raw > 0) \
                    else cfg.atr_stop_mult * atr_i
                sl_, tp_ = c[i] + r, c[i] - cfg.rr_ratio * r
                is_rev = bool(sig["rev_short"][i]) and not (sig["st_short"][i] or sig["pull_short"][i])
            last_dir = direction
            last_sig_bar = i
            if pos is not None and pos.side == direction:
                # pyramiding=0 blocks the order, but Pine still resets trade mgmt state
                pos.entry_ref, pos.risk, pos.sl, pos.tp = c[i], r, sl_, tp_
                pos.be_done = False
            else:
                pending_entry = direction
                pend_risk, pend_sl, pend_tp, pend_ref, pend_rev = r, sl_, tp_, c[i], is_rev

        # place/refresh strategy.exit working orders (live from next bar)
        if pos is not None:
            pos.orders_live = True
            eff_stop = pos.entry_ref if (cfg.use_breakeven and pos.be_done) else pos.sl
            pos.work_stop = eff_stop
            pos.work_tp1 = pos.entry_ref + pos.side * cfg.partial_r * pos.risk
            pos.work_tp2 = pos.tp
            pos.work_tp1_live = cfg.use_partial

        # equity mark at close (short entry credited cash, so side-signed value is right)
        equity_curve[i] = cash + (pos.qty * c[i] * pos.side if pos is not None else 0.0)

    # liquidate any open position at the last close (reporting only)
    if pos is not None:
        close_all(c[-1], n - 1, "end_of_data", True)

    return {"trades": trades, "equity": equity_curve, "config": cfg}


# ──────────────────────────────────────────────────────────────────────────────
def stats(result: dict) -> dict:
    trades = [t for t in result["trades"] if t.get("pnl") is not None]
    eq = result["equity"]
    cfg = result["config"]
    if not trades:
        return {"trades": 0, "net_profit": 0.0, "win_rate": np.nan,
                "profit_factor": np.nan, "expectancy_usd": np.nan,
                "expectancy_r": np.nan, "max_dd_pct": 0.0, "avg_r": np.nan}
    pnls = np.array([t["pnl"] for t in trades])
    rs = np.array([t["r"] for t in trades if not np.isnan(t.get("r", np.nan))])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    peak = np.maximum.accumulate(np.concatenate(([cfg.initial_capital], eq)))
    dd = (np.concatenate(([cfg.initial_capital], eq)) - peak) / peak
    return {
        "trades": len(trades),
        "net_profit": float(pnls.sum()),
        "net_pct": float(pnls.sum() / cfg.initial_capital * 100),
        "win_rate": float(len(wins) / len(trades) * 100),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else np.inf,
        "expectancy_usd": float(pnls.mean()),
        "expectancy_r": float(rs.mean()) if len(rs) else np.nan,
        "max_dd_pct": float(dd.min() * 100),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
    }


def config_v2(**overrides) -> Config:
    """SWING_PRO v2 — baseline minus what the 2026-07-01 ablation convicted.

    Changes vs v1 (evidence: backtest/reports/ablation_2026-07-01.md):
      • exit_on_macd=False — the MACD-flip exit cut winners before target;
        removing it alone took the basket from PF 0.93 → 1.00.
      • use_vol=False — the 1.5× volume gate halved trade count while making
        per-trade expectancy WORSE (-0.122R → -0.055R without it).
      • use_trend=False — provably dead: removal changed zero trades (the slope
        filter already implies the right side of the MA). Deleted for simplicity.
    Kept: slope filter, SPY market filter, candle-color rule (all clearly earn
    their keep), momentum gates + ADX (marginal — revisit with longer history),
    structure stops, partial TP, breakeven, trend-line exit.
    """
    base = dict(exit_on_macd=False, use_vol=False, use_trend=False)
    base.update(overrides)
    return Config(**base)


def config_v22(**overrides) -> Config:
    """v2.2 = v2 + the exit-sweep winner (reports/exit_sweep_2026-07-02.md).

    64-config grid, H1-ranked, H2-validated: pure stop + 3R target beat every
    protective mechanism. rr 2.0→3.0; partial TP, breakeven and trend-exit all
    OFF — each was clipping the rare big winners that carry the whole system.
    Full 2y: +$6,835 / PF 1.30 vs +$1,706 / PF 1.08 (consistent in both halves).
    """
    base = dict(exit_on_macd=False, use_vol=False, use_trend=False,
                rr_ratio=3.0, use_partial=False, use_breakeven=False,
                exit_on_trend=False)
    base.update(overrides)
    return Config(**base)


def run(df: pd.DataFrame, market: pd.DataFrame, cfg: Config = None, **overrides) -> dict:
    cfg = replace(cfg or Config(), **overrides) if overrides else (cfg or Config())
    sig = compute_signals(df, market, cfg)
    res = backtest(sig, cfg)
    res["stats"] = stats(res)
    return res
