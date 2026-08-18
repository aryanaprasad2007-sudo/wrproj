"""
botconfig.py — the operator's live control panel for the bot, persisted to
cache/bot_settings.json. The dashboard writes it; every forward_trader tick
reads it fresh, so changes take effect on the next minute with no restart.

WHAT LIVES HERE vs WHAT DOESN'T — the line matters:
  * HERE (yours to set): capital sizing, exposure caps, per-order notional cap,
    a daily loss limit that auto-pauses entries, and which tracks run. These are
    *operational* — changing them does NOT change the edge being measured.
  * NOT here (locked): the validated strategy internals — the entry gates,
    RSI/ADX thresholds, exit logic (pure stop + 3R), baskets. Those are
    pre-registered; live-editing them would silently invalidate the audition
    (house rule #2). The dashboard shows them read-only so you can SEE them
    without corrupting the experiment.

All values are clamped on load, so a bad hand-edit can't feed the bot a
dangerous number.
"""
from __future__ import annotations

import json
from pathlib import Path

_FILE = Path(__file__).resolve().parent / "cache" / "bot_settings.json"

DEFAULTS = {
    "sizing_pct": 10.0,            # % of equity per new position
    "max_positions": 10,          # cap on TOTAL concurrent positions (both books)
    "max_notional_usd": 0.0,      # 0 = off; else hard $ cap per order
    "daily_loss_limit_usd": 0.0,  # 0 = off; else pause NEW entries once the day
                                  #   is down this many $ (auto-resets next day)
    "tracks": {"intraday": True, "daily": True},
    "focus_symbols": [],          # [] = trade the full baskets; else the bot
                                  #   only opens NEW positions in these symbols
    "webull_sizing_equity": 10000.0,   # simulated sizing base in Webull mode
    "alpaca_sizing_equity": 0.0,  # 0 = size off the REAL Alpaca paper balance.
                                  #   Else trade a SMALL book (e.g. 2000) on the
                                  #   big paper account WITHOUT resetting it:
                                  #   sizing uses this number, real balance /
                                  #   buying power / forward-test history stay
                                  #   untouched. See sizing_equity().
}

_CLAMP = {
    "sizing_pct": (0.1, 100.0),
    "max_positions": (1, 50),
    "max_notional_usd": (0.0, 1_000_000.0),
    "daily_loss_limit_usd": (0.0, 1_000_000.0),
    "webull_sizing_equity": (100.0, 100_000_000.0),
    "alpaca_sizing_equity": (0.0, 100_000_000.0),   # 0 = off (use real equity)
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))          # deep copy
    if _FILE.exists():
        try:
            saved = json.loads(_FILE.read_text())
            for k, v in saved.items():
                if k == "tracks" and isinstance(v, dict):
                    cfg["tracks"].update({t: bool(v.get(t, cfg["tracks"][t]))
                                          for t in cfg["tracks"]})
                elif k == "focus_symbols":
                    cfg["focus_symbols"] = _clean_symbols(v)
                elif k in cfg:
                    cfg[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    return _validate(cfg)


def _clean_symbols(v) -> list:
    """Accept a list or a comma/space string; normalize to unique upper tickers."""
    if isinstance(v, str):
        v = v.replace(",", " ").split()
    if not isinstance(v, (list, tuple)):
        return []
    out = []
    for s in v:
        t = str(s).strip().upper()
        if t and t.isalnum() and t not in out:
            out.append(t)
    return out


def save(patch: dict) -> dict:
    """Merge a partial update from the dashboard, clamp, persist, return it."""
    cfg = load()
    for k, v in patch.items():
        if k == "tracks" and isinstance(v, dict):
            cfg["tracks"].update({t: bool(v[t]) for t in cfg["tracks"] if t in v})
        elif k == "focus_symbols":
            cfg["focus_symbols"] = _clean_symbols(v)
        elif k in DEFAULTS and k != "tracks":
            cfg[k] = v
    cfg = _validate(cfg)
    _FILE.parent.mkdir(exist_ok=True)
    _FILE.write_text(json.dumps(cfg, indent=1))
    return cfg


def _validate(cfg: dict) -> dict:
    for k, (lo, hi) in _CLAMP.items():
        try:
            cfg[k] = min(hi, max(lo, float(cfg[k])))
        except (TypeError, ValueError):
            cfg[k] = DEFAULTS[k]
    cfg["max_positions"] = int(cfg["max_positions"])
    if not isinstance(cfg.get("tracks"), dict):
        cfg["tracks"] = dict(DEFAULTS["tracks"])
    cfg["focus_symbols"] = _clean_symbols(cfg.get("focus_symbols", []))
    return cfg


def in_focus(symbol: str, cfg: dict) -> bool:
    """True if the bot may open a NEW position in this symbol. An empty focus
    list means 'no restriction' (trade the full baskets)."""
    foc = cfg.get("focus_symbols") or []
    return (not foc) or (symbol.upper() in foc)


def sizing_equity(real_equity: float, broker_name: str, cfg: dict) -> float:
    """The capital base the strategies size positions against.

    In Alpaca mode this is the real paper equity UNLESS alpaca_sizing_equity is
    set (>0), in which case the bot trades that smaller book — e.g. 2000 makes
    10%-sizing land at ~$200/position — while the real account balance, buying
    power, and the forward-test equity history are left completely untouched.
    In Webull mode broker.account() already returns the simulated base, so this
    just passes it through."""
    if broker_name == "alpaca":
        ov = cfg.get("alpaca_sizing_equity", 0) or 0
        if ov > 0:
            return float(ov)
    return float(real_equity)


def cap_qty(qty: int, price: float, cfg: dict) -> int:
    """Apply the per-order notional cap. 0 = no cap."""
    cap = cfg.get("max_notional_usd", 0) or 0
    if cap > 0 and price > 0:
        qty = min(int(qty), int(cap // price))
    return max(0, int(qty))
