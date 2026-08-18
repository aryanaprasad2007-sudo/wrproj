"""
Psychowl's read layer: every sibling project, as facts from disk.

Psychowl is a federation, not a rewrite. Each project keeps working on its
own; this module is the one place that knows where everything lives, and it
only READS. The browser-side alternative was measured and ruled out in
DATA-CONTRACT.md -- localStorage is per-origin, so file:// pages, Grimoire's
localhost, and this server can never read each other in the browser. On disk,
in Python, none of those walls exist.

Every function returns plain JSON-safe data and swallows absence: a missing
file means that project has nothing to say today, never an error. The hub must
render with any subset of projects present.
"""
import json
import os
import re
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOCKET_DATA = os.path.join(ROOT, "Daily-Docket", "docket_data.json")
DOCKET_SLIPS = os.path.join(ROOT, "Daily-Docket", "slips.json")
BRIEF_DIR = os.path.join(ROOT, "Morning-Brief")
NIGHTOWL_CONFIG = os.path.join(ROOT, "nightowl", "config.json")
NIGHTOWL_STATE = os.path.join(ROOT, "nightowl", "data", "state.json")
FOCUS_SESSIONS = os.path.join(ROOT, "nightowl", "data", "focus_sessions.json")
GRIMOIRE_DIR = os.path.join(ROOT, "grimoire-calendar")
FOCUSFLOW_HTML = os.path.join(ROOT, "FocusFlow-and-Art", "focusflow.html")
LOGS_DIR = os.path.join(ROOT, "logs")


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def docket():
    """The Docket's own build output, trimmed to what a card can show."""
    d = _load(DOCKET_DATA, None)
    if not d:
        return None
    slips = _load(DOCKET_SLIPS, {}) or {}
    slipped = [v for v in slips.values()
               if v.get("count", 0) >= 2 and not v.get("cleared")]
    return {
        "date": d.get("date"),
        "statusLine": d.get("statusLine"),
        "nowTask": d.get("nowTask"),
        "topPriorities": (d.get("topPriorities") or [])[:5],
        "dueToday": (d.get("dueToday") or [])[:5],
        "slippedCount": len(slipped),
    }


def morning_brief():
    """Latest brief: date, title line, and the filename to fetch raw."""
    if not os.path.isdir(BRIEF_DIR):
        return None
    briefs = sorted(f for f in os.listdir(BRIEF_DIR)
                    if f.startswith("morning-brief-") and f.endswith(".md"))
    if not briefs:
        return None
    name = briefs[-1]
    title = None
    try:
        with open(os.path.join(BRIEF_DIR, name), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#"):
                    title = line.lstrip("# ").strip()
                    break
    except OSError:
        pass
    return {
        "file": name,
        "date": name[len("morning-brief-"):-len(".md")],
        "title": title,
        "isToday": name[len("morning-brief-"):-len(".md")]
                   == datetime.now().strftime("%Y-%m-%d"),
    }


def brief_path(name):
    """Resolve a brief filename safely, or None. No path components allowed."""
    if not re.fullmatch(r"morning-brief-\d{4}-\d{2}-\d{2}\.md", name or ""):
        return None
    full = os.path.join(BRIEF_DIR, name)
    return full if os.path.exists(full) else None


def nightowl():
    """NightOwl's rhythm (config) and current mode (state), straight off disk."""
    cfg = _load(NIGHTOWL_CONFIG, {})
    state = _load(NIGHTOWL_STATE, {})
    sessions = _load(FOCUS_SESSIONS, [])
    today = datetime.now().strftime("%Y-%m-%d")
    focus_today = 0
    for s in sessions if isinstance(sessions, list) else []:
        try:
            if str(s.get("at", s.get("date", "")))[:10] == today:
                focus_today += int(s.get("minutes", 0))
        except (TypeError, ValueError):
            continue
    #  nightRoutine is the six-step wind-down walkthrough in config.json. It
    #  used to render only on nightowl/hub/index.html, which stopped being
    #  opened by anything when `no hub` was repointed at psychowl -- so the
    #  gentlest content in the whole system was reaching him nowhere. Passed
    #  through here so the page he actually opens can show it.
    routine = cfg.get("nightRoutine") or {}
    return {
        "wake": cfg.get("wake", "07:30"),
        "bedtime": cfg.get("bedtime", "01:30"),
        "windDownMinutes": cfg.get("windDownMinutes", 60),
        "mode": state.get("mode"),
        "modeSince": state.get("modeSince"),
        "focusMinutesToday": focus_today,
        "routine": {
            "lightsOutTime": routine.get("lightsOutTime", ""),
            "stillAwake": routine.get("stillAwake", ""),
            "steps": routine.get("steps", []),
        },
    }


def _read_runs(day):
    """Every run logged on a given date (a date object or 'YYYY-MM-DD'), or
    [] if that day has no log yet. The one place that reads modes-*.jsonl, so
    week_bars/streak/mode_totals can't drift apart on how a bad line is
    handled."""
    day_str = day.isoformat() if hasattr(day, "isoformat") else day
    path = os.path.join(LOGS_DIR, f"modes-{day_str}.jsonl")
    runs = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    runs.append(json.loads(line))
                except ValueError:
                    continue          # a half-written final line is expected
    return runs


def mode_totals(day=None):
    """Today's tracker runs, totalled per mode. Same log mode_log.py writes."""
    day_str = day or datetime.now().strftime("%Y-%m-%d")
    runs = _read_runs(day_str)
    totals = {}
    for r in runs:
        totals[r["mode"]] = totals.get(r["mode"], 0) + r.get("minutes", 0)
    ranked = sorted(({"mode": m, "minutes": round(v, 1)}
                     for m, v in totals.items()), key=lambda t: -t["minutes"])
    return {"date": day_str, "runs": len(runs), "totals": ranked,
            "trackedMinutes": round(sum(totals.values()), 1),
            "last": runs[-1] if runs else None}


def week_bars(mode="deep_work", days=7):
    """
    Per-day minutes in `mode`, oldest to newest, the last `days` days
    including today.

    A day with no log file is a real zero, not "unknown" -- if the tracker
    wasn't running that day, no deep_work happened, and pretending otherwise
    would be inventing data the same way the project's Aria-facts rule
    forbids. The card renders zero-height bars for those days rather than
    hiding them, so a week with a gap actually looks like it has one.
    """
    today = datetime.now().date()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        total = sum(r.get("minutes", 0) for r in _read_runs(d)
                    if r.get("mode") == mode)
        out.append({"date": d.isoformat(), "label": d.strftime("%a"),
                    "minutes": round(total, 1), "isToday": d == today})
    return out


# A "hit" day needs one CONTIGUOUS run this long, not minutes summed across
# several short ones -- 5 x 6-minute glances at code is not the thing this is
# meant to reward, and summing would let it count as one anyway.
STREAK_MIN_MINUTES = 25
STREAK_MAX_DAYS = 90


def streak(min_minutes=STREAK_MIN_MINUTES, max_days=STREAK_MAX_DAYS):
    """
    Consecutive days, walking back from today, with at least one deep_work
    run of min_minutes or more.

    Today gets special treatment: if it hasn't produced a qualifying run YET,
    that is not a break -- the day isn't over. Only a PAST day with no
    qualifying run ends the streak. Capped at max_days so a system that's
    been running for months doesn't scan its entire history on every request.
    """
    today = datetime.now().date()
    count = 0
    d = today
    for _ in range(max_days + 1):
        hit = any(r.get("mode") == "deep_work" and r.get("minutes", 0) >= min_minutes
                  for r in _read_runs(d))
        if hit:
            count += 1
            d -= timedelta(days=1)
            continue
        if d == today:
            d -= timedelta(days=1)
            continue
        break
    return {"days": count, "minMinutes": min_minutes}


# --- Spotify -----------------------------------------------------------
#
# The Spotify MCP tool (get_currently_playing) is reachable only from a chat
# session, never from this plain-stdlib server -- there is no local API
# credential on this machine for dashboard.py to poll on its own. So this is
# a READER, not a poller: it shows whatever a chat session last wrote to
# SPOTIFY_SNAPSHOT, and only if it's fresh. A stale snapshot displayed as
# "now playing" would be exactly the kind of invented-looking claim the
# facts-only rule exists to prevent, so it returns None past the cutoff
# rather than show a lie by omission.
SPOTIFY_SNAPSHOT = os.path.join(LOGS_DIR, "spotify_now.json")
SPOTIFY_STALE_SECONDS = 600


def spotify_now():
    snap = _load(SPOTIFY_SNAPSHOT, None)
    if not snap or not snap.get("takenAt"):
        return None
    try:
        age = (datetime.now() - datetime.fromisoformat(snap["takenAt"])).total_seconds()
    except ValueError:
        return None
    if age > SPOTIFY_STALE_SECONDS:
        return None
    snap["ageSeconds"] = round(age)
    return snap


# --- Grimoire's ICS feeds -------------------------------------------------
#
# Grimoire's client calls `/ics?cal=<n>` on ITS OWN origin (config.js:
# icsProxyPath '/ics'), because Google's iCal endpoint sends no CORS header
# and a browser will not let the page read it directly. Serving Grimoire from
# psychowl's origin means psychowl must answer that same route.
#
# This regex is a deliberate COPY of grimoire-calendar/tools/serve.py's
# URL_RE, not an import: that file is a script, and importing a script for
# one regex couples psychowl to its argv handling. Both read the same
# config files, so they cannot disagree about which calendar is index n --
# the config itself is the single source of truth, which is the property
# serve.py's docstring actually argues for.

_URL_RE = re.compile(r"""\burl\s*:\s*(['"])(.*?)\1""", re.DOTALL)


def ics_urls():
    """Feed URLs from grimoire's config, in config order (index = cal id)."""
    for name in ("config.local.js", "config.js"):
        path = os.path.join(GRIMOIRE_DIR, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                return [m.group(2) for m in _URL_RE.finditer(f.read())]
        except OSError:
            continue
    return []


def plan_blocks():
    """Perfect Ari's whole day, in order -- the hub renders it as a timeline.
    Imported from profile_plan so the half-open/wraps-midnight tiling rule
    stays in exactly one place."""
    try:
        import profile_plan
        p = profile_plan.load()
        return [{"start": b["start"], "name": b["name"],
                 "emoji": b.get("emoji", ""),
                 "modes": list(b.get("modes") or []),
                 "awayOk": bool(b.get("away_ok"))}
                for b in profile_plan.blocks_sorted(p)]
    except Exception:
        return []


def summary():
    """Everything the hub's non-live cards need, in one read."""
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "docket": docket(),
        "brief": morning_brief(),
        "nightowl": nightowl(),
        "modes": mode_totals(),
        "week": week_bars(),
        "streak": streak(),
        "spotify": spotify_now(),
        "plan": plan_blocks(),
        "apps": {
            "focusflow": os.path.exists(FOCUSFLOW_HTML),
            "grimoire": os.path.isdir(GRIMOIRE_DIR),
        },
    }


if __name__ == "__main__":
    import sys
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    print(json.dumps(summary(), indent=2, ensure_ascii=False))
