"""
indicators.py — Pine-exact indicator math for the iAPE validation harness.

Every function replicates TradingView Pine v6 semantics, including seeding:
  • ta.ema  — SMA-seeded EMA (na for first len-1 bars, seed = SMA at bar len-1)
  • ta.rma  — Wilder smoothing, SMA-seeded (used inside RSI / ATR / DMI)
  • ta.rsi, ta.atr, ta.macd, ta.dmi — built from the above
  • calc_smma / calc_zlema — the Impulse MACD helpers from the Pine source

All functions take/return numpy float arrays (nan = Pine `na`).
"""
from __future__ import annotations

import numpy as np


def sma(x: np.ndarray, length: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= length:
        c = np.cumsum(np.nan_to_num(x, nan=0.0))
        # only valid where the full window has no leading nan
        first_valid = np.argmax(~np.isnan(x)) if np.any(~np.isnan(x)) else len(x)
        for i in range(max(length - 1, first_valid + length - 1), len(x)):
            w = x[i - length + 1 : i + 1]
            if not np.isnan(w).any():
                out[i] = w.mean()
    return out


def ema(x: np.ndarray, length: int) -> np.ndarray:
    """Pine ta.ema: alpha = 2/(len+1), seeded with SMA of the first len valid values."""
    return _recursive_ma(x, length, alpha=2.0 / (length + 1.0))


def rma(x: np.ndarray, length: int) -> np.ndarray:
    """Pine ta.rma (Wilder): alpha = 1/len, SMA seed."""
    return _recursive_ma(x, length, alpha=1.0 / length)


def _recursive_ma(x: np.ndarray, length: int, alpha: float) -> np.ndarray:
    out = np.full(len(x), np.nan)
    prev = np.nan
    count = 0
    acc = 0.0
    for i in range(len(x)):
        v = x[i]
        if np.isnan(v):
            # Pine: na input keeps state (nz-style continuation not applied here;
            # leading na simply delays the seed, matching series warm-up)
            out[i] = prev
            continue
        if np.isnan(prev):
            acc += v
            count += 1
            if count == length:
                prev = acc / length
                out[i] = prev
        else:
            prev = alpha * v + (1.0 - alpha) * prev
            out[i] = prev
    return out


def smma(x: np.ndarray, length: int) -> np.ndarray:
    """calc_smma from the Pine source: SMA seed, then (prev*(len-1)+src)/len.
    Identical to rma()."""
    return rma(x, length)


def zlema(x: np.ndarray, length: int) -> np.ndarray:
    """calc_zlema from the Pine source: ema1 + (ema1 - ema2)."""
    e1 = ema(x, length)
    e2 = ema(e1, length)  # nan-aware recursive MA handles the warm-up alignment
    return e1 + (e1 - e2)


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.concatenate(([np.nan], close[:-1]))
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    tr[0] = high[0] - low[0]  # Pine: TR on first bar = high-low
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    return rma(true_range(high, low, close), length)


def rsi(x: np.ndarray, length: int) -> np.ndarray:
    delta = np.diff(x, prepend=np.nan)
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    up[0] = np.nan
    dn[0] = np.nan
    ru = rma(up, length)
    rd = rma(dn, length)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(rd == 0, 100.0,
                       np.where(ru == 0, 0.0, 100.0 - 100.0 / (1.0 + ru / rd)))
    out[np.isnan(ru) | np.isnan(rd)] = np.nan
    return out


def macd(x: np.ndarray, fast: int, slow: int, signal: int):
    line = ema(x, fast) - ema(x, slow)
    sig = _recursive_ma(line, signal, alpha=2.0 / (signal + 1.0))
    return line, sig, line - sig


def dmi(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        di_len: int, adx_len: int):
    """Pine ta.dmi(diLength, adxSmoothing) -> (+DI, -DI, ADX)."""
    up = np.diff(high, prepend=np.nan)
    dn = -np.diff(low, prepend=np.nan)
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    plus_dm[0] = np.nan
    minus_dm[0] = np.nan
    trur = rma(true_range(high, low, close), di_len)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus = 100.0 * rma(plus_dm, di_len) / trur
        minus = 100.0 * rma(minus_dm, di_len) / trur
        s = plus + minus
        dx = 100.0 * np.abs(plus - minus) / np.where(s == 0, 1.0, s)
    adx_ = rma(dx, adx_len)
    return plus, minus, adx_


def crossover(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pine ta.crossover(a,b): a>b now, a<=b on the previous bar."""
    prev_a = np.concatenate(([np.nan], a[:-1]))
    prev_b = np.concatenate(([np.nan], b[:-1]))
    return (a > b) & (prev_a <= prev_b)


def crossunder(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    prev_a = np.concatenate(([np.nan], a[:-1]))
    prev_b = np.concatenate(([np.nan], b[:-1]))
    return (a < b) & (prev_a >= prev_b)


def rolling_min(x: np.ndarray, length: int) -> np.ndarray:
    """ta.lowest(x, len) including current bar."""
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        lo = max(0, i - length + 1)
        out[i] = np.nanmin(x[lo : i + 1])
    return out


def rolling_max(x: np.ndarray, length: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        lo = max(0, i - length + 1)
        out[i] = np.nanmax(x[lo : i + 1])
    return out
