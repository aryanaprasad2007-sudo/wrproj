"""
data.py â€” 5-minute bar loader for the iAPE validation harness.

Sources, in order of preference:
  1. Alpaca historical SIP bars (full market, years of history) â€” used automatically
     when APCA_API_KEY_ID / APCA_API_SECRET_KEY are set in the environment. Free tier
     works: SIP data older than 15 minutes is included.
  2. yfinance â€” no keys needed, but 5m history is capped at ~60 days.

Bars are cached under backtest/cache/ so reruns are instant and deterministic.
All frames come back tz-aware in America/New_York, RTH only (09:30â€“16:00),
columns: open, high, low, close, volume.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"
NY = "America/New_York"


def _env(name: str):
    """os.environ, falling back to the Windows User registry â€” child shells
    spawned before [Environment]::SetEnvironmentVariable(...,'User') took
    effect won't have the var in os.environ, but the registry always does."""
    v = os.environ.get(name)
    if v:
        return v
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    return None


def _cached_or_none(symbol: str, interval: str, days: int):
    """Most recent cache file for this series, any date stamp — historical bars
    don't go stale, so yesterday's 730d cache is as good as today's."""
    hits = sorted(CACHE_DIR.glob(f"{symbol}_{interval}_{days}d_*.parquet"))
    return pd.read_parquet(hits[-1]) if hits else None


def load_bars(symbol: str, days: int = 59, interval: str = "5m",
              refresh: bool = False) -> pd.DataFrame:
    CACHE_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    cache = CACHE_DIR / f"{symbol}_{interval}_{days}d_{stamp}.parquet"
    if not refresh:
        hit = _cached_or_none(symbol, interval, days)
        if hit is not None:
            return hit

    if _env("APCA_API_KEY_ID") and _env("APCA_API_SECRET_KEY"):
        df = _alpaca_bars(symbol, days, interval)
        src = "alpaca-sip"
    else:
        df = _yf_bars(symbol, days, interval)
        src = "yfinance"

    if interval == "1d":  # daily bars have no intraday session to filter
        df = df[~df.index.duplicated(keep="first")].sort_index() \
            .dropna(subset=["open", "high", "low", "close"])
    else:
        df = _clean_rth(df)
    df.attrs["source"] = src
    try:
        df.to_parquet(cache)
    except Exception:
        pass  # parquet engine missing -> just skip caching
    return df


def _yf_bars(symbol: str, days: int, interval: str) -> pd.DataFrame:
    import yfinance as yf

    days = min(days, 59)  # yfinance hard cap for 5m data
    df = yf.download(symbol, period=f"{days}d", interval=interval,
                     auto_adjust=False, prepost=False, progress=False,
                     multi_level_index=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {symbol}")
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index = pd.DatetimeIndex(df.index).tz_convert(NY)
    return df


def _alpaca_bars(symbol: str, days: int, interval: str) -> pd.DataFrame:
    tf = {"5m": "5Min", "1m": "1Min", "15m": "15Min", "1h": "1Hour",
          "1d": "1Day"}[interval]
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (datetime.now(timezone.utc) - timedelta(minutes=16)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {
        "APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY"),
    }
    rows, token = [], None
    while True:
        q = {"timeframe": tf, "start": start, "end": end, "limit": 10000,
             "adjustment": "split", "feed": "sip"}
        if token:
            q["page_token"] = token
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers=headers)
        payload = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    payload = json.loads(r.read().decode())
                break
            except Exception:
                if attempt == 4:
                    raise
                import time as _t
                _t.sleep(2 ** attempt)  # 1,2,4,8s backoff on resets/rate limits
        rows.extend(payload.get("bars") or [])
        token = payload.get("next_page_token")
        if not token:
            break
    if not rows:
        raise RuntimeError(f"Alpaca returned no bars for {symbol}")
    df = pd.DataFrame(rows).rename(columns={
        "t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(NY)
    return df.set_index("time")[["open", "high", "low", "close", "volume"]]


def load_bars_1m(symbol: str, days: int = 29, refresh: bool = False) -> pd.DataFrame:
    """1-minute bars. Alpaca (years) when keys are set; else yfinance, which caps
    1m data at ~30 days lookback and 7 days per request â€” so we stitch chunks."""
    CACHE_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    cache = CACHE_DIR / f"{symbol}_1m_{days}d_{stamp}.parquet"
    if not refresh:
        hit = _cached_or_none(symbol, "1m", days)
        if hit is not None:
            return hit

    if _env("APCA_API_KEY_ID") and _env("APCA_API_SECRET_KEY"):
        df = _alpaca_bars(symbol, days, "1m")
        src = "alpaca-sip"
    else:
        import yfinance as yf
        days = min(days, 29)
        chunks = []
        end = datetime.now()
        start_lim = end - timedelta(days=days)
        cur_end = end
        while cur_end > start_lim:
            cur_start = max(cur_end - timedelta(days=7), start_lim)
            d = yf.download(symbol, start=cur_start.strftime("%Y-%m-%d"),
                            end=(cur_end + timedelta(days=1)).strftime("%Y-%m-%d"),
                            interval="1m", auto_adjust=False, prepost=False,
                            progress=False, multi_level_index=False)
            if d is not None and not d.empty:
                d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
                d.index = pd.DatetimeIndex(d.index).tz_convert(NY)
                chunks.append(d)
            cur_end = cur_start
        if not chunks:
            raise RuntimeError(f"no 1m data for {symbol}")
        df = pd.concat(chunks)
        src = "yfinance"

    df = _clean_rth(df)
    df.attrs["source"] = src
    try:
        df.to_parquet(cache)
    except Exception:
        pass
    return df


def resample_5m(df1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1m -> 5m so both MTF layers share identical source data."""
    g = df1m.resample("5min", label="left", closed="left")
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "volume": g["volume"].sum(),
    }).dropna(subset=["open", "close"])
    return _clean_rth(out)


def _clean_rth(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df.index.duplicated(keep="first")].sort_index()
    t = df.index.time
    import datetime as _dt
    mask = (t >= _dt.time(9, 30)) & (t < _dt.time(16, 0))
    df = df[mask]
    return df.dropna(subset=["open", "high", "low", "close"])

