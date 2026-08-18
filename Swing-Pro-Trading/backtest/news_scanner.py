"""
news_scanner.py — iAPE News Scanner ("what does the news say about MY stock?").

WHAT IT DOES
  * ONE stock at a time. You type a ticker on the page (any ticker — it doesn't
    have to be on the trading bot's list) and the scanner pulls that stock's
    fresh headlines (Google News RSS, free, no key).
  * Sends them to Claude (claude-fable-5) and gets back ONE clear judgement a
    person with no finance background can read: a bottom line in plain English,
    why, good signs, warning signs, what could flip the read, and how confident
    the AI is (0-100).
  * Serves a local web page (http://127.0.0.1:8790) that shows the verdict,
    refreshes itself, and lets you switch stocks or rescan anytime.

WHEN IT RUNS (all times local = PT, same convention as every SwingPro_* task)
  * Pre-market briefing: first weekday read fires at ~05:35, so the verdict on
    your focus stock is waiting before the 06:30 open.
  * Market hours: re-reads every N minutes (default 10, operator-settable)
    06:30–13:00 on weekdays.
  * Anytime: the "Scan again" button, or typing a new ticker.

COST CONTROL (Fable 5 is $10/$50 per MTok)
  * One ticker per call, plus change detection: the stock is only re-judged
    when its headline set actually changed (or the verdict is >24h old).
    The UI shows estimated $ spent today.

HONESTY LINE (house rules): this is an INFORMATIONAL research read. It is not
a validated signal, it is NOT wired into forward_trader, and it places no
orders. Every judgement is logged to the verdict ledger and scored by the
referee (track-record card) — same bar as everything else: ≥30 scored calls
per bucket before the reads earn any trust.

API key: reads ANTHROPIC_API_KEY from the environment, falling back to the
Windows User registry (same _env pattern as the rest of the stack). With no
key the scanner still runs in headlines-only mode and the page shows setup
instructions.

Run:  py news_scanner.py            (starts server + opens browser)
      py news_scanner.py --headless (server only — what the scheduled task uses)
      py news_scanner.py --once     (single scan to stdout/state file, no server)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
STATE_F = CACHE / "news_state.json"
SETTINGS_F = CACHE / "news_settings.json"
VERDICTS_CSV = CACHE / "news_verdicts.csv"      # append-only judgment ledger
SCORECARD_F = CACHE / "news_scorecard.json"     # the referee's aggregate
LOG_F = HERE / "news_scanner.log"
FWD_STATE_F = HERE / "forward_state.json"       # bot holdings/queue (read-only)
DASHBOARD_API = "http://127.0.0.1:8788/api/state"

CSV_FIELDS = ["ts", "epoch", "date", "ticker", "stance", "conviction",
              "price", "briefing", "model"]

PORT_DEFAULT = 8790
MODEL = "claude-fable-5"
FALLBACK_MODEL = "claude-opus-4-8"
# $/MTok for the spend estimate shown in the UI (thinking bills as output).
PRICES_PER_MTOK = {"claude-fable-5": (10.0, 50.0), "claude-opus-4-8": (5.0, 25.0)}

TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,8}$")

# Known names for nicer headlines queries; anything else resolves via yfinance
# (best-effort, cached) and falls back to the raw ticker.
COMPANY = {
    "AAPL": "Apple", "NVDA": "Nvidia", "TSLA": "Tesla", "MSFT": "Microsoft",
    "META": "Meta Platforms", "MSTR": "MicroStrategy", "ORCL": "Oracle",
    "NFLX": "Netflix", "AVGO": "Broadcom", "CRWD": "CrowdStrike",
    "JPM": "JPMorgan", "GS": "Goldman Sachs", "XOM": "Exxon Mobil",
    "CVX": "Chevron", "CAT": "Caterpillar", "DE": "Deere",
    "BA": "Boeing", "WMT": "Walmart", "COST": "Costco",
    "HD": "Home Depot", "UNH": "UnitedHealth", "DIS": "Disney",
    "KO": "Coca-Cola", "SPY": "S&P 500",
}

# After this many consecutive judge failures, every scan says DEGRADED out loud
# instead of the bare "SCAN done". A dead key used to look identical to a healthy
# scan in the log (headlines + local signals still land), which is how a revoked
# key went unnoticed for 12 days in July 2026.
DEGRADED_AFTER = 3

SETTINGS_DEFAULTS = {
    "focus_ticker": "",        # the ONE stock being read ("" → default at load)
    "interval_min": 10,        # market-hours re-read cadence
    "max_headlines": 8,        # per scan (one stock, so we can afford more)
    "effort": "medium",        # Fable effort: low | medium | high
}

_scan_lock = threading.Lock()
_scan_request = threading.Event()   # set by the UI's "Scan again" / ticker change
_scanning = False


# ── small utilities ──────────────────────────────────────────────────────────

def log(msg: str):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        if LOG_F.exists() and LOG_F.stat().st_size > 500_000:
            LOG_F.write_text("")            # keep the log small
        with LOG_F.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _env(name: str):
    """os.environ, falling back to the Windows User registry (HKCU\\Environment)
    — same pattern as data._env: long-lived shells keep stale env, the registry
    is the source of truth."""
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


def _atomic_write(path: Path, obj):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _default_ticker() -> str:
    """First bot focus symbol if the operator set one, else AAPL."""
    try:
        import botconfig
        fs = botconfig.load().get("focus_symbols") or []
        if fs and TICKER_RE.match(str(fs[0]).upper()):
            return str(fs[0]).upper()
    except Exception:
        pass
    return "AAPL"


def load_settings() -> dict:
    cfg = dict(SETTINGS_DEFAULTS)
    if SETTINGS_F.exists():
        try:
            saved = json.loads(SETTINGS_F.read_text())
            for k in cfg:
                if k in saved:
                    cfg[k] = saved[k]
        except (json.JSONDecodeError, OSError):
            pass
    # clamps — a bad hand-edit can't produce a runaway cadence or prompt
    try:
        cfg["interval_min"] = int(min(60, max(5, float(cfg["interval_min"]))))
    except (TypeError, ValueError):
        cfg["interval_min"] = 10
    try:
        cfg["max_headlines"] = int(min(12, max(3, float(cfg["max_headlines"]))))
    except (TypeError, ValueError):
        cfg["max_headlines"] = 8
    if cfg.get("effort") not in ("low", "medium", "high"):
        cfg["effort"] = "medium"
    t = str(cfg.get("focus_ticker") or "").strip().upper()
    cfg["focus_ticker"] = t if TICKER_RE.match(t) else _default_ticker()
    return cfg


def save_settings(patch: dict) -> dict:
    cfg = load_settings()
    for k in SETTINGS_DEFAULTS:
        if k in patch:
            cfg[k] = patch[k]
    _atomic_write(SETTINGS_F, cfg)
    return load_settings()


def load_state() -> dict:
    if STATE_F.exists():
        try:
            return json.loads(STATE_F.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"updated": None, "briefing_date": None, "last_scan": 0,
            "verdicts": {}, "spend": {"date": None, "usd": 0.0, "calls": 0},
            "last_error": None, "scanner_state": "running"}


# ── news ingestion (Google News RSS — free, no key) ─────────────────────────

_names: dict = {}


def company_name(sym: str) -> str:
    """Company name for the headlines query + UI. Known map first, then a
    cached best-effort yfinance lookup (scan thread only), else the ticker."""
    if sym in COMPANY:
        return COMPANY[sym]
    if sym in _names:
        return _names[sym]
    name = sym
    try:
        import yfinance as yf
        info = yf.Ticker(sym).info or {}
        raw = info.get("shortName") or info.get("longName")
        if raw:
            name = re.sub(r",? ?(Inc|Corp|Corporation|Company|Co|Ltd|PLC|plc"
                          r"|N\.?V\.?|S\.?E\.?|SA)\.?$", "", str(raw).strip(),
                          flags=re.I).strip() or sym
    except Exception:
        pass
    _names[sym] = name
    return name


def fetch_headlines(sym: str, max_headlines: int) -> list[dict]:
    company = company_name(sym)
    q = urllib.parse.quote(f'"{company}" stock when:2d')
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        root = ET.fromstring(r.read())
    now = datetime.now(timezone.utc)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        # Google formats titles as "Headline - Source"
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        age_min = None
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "")
            age_min = max(0, int((now - pub).total_seconds() // 60))
        except (TypeError, ValueError):
            pass
        items.append({"title": title, "link": (it.findtext("link") or "").strip(),
                      "source": src, "age_min": age_min})
    items.sort(key=lambda x: x["age_min"] if x["age_min"] is not None else 9999)
    # drop listicle noise the model would be told to ignore anyway
    junk = re.compile(r"\b(\d+ (best|top) stocks|stocks to buy|motley fool)\b", re.I)
    items = [x for x in items if not junk.search(x["title"])] or items
    return items[:max_headlines]


def fetch_prices(symbols: list[str]) -> dict:
    """Last close + 5-day % change per symbol (context for the model + UI).
    Best-effort: any failure returns {} and the scan proceeds without prices."""
    try:
        import yfinance as yf
        syms = list(dict.fromkeys(symbols + ["SPY"]))
        df = yf.download(" ".join(syms), period="7d",
                         progress=False, auto_adjust=True, threads=True)
        closes = df["Close"] if "Close" in df else df
        out = {}
        for s in syms:
            try:
                col = closes[s].dropna()
                if len(col) >= 2:
                    last = float(col.iloc[-1])
                    base = float(col.iloc[0])
                    out[s] = {"last": round(last, 2),
                              "chg5d": round((last / base - 1) * 100, 2)}
            except Exception:
                continue
        return out
    except Exception as e:
        log(f"PRICE_ERROR: {e}")
        return {}


def news_hash(headlines: list[dict]) -> str:
    return hashlib.sha1("|".join(sorted(h["title"] for h in headlines))
                        .encode("utf-8", "replace")).hexdigest()[:16]


# ── verdict ledger + scorecard (the referee) ────────────────────────────────

def log_verdicts(rows: list[dict]):
    """Append every judged call to the permanent ledger. This is the raw
    material for the track record — the referee that decides whether these AI
    reads have any edge (house rule: chart eyes propose, harness disposes)."""
    new = not VERDICTS_CSV.exists()
    VERDICTS_CSV.parent.mkdir(exist_ok=True)
    with VERDICTS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def compute_scorecard() -> dict | None:
    """Score the ledger: for the FIRST judgment of each (date, ticker) — the
    actionable morning call — measure the move from the logged price to the
    daily close 1 / 3 / 5 trading days out, with SPY over the same windows for
    context. Only completed closes count (today's bar is excluded while the
    session is still open). Writes cache/news_scorecard.json."""
    if not VERDICTS_CSV.exists():
        return None
    rows = []
    with VERDICTS_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["price"] = float(r["price"])
                r["conviction"] = int(float(r["conviction"]))
            except (TypeError, ValueError):
                continue                          # unpriced rows can't score
            if r.get("ticker") and r.get("date"):
                rows.append(r)
    first = {}
    for r in rows:                    # ledger is chronological (append-only)
        first.setdefault((r["date"], r["ticker"]), r)
    rows = list(first.values())
    if not rows:
        return None

    import pandas as pd
    import yfinance as yf
    tickers = sorted({r["ticker"] for r in rows})
    # start a week early so SPY has a baseline close BEFORE the first call
    start = (pd.Timestamp(min(r["date"] for r in rows))
             - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    df = yf.download(" ".join(tickers + ["SPY"]), start=start,
                     progress=False, auto_adjust=True, threads=True)
    try:
        closes = df["Close"]
    except KeyError:
        closes = df
    if getattr(closes.index, "tz", None) is not None:
        closes.index = closes.index.tz_localize(None)
    if market_phase(datetime.now()) in ("premarket", "open"):
        closes = closes[closes.index < pd.Timestamp(f"{datetime.now():%Y-%m-%d}")]

    def horizon_ret(sym, date_s, base, k):
        try:
            ser = closes[sym].dropna()
        except (KeyError, TypeError):
            return None
        if not len(ser) or not base:
            return None
        i = int(ser.index.searchsorted(pd.Timestamp(date_s))) + (k - 1)
        if i >= len(ser):
            return None                           # horizon not reached yet
        return float(ser.iloc[i]) / float(base) - 1.0

    def spy_ret(date_s, k):
        try:
            ser = closes["SPY"].dropna()
        except (KeyError, TypeError):
            return None
        i0 = int(ser.index.searchsorted(pd.Timestamp(date_s)))
        if i0 == 0 or i0 + (k - 1) >= len(ser):
            return None
        return float(ser.iloc[i0 + k - 1]) / float(ser.iloc[i0 - 1]) - 1.0

    def bucket(r):
        if r["stance"] == "bullish":
            return "bullish_hi" if r["conviction"] >= 70 else "bullish_lo"
        return r["stance"]

    out = {"computed": f"{datetime.now():%Y-%m-%d %H:%M}",
           "calls_scoped": len(rows), "buckets": {}}
    for name in ("bullish_hi", "bullish_lo", "neutral", "bearish"):
        brows = [r for r in rows if bucket(r) == name]
        if not brows:
            continue
        b = {"n": len(brows)}
        for k in (1, 3, 5):
            rets, spys, hits = [], [], []
            for r in brows:
                rr = horizon_ret(r["ticker"], r["date"], r["price"], k)
                if rr is None:
                    continue
                rets.append(rr)
                sr = spy_ret(r["date"], k)
                if sr is not None:
                    spys.append(sr)
                if name.startswith("bullish"):
                    hits.append(rr > 0)
                elif name == "bearish":
                    hits.append(rr < 0)
            b[f"h{k}"] = {
                "n": len(rets),
                "avg": round(sum(rets) / len(rets), 5) if rets else None,
                "hit": round(sum(hits) / len(hits), 3) if hits else None,
                "spy": round(sum(spys) / len(spys), 5) if spys else None,
            }
        out["buckets"][name] = b
    _atomic_write(SCORECARD_F, out)
    return out


def maybe_scorecard(force: bool = False):
    try:
        if not force and SCORECARD_F.exists() \
                and time.time() - SCORECARD_F.stat().st_mtime < 12 * 3600:
            return
        sc = compute_scorecard()
        if sc:
            log(f"SCORECARD computed over {sc['calls_scoped']} first-of-day calls")
    except Exception as e:
        log(f"SCORECARD_ERROR: {e}")


# ── validated-system confluence (read-only) ─────────────────────────────────

_sys = {"t": 0.0, "data": None, "src": None}


def _read_forward_state():
    """Bot holdings + queued entries straight from forward_state.json —
    read-only, always available, no dashboard required."""
    try:
        st = json.loads(FWD_STATE_F.read_text())
    except (OSError, json.JSONDecodeError):
        return {}, {}
    hold = {}
    for book, key in (("intraday", "positions"), ("daily", "daily_positions")):
        for sym, p in (st.get(key) or {}).items():
            qty = p.get("qty") or p.get("shares") or 0
            hold[sym.upper()] = {"book": book, "qty": qty}
    queued = {sym.upper(): str(p.get("fill_date") or "")
              for sym, p in (st.get("daily_pending") or {}).items()}
    return hold, queued


def system_signals(allow_compute: bool) -> dict:
    """DAILY-engine signal state (none/forming/triggered) per symbol.
    Source 1: the control dashboard's /api/state (it recomputes every 240s).
    Source 2 (dashboard closed — the usual case pre-market): compute here via
    forward_trader, cached 15 min. allow_compute=False keeps web requests
    fast: only the scan thread ever does the heavy compute."""
    now = time.time()
    if _sys["data"] and now - _sys["t"] < (300 if _sys["src"] == "dashboard" else 900):
        return _sys["data"]
    try:
        req = urllib.request.Request(DASHBOARD_API)
        with urllib.request.urlopen(req, timeout=2.5) as r:
            js = json.loads(r.read())
        rows = (js.get("scanner") or {}).get("rows") or []
        if rows:
            data = {r["symbol"]: {"signal": r.get("signal"),
                                  "above_trend": r.get("above_trend"),
                                  "mkt_ok": r.get("mkt_ok")} for r in rows}
            _sys.update(t=now, data=data, src="dashboard")
            return data
    except Exception:
        pass
    if not allow_compute:
        return _sys["data"] or {}
    try:
        import botconfig
        import forward_trader as ft
        spy = ft.daily_bars("SPY", 460)
        data = {}
        for sym in ft.daily_universe(botconfig.load()):
            try:
                d = ft.daily_bars(sym, 460)
                if len(d) >= 250 and len(spy) >= 250:
                    sg = ft.compute_signals(d, spy, ft.CFG_D)
                    i = len(d) - 1
                    data[sym] = {
                        "signal": ("triggered" if bool(sg["go_long"][i])
                                   else "forming" if bool(sg["long_state"][i])
                                   else "none"),
                        "above_trend": bool(float(sg["close"][i])
                                            > float(sg["trend_ma"][i])),
                        "mkt_ok": bool(sg["mkt_long_ok"][i]),
                    }
            except Exception:
                continue
        if data:
            _sys.update(t=now, data=data, src="local")
            log(f"SYSTEM signals computed locally for {len(data)} symbols")
        return data
    except Exception as e:
        log(f"SYSTEM_READ_ERROR: {e}")
        return _sys["data"] or {}


def system_context(sym: str) -> str:
    """One line of operator context for the model's swing_note: book size,
    per-trade budget, the daily engine's signal for this stock, holdings and
    queued entries. Best-effort — '' when nothing is readable."""
    try:
        try:
            import botconfig
            bc = botconfig.load()
        except Exception:
            bc = {}
        broker = (_env("SWINGPRO_BROKER") or "alpaca").lower()
        if broker == "webull":
            book = float(bc.get("webull_sizing_equity") or 2000.0)
        else:
            book = float(bc.get("alpaca_sizing_equity") or 0) or 100000.0
        per_trade = round(book * float(bc.get("sizing_pct") or 10.0) / 100.0)
        hold, queued = _read_forward_state()
        sig = (system_signals(allow_compute=False) or {}).get(sym)
        parts = [f"paper trading book ${book:.0f}, per-trade budget ${per_trade}"]
        parts.append(f"trading engine's own signal for {sym}: "
                     + (sig["signal"] if sig and sig.get("signal")
                        else "not on the engine's watchlist"))
        if sym in hold:
            parts.append(f"the bot currently HOLDS {sym}"
                         + (f" (qty {hold[sym]['qty']})" if hold[sym]["qty"] else ""))
        if sym in queued:
            parts.append(f"{sym} is queued to buy on {queued[sym]}")
        return "; ".join(parts)
    except Exception:
        return ""


# ── the Fable 5 judgment call ────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the news analyst for iAPE, a personal trading research \
tool. You receive fresh headlines and price context for ONE stock and produce ONE \
clear judgement that a person with no finance background can read and immediately \
understand.

Standards:
- Make one honest call: over the next 1-5 trading days, does the news point UP \
(bullish), DOWN (bearish), or NOWHERE (neutral) for this stock? Most days the honest \
answer is neutral — say so plainly rather than forcing a story.
- bottom_line: ONE short sentence in plain everyday English that answers "so what's \
the deal with this stock right now?". No jargon.
- explanation: 2-4 short sentences expanding on the bottom line. If a financial term \
is unavoidable (earnings, guidance, downgrade…), gloss it in a few words.
- good_signs / bad_signs: up to 3 each, short plain phrases a non-professional gets \
instantly (e.g. "a big bank just raised its price target", "sales grew slower than \
hoped"). Empty lists are fine on a quiet day.
- watch_out: one sentence — the single most likely thing that would flip this read.
- conviction is 0-100: how confident you are in the stance you chose (a confident \
neutral can be 60+). Reserve 70+ for genuinely material catalysts: earnings/guidance \
surprises, M&A, regulatory decisions, major product or contract news, substantive \
analyst action.
- Ignore listicles and clickbait ("N stocks to buy now") — noise, not catalysts. \
Weight recency: a 40-hour-old headline the market already traded on is weaker than a \
2-hour-old one.
- swing_note: ONE short plain sentence connecting your read to the operator context \
in the payload (their trading bot's signal, holdings, or budget for this stock), only \
when there is something worth saying — otherwise an empty string. The bot's own \
signals decide its entries; never tell the operator to take a trade.
- This output is informational research for a human reviewing a paper-trading \
system. It is not a trade instruction and not financial advice; never phrase it as one.
Return ONLY the JSON demanded by the schema."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "stance": {"type": "string",
                   "enum": ["bullish", "neutral", "bearish"]},
        "conviction": {"type": "integer"},
        "bottom_line": {"type": "string"},
        "explanation": {"type": "string"},
        "good_signs": {"type": "array", "items": {"type": "string"}},
        "bad_signs": {"type": "array", "items": {"type": "string"}},
        "watch_out": {"type": "string"},
        "swing_note": {"type": "string"},
    },
    "required": ["ticker", "stance", "conviction", "bottom_line", "explanation",
                 "good_signs", "bad_signs", "watch_out", "swing_note"],
    "additionalProperties": False,
}


def build_payload(sym: str, headlines: list[dict], prices: dict,
                  briefing: bool) -> str:
    lines = [f"NOW: {datetime.now():%A %Y-%m-%d %H:%M} PT"
             + ("  — PRE-MARKET BRIEFING (first read of the day)" if briefing else ""),
             ""]
    p = prices.get(sym)
    px = (f" — last price {p['last']}, {p['chg5d']:+.1f}% over 5 days" if p
          else " — no price data found (possibly a bad ticker)")
    lines.append(f"STOCK TO JUDGE: {sym} ({company_name(sym)}){px}")
    spy = prices.get("SPY")
    if spy:
        lines.append(f"MARKET CONTEXT: SPY last {spy['last']}, 5-day {spy['chg5d']:+.1f}%")
    lines.append("")
    if not headlines:
        lines.append("HEADLINES: none found in the last 2 days — a quiet news "
                     "stretch; judge accordingly.")
    else:
        lines.append("HEADLINES (newest first):")
        for h in headlines:
            age = (f"{h['age_min']}m" if h["age_min"] is not None and h["age_min"] < 120
                   else f"{h['age_min']//60}h" if h["age_min"] is not None else "?")
            lines.append(f"  - [{age} ago | {h['source'] or 'unknown'}] {h['title']}")
    ctx = system_context(sym)
    if ctx:
        lines.append("")
        lines.append(f"OPERATOR CONTEXT (for swing_note only): {ctx}")
    return "\n".join(lines)


def judge(payload: str, effort: str, api_key: str) -> tuple[dict, dict]:
    """One Fable 5 call → (parsed JSON verdict, usage info). Raises on failure."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-06-01"],
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": payload}],
        # extra_body so this works regardless of SDK version typing:
        # fallbacks = auto-retry on Opus 4.8 if Fable's safety classifiers
        # decline (finance news is benign, but belt-and-suspenders);
        # output_config = structured output guarantees schema-valid JSON.
        extra_body={
            "fallbacks": [{"model": FALLBACK_MODEL}],
            "output_config": {"effort": effort,
                              "format": {"type": "json_schema",
                                         "schema": OUTPUT_SCHEMA}},
        },
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined the request (refusal)")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("response truncated at max_tokens")
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    served_by = getattr(resp, "model", MODEL)
    in_rate, out_rate = PRICES_PER_MTOK.get(
        next((m for m in PRICES_PER_MTOK if served_by.startswith(m)), MODEL),
        PRICES_PER_MTOK[MODEL])
    usage = {
        "model": served_by,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "usd": round(resp.usage.input_tokens * in_rate / 1e6
                     + resp.usage.output_tokens * out_rate / 1e6, 4),
    }
    return data, usage


# ── the scan ─────────────────────────────────────────────────────────────────

def scan(force_judge: bool = False, briefing: bool = False):
    global _scanning
    with _scan_lock:
        _scanning = True
        try:
            _scan_inner(force_judge, briefing)
        except Exception as e:
            log(f"SCAN_ERROR: {e}")
            msg = str(e)
            err_state = "scanner_down"
            if "401" in msg or "authentication" in msg.lower():
                err_state = "key_dead"
                msg = ("the API key was rejected (it may have been revoked). "
                       "Create a fresh key at console.anthropic.com, then run: "
                       '[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY",'
                       '"sk-ant-…","User") — headlines still work meanwhile.')
            elif "URLError" in msg or "ConnectionError" in msg or "timeout" in msg.lower():
                err_state = "network_error"
            st = load_state()
            st["last_error"] = f"{datetime.now():%H:%M} — {msg}"
            st["scanner_state"] = err_state
            _atomic_write(STATE_F, st)
        finally:
            _scanning = False


def _scan_inner(force_judge: bool, briefing: bool):
    settings = load_settings()
    st = load_state()
    sym = settings["focus_ticker"]
    today = f"{datetime.now():%Y-%m-%d}"
    log(f"SCAN start ({sym}, briefing={briefing})")

    try:
        hs = fetch_headlines(sym, settings["max_headlines"])
    except Exception as e:
        log(f"NEWS_ERROR {sym}: {e}")
        hs = None                                  # fetch failed — keep old
    prices = fetch_prices([sym])

    v = st.setdefault("verdicts", {}).setdefault(
        sym, {"ticker": sym, "stance": "neutral", "conviction": 0,
              "bottom_line": None, "explanation": None, "good_signs": [],
              "bad_signs": [], "watch_out": None, "swing_note": None,
              "news_hash": None, "judged_epoch": 0, "judged_model": None})
    v["company"] = company_name(sym)
    if hs is not None:
        v["headlines"] = hs
    if sym in prices:
        v["price"] = prices[sym]

    # judge only when something changed (or the verdict aged out) — cost control
    now = time.time()
    have_news = v.get("headlines") is not None
    h = news_hash(v.get("headlines") or [])
    stale = (not v.get("judged_epoch")) or v.get("news_hash") != h \
        or (now - v.get("judged_epoch", 0)) > 24 * 3600
    need = (force_judge or briefing or stale) and have_news

    api_key = _env("ANTHROPIC_API_KEY")
    if need and api_key:
        try:
            _judge_and_apply(st, v, sym, prices, settings, briefing, today)
            st["judge_fail_streak"] = 0
            st.pop("judge_fail_since", None)
            st.pop("last_error", None)
            st["scanner_state"] = "running"
        except Exception as e:
            # a failed AI call must not throw away the fetched headlines/prices
            # or stall last_scan (that would retry every 30s all session long)
            log(f"JUDGE_ERROR: {e}")
            msg = str(e)
            err_state = "scanner_down"  # explicit state: distinguish from "ran, found nothing"
            if "401" in msg or "authentication" in msg.lower():
                err_state = "key_dead"
                msg = ("the API key was rejected (it may have been revoked). "
                       "Create a fresh key at console.anthropic.com, then run: "
                       '[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY",'
                       '"sk-ant-…","User") — headlines still work meanwhile.')
            elif "URLError" in msg or "ConnectionError" in msg or "timeout" in msg.lower():
                err_state = "network_error"
            st["last_error"] = f"{datetime.now():%H:%M} — {msg}"
            st["scanner_state"] = err_state
            st["judge_fail_streak"] = int(st.get("judge_fail_streak") or 0) + 1
            st.setdefault("judge_fail_since", f"{datetime.now():%Y-%m-%d %H:%M}")
    elif need:
        log(f"SKIP judgment for {sym} — no ANTHROPIC_API_KEY")
    else:
        log(f"CARRIED {sym} — headlines unchanged")

    if briefing:
        st["briefing_date"] = today
        st["briefing_at"] = f"{datetime.now():%H:%M}"
    st["last_scan"] = time.time()
    st["updated"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    _atomic_write(STATE_F, st)
    # warm the confluence read (dashboard API if up, else local engine compute)
    system_signals(allow_compute=True)
    streak = int(st.get("judge_fail_streak") or 0)
    if streak >= DEGRADED_AFTER:
        log(f"SCAN done — DEGRADED: no AI judgment for {streak} consecutive scans "
            f"since {st.get('judge_fail_since') or '?'} — headlines and local "
            f"signals only. Last cause: {st.get('last_error') or 'unknown'}")
    else:
        log("SCAN done")


def _judge_and_apply(st: dict, v: dict, sym: str, prices: dict,
                     settings: dict, briefing: bool, today: str):
    """The AI call + everything that depends on its result (verdict fields,
    ledger row, spend). Split out so a failure here can't abort the scan."""
    payload = build_payload(sym, v.get("headlines") or [], prices, briefing)
    data, usage = judge(payload, settings["effort"], _env("ANTHROPIC_API_KEY"))
    judged_at = time.time()
    v.update(
        stance=(data.get("stance") if data.get("stance")
                in ("bullish", "neutral", "bearish") else "neutral"),
        conviction=int(min(100, max(0, int(data.get("conviction") or 0)))),
        bottom_line=data.get("bottom_line"),
        explanation=data.get("explanation"),
        good_signs=(data.get("good_signs") or [])[:3],
        bad_signs=(data.get("bad_signs") or [])[:3],
        watch_out=data.get("watch_out"),
        swing_note=data.get("swing_note") or "",
        news_hash=news_hash(v.get("headlines") or []),
        judged_epoch=judged_at,
        judged_model=usage["model"],
    )
    try:
        log_verdicts([{
            "ts": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
            "epoch": int(judged_at), "date": today, "ticker": sym,
            "stance": v["stance"], "conviction": v["conviction"],
            "price": (prices.get(sym) or {}).get("last", ""),
            "briefing": int(bool(briefing)), "model": usage["model"],
        }])
    except OSError as e:
        log(f"LEDGER_ERROR: {e}")
    # spend ledger (resets daily)
    sp = st.get("spend") or {}
    if sp.get("date") != today:
        sp = {"date": today, "usd": 0.0, "calls": 0}
    sp["usd"] = round(sp["usd"] + usage["usd"], 4)
    sp["calls"] += 1
    st["spend"] = sp
    st["last_error"] = None
    log(f"JUDGED {sym} via {usage['model']} "
        f"(${usage['usd']:.3f}, {usage['input_tokens']}in/{usage['output_tokens']}out)")


# ── scheduler (machine clock is PT, like every other SwingPro task) ─────────

def market_phase(dt: datetime) -> str:
    if dt.weekday() >= 5:
        return "weekend"
    mins = dt.hour * 60 + dt.minute
    if mins < 5 * 60 + 30:
        return "overnight"
    if mins < 6 * 60 + 30:
        return "premarket"
    if mins < 13 * 60:
        return "open"
    return "closed"


def scheduler_loop():
    # cold start: if the read is missing or very stale, populate it right away
    st = load_state()
    if time.time() - st.get("last_scan", 0) > 24 * 3600:
        scan(briefing=(market_phase(datetime.now()) == "premarket"))
    maybe_scorecard()
    while True:
        try:
            if _scan_request.is_set():
                _scan_request.clear()
                scan(force_judge=False)
                continue
            now = datetime.now()
            phase = market_phase(now)
            st = load_state()
            today = f"{now:%Y-%m-%d}"
            if phase in ("premarket", "open") and st.get("briefing_date") != today \
                    and now.hour * 60 + now.minute >= 5 * 60 + 35:
                scan(briefing=True)
                maybe_scorecard(force=True)   # daily re-score off fresh closes
            elif phase == "open":
                interval = load_settings()["interval_min"] * 60
                if time.time() - st.get("last_scan", 0) >= interval:
                    scan()
        except Exception as e:
            log(f"SCHEDULER_ERROR: {e}")
        _scan_request.wait(timeout=30)


def next_scan_info() -> dict:
    """For the UI countdown."""
    now = datetime.now()
    phase = market_phase(now)
    st = load_state()
    interval = load_settings()["interval_min"] * 60
    if _scanning:
        return {"phase": phase, "label": "scanning now…", "seconds": 0}
    if phase == "open":
        nxt = max(0, int(st.get("last_scan", 0) + interval - time.time()))
        return {"phase": phase, "label": "next auto-scan", "seconds": nxt}
    if phase in ("overnight", "premarket"):
        target = now.replace(hour=5, minute=35, second=0)
        if now >= target:
            return {"phase": phase, "label": "briefing due", "seconds": 0}
        return {"phase": phase, "label": "pre-market briefing",
                "seconds": int((target - now).total_seconds())}
    # closed / weekend → next weekday 05:35
    d = (now + timedelta(days=1)).replace(hour=5, minute=35, second=0, microsecond=0)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return {"phase": phase, "label": "next briefing",
            "seconds": int((d - now).total_seconds())}


# ── web server ───────────────────────────────────────────────────────────────

def api_state() -> dict:
    settings = load_settings()
    st = load_state()
    sym = settings["focus_ticker"]
    return {
        "updated": st.get("updated"),
        "briefing_date": st.get("briefing_date"),
        "briefing_at": st.get("briefing_at"),
        "ticker": sym,
        "verdict": (st.get("verdicts") or {}).get(sym),
        "spend": st.get("spend"),
        "last_error": st.get("last_error"),
        "scanner_state": st.get("scanner_state", "running"),  # explicit: "running", "key_dead", "network_error", "scanner_down"
        "judge_fail_streak": int(st.get("judge_fail_streak") or 0),
        "judge_fail_since": st.get("judge_fail_since"),
        "degraded": int(st.get("judge_fail_streak") or 0) >= DEGRADED_AFTER,
        "scanning": _scanning,
        "next": next_scan_info(),
        "settings": settings,
        "key_present": bool(_env("ANTHROPIC_API_KEY")),
        "model": MODEL,
        "system": _system_block(),
        "scorecard": _scorecard_block(),
    }


def _system_block() -> dict:
    """Everything the page shows about the iAPE trading system: engine signals,
    holdings/queue, and the live book + per-position budget (so the page can say
    whether the focused stock even fits a position)."""
    hold, queued = _read_forward_state()
    try:
        import botconfig
        bc = botconfig.load()
    except Exception:
        bc = {}
    broker = (_env("SWINGPRO_BROKER") or "alpaca").lower()
    if broker == "webull":
        book, venue = float(bc.get("webull_sizing_equity") or 2000.0), "Webull paper"
    else:
        book = float(bc.get("alpaca_sizing_equity") or 0) or 100000.0
        venue = "Alpaca paper"
    sizing = float(bc.get("sizing_pct") or 10.0)
    return {"signals": system_signals(allow_compute=False),
            "src": _sys["src"], "as_of": _sys["t"],
            "holdings": hold, "queued": queued,
            "book": book, "venue": venue, "sizing_pct": sizing,
            "per_trade": round(book * sizing / 100.0)}


def _scorecard_block():
    if SCORECARD_F.exists():
        try:
            return json.loads(SCORECARD_F.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                     # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/state":
            self._send(200, api_state())
        else:
            self._send(200, PAGE.encode("utf-8"), "text/html")

    def do_POST(self):
        if self.path != "/api/action":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "bad json"})
        act = req.get("action")
        if act == "scan":
            _scan_request.set()
            return self._send(200, {"ok": True})
        if act == "focus":
            t = str(req.get("ticker") or "").strip().upper()
            if not TICKER_RE.match(t):
                return self._send(400, {"error": "that doesn't look like a ticker"})
            cfg = save_settings({"focus_ticker": t})
            _scan_request.set()
            return self._send(200, {"ok": True, "settings": cfg})
        if act == "settings":
            cfg = save_settings(req.get("settings") or {})
            return self._send(200, {"ok": True, "settings": cfg})
        return self._send(400, {"error": f"unknown action {act!r}"})


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>iAPE — News Scanner</title>
<style>
:root{--bg:#0b0e14;--card:#141926;--card2:#1a2133;--txt:#dbe2f0;--dim:#7d8aa5;
--green:#2ecc8f;--red:#ff5d73;--gray:#8b97ad;--accent:#5b8cff;--amber:#ffb454}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:14px/1.5 'Segoe UI',system-ui,sans-serif;
padding:18px;max-width:860px;margin:0 auto}
h1{font-size:19px;font-weight:600;letter-spacing:.4px}
.topbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-bottom:14px}
.pill{padding:3px 11px;border-radius:20px;font-size:12px;font-weight:600;background:var(--card2)}
.pill.live{color:var(--green)} .pill.idle{color:var(--dim)}
.btn{background:var(--accent);border:none;color:#fff;font-weight:600;font-size:13px;
padding:7px 16px;border-radius:8px;cursor:pointer}
.btn:disabled{opacity:.45;cursor:default}
.btn.ghost{background:var(--card2);color:var(--txt)}
.focusbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:var(--card);
border-radius:12px;padding:12px 16px;margin-bottom:14px}
.focusbar input{background:var(--card2);border:1px solid #2a3550;color:var(--txt);
border-radius:8px;padding:8px 12px;font-size:16px;font-weight:700;width:130px;
text-transform:uppercase;letter-spacing:1px}
.banner{border-radius:10px;padding:10px 14px;font-size:12.5px;margin-bottom:14px;
background:#20180c;border:1px solid #4d3a12;color:var(--amber)}
.setup{background:#101a2e;border:1px solid #24406e;color:#9fc0ff}
.err{background:#2a1118;border:1px solid #6e2438;color:#ff9fb0}
.focuscard{background:var(--card);border-radius:14px;padding:18px 20px;margin-bottom:16px}
.fhead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.ftick{font-size:26px;font-weight:800}
.fco{color:var(--dim);font-size:14px;flex:1}
.px{font-size:13px;color:var(--dim)} .px b{color:var(--txt);font-size:15px}
.verdict{border-radius:12px;padding:14px 16px;margin-bottom:14px;font-size:18px;
font-weight:700;background:var(--card2);border-left:5px solid var(--gray);color:var(--gray)}
.verdict.bullish{border-left-color:var(--green);color:var(--green)}
.verdict.bearish{border-left-color:var(--red);color:var(--red)}
.confline{display:block;font-size:12.5px;font-weight:500;color:var(--dim);margin-top:5px}
.convbar{height:6px;border-radius:3px;background:#0b0e14;margin-top:8px;overflow:hidden}
.convbar i{display:block;height:100%;border-radius:3px}
.bl{font-size:16px;font-weight:600;margin-bottom:8px}
.why{font-size:14px;margin-bottom:14px;color:var(--txt)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
@media(max-width:560px){.cols{grid-template-columns:1fr}}
.cols h3{font-size:12px;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px}
.good h3{color:var(--green)} .bad h3{color:var(--amber)}
.cols li{list-style:none;font-size:13px;margin:4px 0;padding-left:14px;position:relative}
.cols li:before{content:'•';position:absolute;left:2px;color:var(--dim)}
.watch{font-size:13px;color:var(--dim);margin-bottom:10px}.watch b{color:var(--amber);font-weight:600}
.sysline{font-size:12px;color:var(--dim);margin-bottom:10px}
.swingnote{font-size:12.5px;color:#a8b6d4;background:var(--card2);border-radius:8px;
padding:8px 12px;margin-bottom:12px}
.news{border-top:1px solid #222b40;padding-top:9px;margin-top:4px}
.news h3{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:5px}
.news a{color:#9db8e8;text-decoration:none;font-size:12.5px}
.news a:hover{text-decoration:underline}
.news li{list-style:none;margin:4px 0;font-size:12.5px;color:var(--dim)}
.meta{font-size:11px;color:#5a6680}
.judged{font-size:10.5px;color:#56628a;margin-top:10px}
.foot{margin-top:18px;background:var(--card);border-radius:12px;padding:14px 16px}
.foot h2{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
.frow{display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:13px}
input[type=number],select{background:var(--card2);border:1px solid #2a3550;
color:var(--txt);border-radius:7px;padding:5px 9px;font-size:13px}
input[type=number]{width:64px}
label{color:var(--dim)}
.small{font-size:11.5px;color:var(--dim);margin-top:10px}
.scrollx{overflow-x:auto}
.trtable{border-collapse:collapse;font-size:12.5px;min-width:560px}
.trtable th,.trtable td{padding:5px 12px 5px 0;text-align:left;border-bottom:1px solid #222b40}
.trtable th{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.8px}
.statuscard{background:var(--card);border-radius:12px;padding:12px 16px;margin-bottom:14px}
#statusline{font-size:14.5px}
#botglance{font-size:12.5px;color:var(--dim);margin-top:6px}
.chiprow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:-4px 0 14px}
.chipbtn{display:inline-flex;align-items:center;gap:6px;background:var(--card2);
border:1px solid #2a3550;color:var(--txt);font-size:12px;font-weight:600;
padding:4px 10px;border-radius:14px;cursor:pointer}
.chipbtn:hover{border-color:var(--accent)}
.chipbtn.on{border-color:var(--accent);background:#1b2742}
.chipbtn i{width:7px;height:7px;border-radius:50%;display:inline-block}
.fitline{font-size:12.5px;border-radius:8px;padding:7px 12px;margin-bottom:10px}
.fitline.ok{background:#0f2018;color:#7fdcb2}
.fitline.no{background:#20180c;color:var(--amber)}
.help li{list-style:none;font-size:13px;margin:8px 0;color:var(--txt)}
.help b{color:#9db8e8}
details.foot summary{cursor:pointer;font-weight:600;font-size:13.5px}
</style></head><body>
<div class="topbar">
  <h1>📰 iAPE News Scanner <span style="color:var(--dim);font-weight:400;font-size:13px">— one stock, one clear read</span></h1>
  <div style="display:flex;gap:8px;align-items:center">
    <span id="phase" class="pill idle">—</span>
    <span id="countdown" class="pill idle">—</span>
    <button id="scanbtn" class="btn ghost" onclick="scanNow()">Scan again</button>
  </div>
</div>
<div class="focusbar">
  <span style="font-weight:600">Which stock?</span>
  <input id="tick" maxlength="8" placeholder="AAPL" onkeydown="if(event.key==='Enter')setTicker()">
  <button class="btn" onclick="setTicker()">Get the read</button>
  <span class="meta">any ticker works — AAPL, NVDA, DIS, AMD…</span>
</div>
<div class="chiprow" id="botchips" style="display:none"></div>
<div class="statuscard"><div id="statusline">Loading…</div><div id="botglance"></div></div>
<div class="banner">⚠️ This is an AI's read of recent headlines — informational research only, <b>not</b> a validated signal, not financial advice, and not connected to the trading bot's orders.</div>
<div id="setup" class="banner setup" style="display:none"></div>
<div id="error" class="banner err" style="display:none"></div>
<div id="notfound" class="banner err" style="display:none"></div>
<div id="holdwarn" class="banner err" style="display:none"></div>
<div id="main"></div>
<div class="foot" id="record" style="display:none"></div>
<div class="foot">
  <h2>Settings</h2>
  <div class="frow">
    <label>Re-read every <input id="s_interval" type="number" min="5" max="60"> min (market hours)</label>
    <label>Headlines per read <input id="s_heads" type="number" min="3" max="12"></label>
    <label>AI effort <select id="s_effort"><option>low</option><option>medium</option><option>high</option></select></label>
    <button class="btn ghost" onclick="saveSettings()">Save</button>
  </div>
  <div class="small" id="spend"></div>
  <div class="small" id="stamp"></div>
</div>
<details class="foot">
  <summary>❓ How to read this page</summary>
  <ul class="help">
    <li><b>The big verdict</b> — the AI reads the last two days of headlines about your stock and makes one honest call: does the news push it up, down, or nowhere over the next few days? Most days "nowhere" is the honest answer.</li>
    <li><b>Confidence (0–100)</b> — how sure the AI is of that call. 70+ means a genuinely big catalyst (earnings shock, a buyout, a major upgrade). 40–70 is "leaning". Below 40 is a shrug.</li>
    <li><b>👍 / ⚠️ lists</b> — the strongest things pulling the stock up and the things to be careful about, in plain words.</li>
    <li><b>Your trading bot's own signal</b> — completely separate from the news. This is what your iAPE bot (the validated strategy) says about the same stock: 🎯 <b>TRIGGERED</b> = it wants to buy at the next market open, 👀 <b>forming</b> = getting close, 💤 <b>none</b> = no setup. The bot only trades its own signals — never the AI's news read.</li>
    <li><b>The budget line</b> — your bot puts a fixed slice of its practice money into each trade. This line says whether one share of this stock even fits that slice.</li>
    <li><b>📊 Track record</b> — every morning call the AI makes gets graded later against what the stock actually did. Until there are ~30 graded calls per row, treat it as "still collecting evidence".</li>
    <li><b>The golden rule</b> — the AI read is information, the bot's validated signals make the (paper) trades, and nothing ever touches real money without passing the ≥30-trade audition.</li>
  </ul>
</details>
<script>
let S=null, dirty=false, cds=0;
['s_interval','s_heads','s_effort'].forEach(id=>{
  document.getElementById(id).addEventListener('input',()=>dirty=true);});
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function age(m){return m==null?'':(m<120?m+'m':Math.round(m/60)+'h')}
function sigOf(t){const s=S&&S.system&&S.system.signals&&S.system.signals[t];return s||null}
function heldOf(t){return (S&&S.system&&S.system.holdings&&S.system.holdings[t])||null}
function queuedOf(t){return (S&&S.system&&S.system.queued&&S.system.queued[t])||null}
function confPhrase(c){return c>=70?'very confident':c>=40?'fairly confident':'not very confident'}
const BIG={bullish:['📈','The news looks GOOD for this stock'],
           bearish:['📉','The news looks BAD for this stock'],
           neutral:['😐','The news doesn’t point clearly either way']};
function sysline(t){
  const sys=sigOf(t), hp=heldOf(t), qd=queuedOf(t);
  let s;
  if(sys&&sys.signal){
    const M={triggered:['🎯','var(--green)','has a LIVE BUY setup on this stock right now'],
             forming:['👀','var(--amber)','is watching this one — a setup is forming'],
             none:['💤','var(--dim)','sees no setup on this stock right now']};
    const m=M[sys.signal]||M.none;
    s=`${m[0]} Your trading bot <b style="color:${m[1]}">${m[2]}</b>`
      +(sys.above_trend!=null?` · price is ${sys.above_trend?'above':'below'} its long-term trend`:'')
      +(sys.mkt_ok!=null?` · the overall market ${sys.mkt_ok?'looks OK to it':'has its caution filter on'}`:'');
  }else{
    s=`💤 Your trading bot doesn’t trade this stock <span class="meta">(not on its watchlist)</span>`;
  }
  if(hp) s+=` · <b style="color:var(--accent)">the bot OWNS this one${hp.qty?' ('+hp.qty+' shares)':''}</b>`;
  if(qd) s+=` · <b style="color:var(--amber)">queued to buy at the next open${qd&&qd!=='?'?' ('+esc(qd)+')':''}</b>`;
  return `<div class="sysline">${s}</div>`+fitline(t);}
function fitline(t){
  const v=S.verdict, sys=S.system||{};
  if(!v||v.ticker!==t||!v.price||!sys.per_trade) return '';
  const px=v.price.last, sh=Math.floor(sys.per_trade/px);
  if(sh>=1) return `<div class="fitline ok">✓ Fits the bot’s budget — its ~$${sys.per_trade} per-position slice buys ${sh} share${sh>1?'s':''} at $${px}</div>`;
  return `<div class="fitline no">✕ Too pricey for the bot — one share ($${px}) costs more than its ~$${sys.per_trade} per-position slice, so it would skip this even on a signal</div>`;}
function botGlance(){
  const sys=S.system||{}; if(!sys.book) return '';
  const sigs=sys.signals||{}, hold=Object.keys(sys.holdings||{}), q=Object.keys(sys.queued||{});
  const trig=Object.keys(sigs).filter(k=>sigs[k].signal==='triggered');
  const form=Object.keys(sigs).filter(k=>sigs[k].signal==='forming');
  const bits=[hold.length?`holding ${hold.join(', ')}`:'no positions right now'];
  if(q.length) bits.push(`queued to buy ${q.join(', ')}`);
  bits.push(trig.length?`🎯 live setup on ${trig.join(', ')}`:
            form.length?`watching ${form.join(', ')} (setups forming)`:
            Object.keys(sigs).length?'no setups on its watchlist today (quiet is normal — it trades ~once every 2-3 weeks)':'');
  return `🤖 Your iAPE bot: ${bits.filter(Boolean).join(' · ')} · practice book $${Math.round(sys.book).toLocaleString()} on ${sys.venue}, ~$${sys.per_trade} per trade`;}
function chips(){
  const el=document.getElementById('botchips');
  const sys=S.system||{}; const sigs=sys.signals||{};
  const names=[...new Set([...Object.keys(sys.holdings||{}),...Object.keys(sys.queued||{}),...Object.keys(sigs)])];
  if(!names.length){el.style.display='none';return;}
  el.innerHTML='<span class="meta">Your bot’s stocks (tap for a read):</span>'+names.map(t=>{
    const sg=sigs[t]&&sigs[t].signal;
    const dot=sg==='triggered'?'var(--green)':sg==='forming'?'var(--amber)':'#3a4560';
    const mark=(sys.holdings&&sys.holdings[t])?' 📦':((sys.queued&&sys.queued[t])?' 🕐':'');
    return `<button class="chipbtn${t===S.ticker?' on':''}" onclick="focusTo('${t}')"><i style="background:${dot}"></i>${t}${mark}</button>`;
  }).join('');
  el.style.display='flex';}
function focusTo(t){document.getElementById('tick').value=t;setTicker();}
function fmtCd(x){const m=Math.floor(x/60),s=x%60,h=Math.floor(m/60);
  return h>0?h+'h '+(m%60)+'m':m+'m '+String(s).padStart(2,'0')+'s'}
function todayLocal(){const d=new Date();
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function statusSentence(){
  const ph=S.next.phase, cd=fmtCd(cds);
  if(S.scanning) return '⏳ Reading the news right now — one moment…';
  if(ph==='open') return `The market is open. I re-check ${S.ticker}’s news every ${S.settings.interval_min} minutes — next look in ${cd}.`;
  if(ph==='premarket') return S.briefing_date===todayLocal()
    ? `☀️ Your morning read is in (done at ${S.briefing_at||'~5:35'}). The market opens at 6:30.`
    : `The market opens at 6:30 AM. Your morning read on ${S.ticker} lands in ${cd}.`;
  if(ph==='overnight') return `The market is closed for the night. Your morning read on ${S.ticker} lands in ${cd} (~5:35 AM).`;
  if(ph==='weekend') return `It’s the weekend — the market is closed. Your next morning read is in ${cd}.`;
  return `The market closed at 1:00 PM. Tomorrow’s morning read on ${S.ticker} lands in ${cd}.`;}
function updateStatus(){if(!S)return;const el=document.getElementById('statusline');if(el)el.textContent=statusSentence();}
function focusCard(){
  const v=S.verdict;
  if(!v) return `<div class="focuscard" style="color:var(--dim)">No read yet for <b>${esc(S.ticker)}</b> — hit “Get the read”.</div>`;
  const p=v.price?`<span class="px"><b>$${v.price.last}</b> · ${v.price.chg5d>=0?'up':'down'} ${Math.abs(v.price.chg5d)}% over the past 5 days</span>`:'';
  const col=v.stance==='bullish'?'var(--green)':v.stance==='bearish'?'var(--red)':'var(--gray)';
  let body='';
  if(v.judged_epoch){
    const big=BIG[v.stance]||BIG.neutral;
    body+=`<div class="verdict ${v.stance}">${big[0]} ${big[1]}
      <span class="confline">The AI is ${confPhrase(v.conviction)} in this read (${v.conviction}/100)</span>
      <div class="convbar"><i style="width:${v.conviction||0}%;background:${col}"></i></div></div>`;
    const bl=v.bottom_line||v.rationale;
    if(bl) body+=`<div class="bl">“${esc(bl)}”</div>`;
    if(v.explanation) body+=`<div class="why">${esc(v.explanation)}</div>`;
    const good=v.good_signs&&v.good_signs.length?v.good_signs:(v.catalysts||[]);
    const bad=v.bad_signs||[];
    if(good.length||bad.length){
      body+=`<div class="cols">
        <div class="good"><h3>👍 Good signs</h3><ul>${good.map(x=>`<li>${esc(x)}</li>`).join('')||'<li class="meta">nothing notable</li>'}</ul></div>
        <div class="bad"><h3>⚠️ Warning signs</h3><ul>${bad.map(x=>`<li>${esc(x)}</li>`).join('')||'<li class="meta">nothing notable</li>'}</ul></div>
      </div>`;}
    const wo=v.watch_out||v.risk;
    if(wo) body+=`<div class="watch"><b>What could change this:</b> ${esc(wo)}</div>`;
    if(v.swing_note) body+=`<div class="swingnote">🤖 ${esc(v.swing_note)}</div>`;
  }else{
    body+=`<div class="verdict">⏳ Headlines fetched — the AI read is on its way…</div>`;
  }
  body+=sysline(v.ticker);
  const news=(v.headlines||[]).map(h=>`<li>· <a href="${esc(h.link)}" target="_blank" rel="noopener">${esc(h.title)}</a> <span class="meta">${esc(h.source)}${h.age_min!=null?' · '+age(h.age_min)+' ago':''}</span></li>`).join('');
  if(news) body+=`<div class="news"><h3>What the AI read</h3><ul>${news}</ul></div>`;
  body+=v.judged_epoch?`<div class="judged">judged ${new Date(v.judged_epoch*1000).toLocaleString([],{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})} · ${esc((v.judged_model||'').replace('claude-',''))}</div>`:'<div class="judged">not yet judged</div>';
  return `<div class="focuscard">
    <div class="fhead"><span class="ftick">${esc(v.ticker)}</span><span class="fco">${esc(v.company||'')}</span>${p}</div>
    ${body}</div>`;}
function pct(x){return x==null?'—':((x*100>=0?'+':'')+(x*100).toFixed(1)+'%')}
function renderRecord(){
  const el=document.getElementById('record');
  if(!S.scorecard||!S.scorecard.buckets){el.style.display='none';return;}
  const names={bullish_hi:'Said “good news” — very confident',bullish_lo:'Said “good news”',
               neutral:'Said “no clear direction”',bearish:'Said “bad news”'};
  let rows='', anyScored=false;
  for(const k of ['bullish_hi','bullish_lo','neutral','bearish']){
    const b=S.scorecard.buckets[k]; if(!b) continue;
    rows+=`<tr><td>${names[k]}</td><td>${b.n}</td>`+[1,3,5].map(n=>{
      const x=b['h'+n]||{};
      if(!x.n) return '<td class="meta">not graded yet</td>';
      anyScored=true;
      let cell=`stock ${pct(x.avg)} avg`;
      if(x.hit!=null) cell+=` · right ${Math.round(x.hit*100)}% of the time`;
      cell+=` <span class="meta">market ${pct(x.spy)} · ${x.n} graded</span>`;
      return `<td>${cell}</td>`;
    }).join('')+'</tr>';
  }
  el.innerHTML=`<h2>📊 Has the AI been right? — its track record</h2>
    <div class="scrollx"><table class="trtable"><tr><th>When the AI…</th><th>calls</th><th>next day</th><th>3 days later</th><th>5 days later</th></tr>${rows}</table></div>
    <div class="small">${anyScored?'':'⏳ Still collecting evidence — calls get graded once the market has had time to answer. '}Every morning call is logged and graded later against what the stock actually did (the market’s own move shown for comparison). Below ~30 graded calls per row, treat this as a work in progress — same rule as everything else in iAPE: no trust without evidence. Updated ${esc(S.scorecard.computed||'')}.</div>`;
  el.style.display='block';}
function render(){
  if(!S)return;
  const ti=document.getElementById('tick');
  if(document.activeElement!==ti) ti.value=S.ticker;
  document.getElementById('main').innerHTML=focusCard();
  const v=S.verdict;
  const nf=document.getElementById('notfound');
  if(v&&!v.price&&(!v.headlines||!v.headlines.length)&&v.headlines!==undefined){
    nf.style.display='block';
    nf.textContent='🔍 Couldn’t find price data or headlines for '+S.ticker+' — double-check the ticker symbol.';
  }else nf.style.display='none';
  const hw=document.getElementById('holdwarn');
  if(v&&v.judged_epoch&&v.stance==='bearish'&&heldOf(v.ticker)){
    hw.style.display='block';
    hw.textContent='⚠ Heads up: the news read is BEARISH on '+v.ticker+' and the trading bot currently holds it — worth a look.';
  }else hw.style.display='none';
  renderRecord();
  const setup=document.getElementById('setup');
  if(!S.key_present){setup.style.display='block';
    setup.innerHTML='🔑 <b>Headlines-only mode.</b> To turn on Fable 5 judgments: create an API key at <b>console.anthropic.com</b> → run in PowerShell: <code>[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY","sk-ant-…","User")</code> → next scan will judge automatically.';}
  else setup.style.display='none';
  const err=document.getElementById('error');
  if(S.scanner_state && S.scanner_state !== 'running'){
    err.style.display='block';
    let msg = S.last_error || 'Unknown error';
    if(S.scanner_state === 'key_dead') {
      msg = '🔑 API key rejected (revoked or expired). ' + msg;
    } else if(S.scanner_state === 'network_error') {
      msg = '🌐 Network error. ' + msg;
    } else if(S.scanner_state === 'scanner_down') {
      msg = '⚠️ Scanner error. ' + msg;
    }
    err.textContent = msg;
  } else err.style.display='none';
  const ph=document.getElementById('phase');
  ph.textContent=({open:'MARKET OPEN',premarket:'PRE-MARKET',closed:'AFTER CLOSE',overnight:'OVERNIGHT',weekend:'WEEKEND'})[S.next.phase]||S.next.phase;
  ph.className='pill '+(S.next.phase==='open'?'live':'idle');
  cds=S.next.seconds; window._cdlabel=S.next.label;
  document.getElementById('scanbtn').disabled=S.scanning;
  if(!dirty){
    document.getElementById('s_interval').value=S.settings.interval_min;
    document.getElementById('s_heads').value=S.settings.max_headlines;
    document.getElementById('s_effort').value=S.settings.effort;
  }
  const sp=S.spend&&S.spend.date?`AI spend today (${S.spend.date}): ~$${S.spend.usd.toFixed(2)} across ${S.spend.calls} call${S.spend.calls===1?'':'s'} · model ${S.model}`:`No AI calls yet today · model ${S.model}`;
  document.getElementById('spend').textContent=sp;
  document.getElementById('stamp').textContent=`Focused on ${S.ticker} · last scan ${S.updated||'never'}`;
  chips();
  document.getElementById('botglance').textContent=botGlance();
  updateStatus();
}
function tickCd(){
  const el=document.getElementById('countdown');
  if(S&&S.scanning){el.textContent='⏳ scanning…';el.className='pill live';updateStatus();return;}
  if(cds>0){cds--;}
  el.textContent=(window._cdlabel||'next scan')+' in '+fmtCd(cds);
  el.className='pill idle';
  updateStatus();}
async function poll(){try{const r=await fetch('/api/state');S=await r.json();render();}catch(e){}}
async function scanNow(){document.getElementById('scanbtn').disabled=true;
  await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'scan'})});
  setTimeout(poll,1500);}
async function setTicker(){
  const t=document.getElementById('tick').value.trim().toUpperCase();
  if(!/^[A-Z0-9.\-]{1,8}$/.test(t)){alert('That doesn’t look like a ticker symbol.');return;}
  const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'focus',ticker:t})});
  if(!r.ok){alert('That doesn’t look like a ticker symbol.');return;}
  document.getElementById('tick').blur();
  setTimeout(poll,1200); setTimeout(poll,4000); setTimeout(poll,9000);}
async function saveSettings(){
  const s={interval_min:+document.getElementById('s_interval').value,
    max_headlines:+document.getElementById('s_heads').value,
    effort:document.getElementById('s_effort').value};
  await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'settings',settings:s})});
  dirty=false; poll();}
poll(); setInterval(poll,15000); setInterval(tickCd,1000);
</script></body></html>"""


# ── entrypoint ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT_DEFAULT)
    ap.add_argument("--headless", action="store_true",
                    help="don't open a browser (scheduled-task mode)")
    ap.add_argument("--once", action="store_true",
                    help="single scan, write state, exit (no server)")
    ap.add_argument("--force", action="store_true",
                    help="with --once: re-judge even if headlines are unchanged")
    ap.add_argument("--ticker", type=str, default=None,
                    help="with --once: set the focus ticker first")
    a = ap.parse_args()

    if a.once:
        if a.ticker and TICKER_RE.match(a.ticker.strip().upper()):
            save_settings({"focus_ticker": a.ticker.strip().upper()})
        scan(force_judge=a.force,
             briefing=(market_phase(datetime.now()) == "premarket"))
        maybe_scorecard(force=True)
        st = load_state()
        sym = load_settings()["focus_ticker"]
        v = (st.get("verdicts") or {}).get(sym) or {}
        print(json.dumps({"ticker": sym, "updated": st.get("updated"),
                          "stance": v.get("stance"),
                          "conviction": v.get("conviction"),
                          "bottom_line": v.get("bottom_line")}, indent=1))
        return

    # single-instance guard: if the port is taken the scanner is already up
    # (the 05:25 scheduled task relies on this being a silent no-op)
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", a.port))
        probe.close()
    except OSError:
        log(f"port {a.port} busy — scanner already running, exiting")
        return

    threading.Thread(target=scheduler_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}"
    log(f"news scanner serving on {url}")
    if not a.headless:
        threading.Thread(target=lambda: (time.sleep(0.8), webbrowser.open(url)),
                         daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
