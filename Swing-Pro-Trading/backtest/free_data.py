"""
free_data.py — $0 orthogonal-data sources (the no-Unusual-Whales stack).

  • DIX / GEX  — SqueezeMetrics daily CSV (SPX dark-pool buying index + dealer
    gamma exposure), 2011 → present. Market-level.
  • FINRA daily short-sale volume — per-ticker off-exchange short volume
    (CNMSshvol files, published nightly, free, no auth). short_ratio =
    ShortVolume / TotalVolume is a widely-used dark-pool-behaviour footprint.

Usage:
  py free_data.py --fetch-finra          # one-time: pulls ~2y of daily files
  (DIX downloads automatically on first use)
"""
from __future__ import annotations

import argparse
import io
import time
import urllib.request
from pathlib import Path

import pandas as pd

CACHE = Path(__file__).parent / "cache"
DIX_URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d}.txt"
BASKET = ["AAPL", "NVDA", "TSLA", "MSFT", "META"]


def load_dix(refresh: bool = False) -> pd.DataFrame:
    """date-indexed DataFrame with columns: price, dix, gex."""
    CACHE.mkdir(exist_ok=True)
    f = CACHE / "dix_gex.csv"
    if refresh or not f.exists():
        req = urllib.request.Request(DIX_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            f.write_bytes(r.read())
    df = pd.read_csv(f, parse_dates=["date"]).set_index("date")
    return df


def load_finra_short(days: int = 760) -> pd.DataFrame:
    """Long-form DataFrame: date, symbol, short_ratio (basket symbols only).
    Fetches each trading day's file once; slim results cached permanently."""
    CACHE.mkdir(exist_ok=True)
    f = CACHE / "finra_short_basket.csv"
    have = pd.read_csv(f, parse_dates=["date"]) if f.exists() else \
        pd.DataFrame(columns=["date", "symbol", "short_ratio"])
    have_dates = set(pd.to_datetime(have["date"]).dt.date) if len(have) else set()

    end = pd.Timestamp.today().normalize()
    all_days = pd.bdate_range(end - pd.Timedelta(days=days), end)
    todo = [d for d in all_days if d.date() not in have_dates]
    if not todo:
        return have

    rows = []
    print(f"FINRA: fetching {len(todo)} daily files (one-time; slim cache after)...")
    for i, d in enumerate(todo):
        url = FINRA_URL.format(d=d.strftime("%Y%m%d"))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", errors="replace")
        except Exception:
            continue  # holiday / not yet published
        for line in text.splitlines()[1:]:
            p = line.split("|")
            if len(p) >= 5 and p[1] in BASKET:
                try:
                    sv, tv = float(p[2]), float(p[4])
                    if tv > 0:
                        rows.append({"date": d, "symbol": p[1], "short_ratio": sv / tv})
                except ValueError:
                    pass
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(todo)} days...")
            time.sleep(1)  # be polite
    new = pd.DataFrame(rows)
    out = pd.concat([have, new], ignore_index=True) if len(have) else new
    out = out.drop_duplicates(["date", "symbol"]).sort_values(["date", "symbol"])
    out.to_csv(f, index=False)
    print(f"FINRA: {len(out)} rows cached ({out.date.min()} -> {out.date.max()})")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-finra", action="store_true")
    ap.add_argument("--days", type=int, default=760)
    args = ap.parse_args()
    if args.fetch_finra:
        load_finra_short(args.days)
    else:
        d = load_dix()
        print(d.tail())
