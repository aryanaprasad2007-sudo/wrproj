"""
control.py — runtime control flags shared by the bot (forward_trader, a fresh
process each minute) and the human (dashboard.py, long-lived). State is tiny
flag files in cache/ so the two always agree without a database.

Three controls, all fail-safe (a missing/unreadable flag = the SAFE state):

  HALT (kill switch)   cache/HALT present  -> bot opens NO new positions.
                       Exits still run (a halt must never strand a position).
  OBSERVER (dead-man)  cache/OBSERVER present -> new entries require a FRESH
                       dashboard heartbeat; if the dashboard has been closed/idle
                       longer than HEARTBEAT_MAX_MIN, the bot manages exits only.
                       This is the "someone must be watching" rule, in code.
  HEARTBEAT            cache/dashboard_heartbeat mtime = last time a human's
                       dashboard polled /api/state (every ~30s while open).

`entries_allowed()` is the single gate the bot calls before any NEW buy.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "cache"
HALT_FLAG = CACHE / "HALT"
OBSERVER_FLAG = CACHE / "OBSERVER"
HEARTBEAT = CACHE / "dashboard_heartbeat"
HEARTBEAT_MAX_MIN = 10.0            # observer dead-man window (minutes)


def _touch(p: Path, on: bool):
    CACHE.mkdir(exist_ok=True)
    if on:
        p.write_text(str(time.time()))
    elif p.exists():
        p.unlink()


def is_halted() -> bool:
    return HALT_FLAG.exists()


def set_halt(on: bool):
    _touch(HALT_FLAG, on)


def observer_mode() -> bool:
    return OBSERVER_FLAG.exists() or (os.environ.get("SWINGPRO_OBSERVER") == "1")


def set_observer(on: bool):
    _touch(OBSERVER_FLAG, on)


def touch_heartbeat():
    """Called by the dashboard on every state poll = 'a human is watching'."""
    CACHE.mkdir(exist_ok=True)
    HEARTBEAT.write_text(str(time.time()))


def heartbeat_age_min() -> float | None:
    """Minutes since the dashboard last polled, or None if never."""
    if not HEARTBEAT.exists():
        return None
    return (time.time() - HEARTBEAT.stat().st_mtime) / 60.0


def entries_allowed() -> tuple[bool, str]:
    """The gate the bot checks before opening any NEW position.
    Exits are NEVER gated — call this only for entries."""
    if is_halted():
        return False, "HALTED (kill switch active)"
    if observer_mode():
        age = heartbeat_age_min()
        if age is None:
            return False, "observer mode: dashboard never opened this session"
        if age > HEARTBEAT_MAX_MIN:
            return False, f"observer dead-man: dashboard idle {age:.0f}m " \
                          f"(> {HEARTBEAT_MAX_MIN:.0f}m) — exits only"
    return True, "ok"


def status() -> dict:
    ok, reason = entries_allowed()
    return {"halted": is_halted(), "observer": observer_mode(),
            "heartbeat_age_min": heartbeat_age_min(),
            "entries_allowed": ok, "reason": reason}
