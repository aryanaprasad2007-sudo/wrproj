"""
Renders hub/index.html - the NightOwl dashboard.

Data is baked into the page at build time because a file:// page cannot fetch
local JSON. The clock, timers and theme are live in the browser; the anime and
system data are refreshed by re-running this script (`no sync`).
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

import anime_sync  # noqa: E402

CONFIG = os.path.join(ROOT, "config.json")
STATE = os.path.join(ROOT, "data", "state.json")
FOCUS_SESSIONS = os.path.join(ROOT, "data", "focus_sessions.json")
CALENDAR = os.path.join(ROOT, "data", "calendar.json")
WRPROJ = os.path.dirname(ROOT)   # nightowl/'s parent - Swing-Pro-Trading, Daily-Docket etc. are siblings, not nested
NOTION = os.path.join(ROOT, "data", "notion.json")
DOCKET_DATA = os.path.join(WRPROJ, "Daily-Docket", "docket_data.json")
DOCKET_SLIPS = os.path.join(WRPROJ, "Daily-Docket", "slips.json")
SOLO_LEVELING = os.path.join(WRPROJ, "Solo-Leveling-System", "solo_leveling_live.html")
DOCKET_PWA = os.path.join(WRPROJ, "daily-docket-pwa", "index.html")
MORNING_BRIEF_DIR = os.path.join(WRPROJ, "Morning-Brief")
IAPE_COCKPIT = os.path.join(WRPROJ, "Swing-Pro-Trading", "cockpit.html")
DOCKET_ARTIFACT_URL = "https://claude.ai/code/artifact/98bafd13-a2a6-4b05-83a8-84c357fa4dc1"
OUT = os.path.join(ROOT, "hub", "index.html")


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def build_console():
    """One distilled line for the greeting console: a day counter plus a
    single computed pointer at whatever's most worth knowing right now -
    not a task list, just the read-out. Pulls the same overdue/slipped/
    cross-check signals the old verdict banner used, but collapses them to
    a count and one named "top loop" instead of a breakdown."""
    notion = load_json(NOTION, None)
    docket = load_json(DOCKET_DATA, None)
    slips = load_json(DOCKET_SLIPS, {}) or {}

    overdue = [t for t in (notion or {}).get("tasks", []) if t.get("overdue")]
    slipped = [v for v in slips.values() if v.get("count", 0) >= 2 and not v.get("cleared")]
    crosscheck = [c for c in (docket or {}).get("crosscheck", []) if c.get("severity") != "info"]

    open_loops = len(overdue) + len(slipped) + len(crosscheck)

    top_loop = None
    if overdue:
        top_loop = sorted(overdue, key=lambda t: t["due"])[0]["title"]
    elif slipped:
        top_loop = sorted(slipped, key=lambda v: -v.get("count", 0))[0].get("text")
    elif crosscheck:
        top_loop = crosscheck[0].get("text")

    if open_loops == 0:
        status = "nominal"
    elif open_loops <= 2:
        status = "attention"
    else:
        status = "overload"

    return {
        "day": datetime.now().timetuple().tm_yday,
        "status": status,
        "openLoops": open_loops,
        "topLoop": top_loop,
    }


def build_tracker():
    """
    Today's lifestyle-tracker summary, baked in at build time.

    The tracker is a live HTTP server; this hub is a static file:// page. The
    card is therefore built in two halves and this is the half that always
    works: read today's mode log off disk so the card says something true even
    with the tracker stopped, the laptop offline, and nothing listening on
    8787. The card's JS then TRIES to upgrade itself from the live server and
    silently keeps this view if it can't.

    That split is deliberate. Making the hub depend on a background process
    being up would be a regression -- `no hub` has always worked cold.

    Everything here traces to a log row. Nothing is inferred, and there is no
    EXP: Solo-Leveling-System/system_bridge.py already owns that path (it
    currently reads the retired activity_log.csv, so it needs repointing at
    this log rather than a second scorer competing with it).
    """
    day = datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(WRPROJ, "logs", f"modes-{day}.jsonl")

    runs = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    runs.append(json.loads(line))
                except ValueError:
                    continue          # a half-written final line is expected

    totals = {}
    for r in runs:
        totals[r["mode"]] = totals.get(r["mode"], 0) + r.get("minutes", 0)
    ranked = sorted(({"mode": m, "minutes": round(v, 1)} for m, v in totals.items()),
                    key=lambda t: -t["minutes"])

    # Perfect Ari's current block. Imported rather than reimplemented: blocks
    # tile the day half-open and wrap past midnight, and a second copy of that
    # rule would drift out of sync with profile_plan's. Guarded because
    # nightowl must still build if the tracker project is absent.
    block = None
    try:
        sys.path.insert(0, os.path.join(WRPROJ, "src"))
        import profile_plan             # noqa: E402
        b = profile_plan.plan_for_now()
        if b:
            block = {"name": b["name"], "emoji": b.get("emoji", ""),
                     "modes": list(b.get("modes") or []),
                     "awayOk": bool(b.get("away_ok"))}
    except Exception:
        block = None

    baseline = load_json(os.path.join(WRPROJ, "logs", "torso_baseline.json"), None)
    if baseline and baseline.get("angles"):
        angles = sorted(baseline["angles"])
        baseline = {"samples": len(angles),
                    "median": round(angles[len(angles) // 2], 1)}
    else:
        baseline = None

    return {
        "date": day,
        "runs": len(runs),
        "totals": ranked,
        "trackedMinutes": round(sum(totals.values()), 1),
        "last": runs[-1] if runs else None,
        "block": block,
        "baseline": baseline,
        "apiUrl": "http://127.0.0.1:8787",
    }


def latest_morning_brief():
    if not os.path.isdir(MORNING_BRIEF_DIR):
        return None
    briefs = sorted(
        f for f in os.listdir(MORNING_BRIEF_DIR)
        if f.startswith("morning-brief-") and f.endswith(".md")
    )
    return os.path.join(MORNING_BRIEF_DIR, briefs[-1]) if briefs else None


def build_payload():
    cfg = load_json(CONFIG, {})
    state = load_json(STATE, {})
    cache = anime_sync.load_cache() or {"shows": [], "season": "?", "year": ""}
    shows = cache.get("shows", [])
    wl = anime_sync.load_watchlist()

    by_id = {s["id"]: s for s in shows}
    queue = []
    for item in wl.get("items", []):
        s = by_id.get(item["id"], {})
        queue.append({
            "id": item["id"],
            "title": s.get("title") or item.get("title"),
            "progress": item.get("progress", 0),
            "episodes": s.get("episodes"),
            "cover": s.get("cover"),
            "color": s.get("color", "#c084fc"),
            "url": s.get("url"),
            "nextEpisode": s.get("nextEpisode"),
            "nextAiringAt": s.get("nextAiringAt"),
            "score": s.get("score"),
        })
    queue.sort(key=lambda q: (q["nextAiringAt"] or 9e18))

    tracked = {q["id"] for q in queue}
    seasonal = [s for s in shows if s["id"] not in tracked and s.get("format") == "TV"]
    seasonal = seasonal[: cfg.get("anime", {}).get("maxSeasonalShown", 14)]

    cal = load_json(CALENDAR, None)
    console = build_console()
    tracker = build_tracker()

    # Direct file/URL launches that don't need the nightowl:// indirection -
    # these are just files or a web URL, not registered .exe paths.
    links = [{"label": "The Docket", "url": DOCKET_ARTIFACT_URL}]
    if os.path.exists(SOLO_LEVELING):
        links.append({"label": "Solo Leveling", "url": Path(SOLO_LEVELING).as_uri()})
    if os.path.exists(DOCKET_PWA):
        links.append({"label": "Docket PWA", "url": Path(DOCKET_PWA).as_uri()})
    brief = latest_morning_brief()
    if brief:
        links.append({"label": "Morning Brief", "url": Path(brief).as_uri()})
    if os.path.exists(IAPE_COCKPIT):
        links.append({"label": "iAPE Cockpit", "url": Path(IAPE_COCKPIT).as_uri()})

    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {
            "wake": cfg.get("wake", "07:30"),
            "bedtime": cfg.get("bedtime", "01:30"),
            "windDownMinutes": cfg.get("windDownMinutes", 60),
            "eyeBreakMinutes": cfg.get("eyeBreakMinutes", 25),
            "deepWorkMinutes": cfg.get("deepWorkMinutes", 50),
            "gameBudgetMinutes": cfg.get("gameBudgetMinutes", 120),
        },
        "state": {
            "mode": state.get("mode", "auto"),
            "lastGameMinutes": state.get("lastGameMinutes"),
            "kelvinOffset": state.get("kelvinOffset", 0),
        },
        "anime": {
            "season": f"{cache.get('season', '').title()} {cache.get('year', '')}",
            "stale": cache.get("stale", False),
            "upcoming": anime_sync.upcoming(shows, days=7),
            "queue": queue,
            "seasonal": seasonal,
        },
        "calendar": cal,      # null if never synced - the template shows a placeholder
        "console": console,   # day counter + distilled open-loops line for the greeting console
        "tracker": tracker,   # lifestyle tracker: today's runs, baked. Upgraded live if the server is up.
        "docketUrl": DOCKET_ARTIFACT_URL,
        "nightRoutine": cfg.get("nightRoutine", {"steps": [], "lightsOutTime": "00:45", "stillAwake": ""}),
        "links": links,       # direct file/URL launches - Solo Leveling, Docket, Docket PWA, Morning Brief, iAPE Cockpit
        "games": cfg.get("steamGames", []),
        "apps": [
            {"key": "brave", "label": "Brave"},
            {"key": "vscode", "label": "VS Code"},
            {"key": "obsidian", "label": "Obsidian"},
            {"key": "notion", "label": "Notion"},
            {"key": "vlc", "label": "VLC"},
            {"key": "obs", "label": "OBS"},
            {"key": "steam", "label": "Steam"},
            {"key": "hoyoplay", "label": "HoYoPlay"},
            {"key": "govee", "label": "Govee"},
        ],
    }


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NightOwl</title>
<style>
:root{
  /* grimoire palette: plum vellum + rose-violet foil, lifted from grimoire-calendar/css/grimoire.css */
  --void:#08050f; --plum-900:#0d0719; --plum-800:#140c26; --plum-700:#1c1133; --plum-600:#261745;
  --foil:#e79ad8; --foil-dim:rgba(231,154,216,.28); --foil-hair:rgba(231,154,216,.17);
  --foil-text:#ffdcf4; --foil-glow:rgba(231,154,216,.55);
  --violet:#a77bff; --violet-dim:rgba(167,123,255,.18);
  --rose:#ff9ad5; --rose-dim:rgba(255,154,213,.16);

  --bg1:var(--plum-900); --bg2:var(--plum-800); --card:rgba(20,12,38,.74); --ink:#efe7ff; --sub:#bcaadf;
  --line:var(--foil-hair); --pink:var(--rose); --purple:var(--violet); --soft:rgba(255,255,255,.04);
  --shadow:inset 0 0 70px -30px var(--foil-dim), 0 20px 50px -30px rgba(0,0,0,.85); --ok:#7ee0a8; --warn:#e79ad8; --bad:#ff6b81;

  --serif:'Iowan Old Style','Palatino Linotype',Georgia,'Times New Roman',serif;
  --sans:'Quicksand','Segoe UI',system-ui,sans-serif;
  --mono:'Cascadia Code',ui-monospace,'Consolas','SFMono-Regular',monospace;
}
html[data-night="1"]{
  --bg1:var(--void); --bg2:var(--plum-900); --card:rgba(13,7,25,.82); --ink:#efe7ff; --sub:#8676ab;
  --line:rgba(231,154,216,.12); --pink:var(--rose); --purple:var(--violet); --soft:rgba(255,255,255,.03);
  --shadow:inset 0 0 70px -30px var(--foil-dim), 0 20px 50px -30px rgba(0,0,0,.95); --ok:#7ee0a8; --warn:#e79ad8; --bad:#ff6b81;
}
*{box-sizing:border-box}
body{
  margin:0; padding:28px 22px 60px; position:relative;
  font-family:var(--sans);
  background:linear-gradient(150deg,var(--bg1),var(--bg2)); color:var(--ink);
  min-height:100vh; transition:background .8s ease,color .4s ease;
  overflow-x:hidden;
}
/* the sky - CSS-only starfield + vignette, same trick as grimoire-calendar */
body::before{
  content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
  background-image:
    radial-gradient(1.4px 1.4px at 12% 18%,#fff,transparent),
    radial-gradient(1px 1px at 28% 62%,#dcd2ff,transparent),
    radial-gradient(1.6px 1.6px at 44% 11%,#fff,transparent),
    radial-gradient(1px 1px at 58% 74%,#c3aaff,transparent),
    radial-gradient(1.2px 1.2px at 71% 29%,#fff,transparent),
    radial-gradient(1px 1px at 84% 57%,#ffe9f8,transparent),
    radial-gradient(1.5px 1.5px at 92% 20%,#fff,transparent),
    radial-gradient(1px 1px at 7% 83%,#cbb9ff,transparent),
    radial-gradient(1px 1px at 36% 91%,#fff,transparent),
    radial-gradient(1.2px 1.2px at 64% 45%,#fff,transparent);
  opacity:.55; animation:twinkle 8s ease-in-out infinite;
}
body::after{
  content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
  background:
    radial-gradient(900px 500px at 78% -8%, rgba(120,70,210,.20), transparent 70%),
    radial-gradient(760px 420px at 4% 108%, rgba(200,90,180,.14), transparent 70%);
}
@keyframes twinkle{0%,100%{opacity:.55}50%{opacity:.85}}
@media (prefers-reduced-motion: reduce){ body::before{animation:none} }
.wrap{max-width:1220px;margin:0 auto;position:relative;z-index:1}
a{text-decoration:none;color:inherit}

/* corner-tick panel treatment, lifted from grimoire-calendar's .panel */
.card,.ribbon{position:relative}
.card::before,.card::after,.ribbon::before,.ribbon::after{
  content:''; position:absolute; width:11px; height:11px; pointer-events:none;
  border-color:var(--foil); border-style:solid; opacity:.6;
}
.card::before,.ribbon::before{ top:-1px; left:-1px; border-width:1px 0 0 1px; }
.card::after,.ribbon::after{ bottom:-1px; right:-1px; border-width:0 1px 1px 0; }

/* ---------- header ---------- */
header{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:22px}
.hello{font-family:var(--serif);font-size:31px;font-weight:400;letter-spacing:.01em;margin:0 0 4px}
.hello span{background:linear-gradient(100deg,var(--foil-text),var(--pink));-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{color:var(--sub);font-size:15px;margin:0}
.clockbox{text-align:right}
.clock{font-family:var(--mono);font-size:46px;font-weight:700;letter-spacing:-1.5px;line-height:1;font-variant-numeric:tabular-nums;color:var(--foil-text);text-shadow:0 0 26px var(--foil-glow)}
.pill{display:inline-block;margin-top:8px;padding:5px 14px;border-radius:999px;font-family:var(--mono);font-size:11.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--foil-text);background:var(--foil-dim);border:1px solid var(--foil-hair)}

/* ---------- console line ---------- */
.consoleline{
  font-family:var(--mono); font-size:12.5px; letter-spacing:.06em;
  color:var(--sub); background:var(--card); backdrop-filter:blur(10px);
  border:1px solid var(--line); border-radius:14px; padding:12px 18px;
  margin-bottom:16px; display:flex; align-items:center; gap:11px;
  box-shadow:var(--shadow);
  opacity:0; animation:consoleIn .7s ease-out .15s forwards;
}
.consoleline .cdot{width:7px;height:7px;border-radius:50%;flex-shrink:0;box-shadow:0 0 10px -1px currentColor}
.consoleline.status-nominal .cdot{background:var(--ok);color:var(--ok)}
.consoleline.status-attention .cdot{background:var(--warn);color:var(--warn)}
.consoleline.status-overload .cdot{background:var(--bad);color:var(--bad)}
.consoleline b{color:var(--foil-text);font-weight:700;letter-spacing:.12em}
@keyframes consoleIn{ from{opacity:0;transform:translateY(-5px)} to{opacity:1;transform:translateY(0)} }

/* ---------- ribbon / day ring ---------- */
.ribbon{background:var(--card);backdrop-filter:blur(10px);border-radius:20px;padding:22px 24px;box-shadow:var(--shadow);margin-bottom:20px;border:1px solid var(--line)}
.rtop{display:flex;justify-content:space-between;font-family:var(--mono);font-size:12px;letter-spacing:.05em;color:var(--sub);margin-bottom:16px;font-weight:600}
.ringrow{display:flex;align-items:center;gap:30px;flex-wrap:wrap}
.ringwrap{position:relative;width:186px;height:186px;flex-shrink:0;
  opacity:0; animation:ringIn .8s cubic-bezier(.2,.8,.2,1) .25s forwards;}
.ringsvg{width:100%;height:100%;transform:rotate(-90deg)}
.ring-bg{fill:none;stroke:var(--soft);stroke-width:10}
.ring-fill{fill:none;stroke:url(#ringGrad);stroke-width:10;stroke-linecap:round;transition:stroke-dashoffset .6s}
.ring-now{fill:var(--plum-900);stroke:var(--foil);stroke-width:4}
.ringtick{fill:var(--pink);opacity:.85}
.ringtick.wd{fill:var(--violet)}
.ringcenter{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.ringcenter b{font-family:var(--mono);font-size:33px;font-weight:700;color:var(--foil-text);font-variant-numeric:tabular-nums;letter-spacing:-1px}
.ringcenter span{font-family:var(--mono);font-size:10px;color:var(--sub);text-transform:uppercase;letter-spacing:.16em;margin-top:3px}
@keyframes ringIn{ from{opacity:0;transform:scale(.86)} to{opacity:1;transform:scale(1)} }
@media (prefers-reduced-motion: reduce){ .consoleline,.ringwrap{animation:none;opacity:1} }
.rbot{display:flex;gap:22px;flex-wrap:wrap;flex:1;min-width:220px}
.stat b{display:block;font-family:var(--mono);font-size:22px;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums;color:var(--foil-text)}
.stat b .subms{font-size:.62em;font-weight:600;color:var(--sub);letter-spacing:-.2px}
.stat span{font-family:var(--mono);font-size:11px;color:var(--sub);font-weight:600;text-transform:uppercase;letter-spacing:.14em}

/* ---------- grid ---------- */
.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:20px}
@media(max-width:960px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);backdrop-filter:blur(10px);border:1px solid var(--line);border-radius:20px;padding:22px 24px;box-shadow:var(--shadow);margin-bottom:20px}
h2{font-family:var(--serif);font-weight:400;font-size:18px;letter-spacing:.05em;margin:0 0 16px;display:flex;align-items:center;gap:9px;color:var(--foil-text)}
h2 em{font-style:normal;font-family:var(--mono);font-size:11px;letter-spacing:.05em;color:var(--sub);font-weight:600;margin-left:auto}

/* ---------- timer ---------- */
.timerwrap{display:flex;align-items:center;gap:24px}
.ring{position:relative;width:150px;height:150px;flex-shrink:0}
.ring svg{transform:rotate(-90deg)}
.ring .t{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.ring .t b{font-size:31px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-1px}
.ring .t span{font-size:11px;color:var(--sub);text-transform:uppercase;letter-spacing:.8px;font-weight:700}
.tbtns{display:flex;flex-direction:column;gap:8px;flex:1}

/* ---------- agenda ---------- */
.ag{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);align-items:center}
.ag:last-child{border-bottom:none}
.ag .bar{width:4px;align-self:stretch;border-radius:3px;background:var(--line);flex-shrink:0}
.ag.now .bar{background:linear-gradient(180deg,var(--pink),var(--purple))}
.ag .m{flex:1;min-width:0}
.ag .m b{display:block;font-size:14px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ag.done .m b{opacity:.5;text-decoration:line-through}
.ag .m span{font-size:12px;color:var(--sub)}
.ag .tag{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;padding:3px 8px;border-radius:7px;background:var(--soft);color:var(--pink);flex-shrink:0}
.ag.now .tag{background:linear-gradient(100deg,var(--pink),var(--purple));color:#fff}

/* ---------- kawaii Today card ---------- */
.card.kawaii{position:relative}
.kawaii-stars{
  position:absolute; inset:0; z-index:0; border-radius:20px; overflow:hidden; pointer-events:none;
  background-image:
    radial-gradient(1.6px 1.6px at 14% 20%, #fff, transparent),
    radial-gradient(1.2px 1.2px at 30% 66%, #ffe3f6, transparent),
    radial-gradient(1.8px 1.8px at 50% 12%, #fff, transparent),
    radial-gradient(1.2px 1.2px at 66% 76%, #ffd9f0, transparent),
    radial-gradient(1.6px 1.6px at 80% 30%, #fff, transparent),
    radial-gradient(1.2px 1.2px at 90% 58%, #ffe9fb, transparent),
    radial-gradient(1.4px 1.4px at 22% 86%, #fff, transparent),
    radial-gradient(1.4px 1.4px at 58% 44%, #ffd0ee, transparent),
    radial-gradient(1.3px 1.3px at 8% 50%, #fff, transparent),
    radial-gradient(1.3px 1.3px at 95% 12%, #ffe3f6, transparent);
  opacity:.75; animation:twinkle 4.5s ease-in-out infinite;
}
.card.kawaii h2,.card.kawaii>div,.card.kawaii>p{position:relative;z-index:1}
.sparkle{position:absolute;z-index:1;color:var(--foil);opacity:.5;pointer-events:none;
  font-size:13px; animation:sparkleFloat 4.2s ease-in-out infinite;}
.sparkle.s1{top:16px;right:96px;animation-delay:0s}
.sparkle.s2{bottom:54px;right:20px;font-size:10px;animation-delay:1.3s}
.sparkle.s3{top:46%;right:52px;font-size:9px;animation-delay:2.5s}
@keyframes sparkleFloat{0%,100%{opacity:.2;transform:translateY(0) scale(.9)}50%{opacity:.9;transform:translateY(-5px) scale(1.2)}}
.kawaii-msg{font-size:13.5px;line-height:1.55;color:var(--foil-text);background:var(--rose-dim);
  border:1px solid var(--foil-hair);border-radius:12px;padding:11px 14px;margin-bottom:12px}
.kawaii-msg b{color:var(--foil-text)}
.kawaii-msg.routine b{display:block;font-family:var(--serif);font-weight:400;font-size:14.5px;letter-spacing:.02em;margin-bottom:2px}
.rstep-time{display:block;font-family:var(--mono);font-size:10px;color:var(--sub);text-transform:uppercase;letter-spacing:.1em;margin-bottom:9px}
.rstep-item{font-size:12.5px;line-height:1.5;padding:3px 0 3px 18px;position:relative}
.rstep-item::before{content:'\2661';position:absolute;left:0;top:3px;color:var(--pink);font-size:11px}
@media (prefers-reduced-motion: reduce){ .kawaii-stars,.sparkle{animation:none} }

button{font-family:var(--mono);font-size:12px;letter-spacing:.04em;font-weight:650;padding:11px 16px;border-radius:12px;border:1px solid var(--line);background:var(--soft);color:var(--ink-soft,var(--ink));cursor:pointer;transition:transform .14s,filter .14s,border-color .14s}
button:hover{transform:translateY(-2px);border-color:var(--foil-dim);color:var(--foil-text)}
button.primary{background:var(--foil-dim);color:var(--foil-text);border:1px solid var(--foil)}
.presets{display:flex;gap:7px}
.presets button{flex:1;padding:8px 6px;font-size:11.5px}

/* ---------- anime ---------- */
.ep{display:flex;align-items:center;gap:13px;padding:11px 0;border-bottom:1px solid var(--line)}
.ep:last-child{border-bottom:none}
.ep img{width:42px;height:58px;object-fit:cover;border-radius:8px;flex-shrink:0;background:var(--soft)}
.ep .m{flex:1;min-width:0}
.ep .m b{display:block;font-size:14px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ep .m span{font-size:12px;color:var(--sub)}
.when{text-align:right;flex-shrink:0}
.when b{display:block;font-size:14px;font-weight:700}
.when span{font-size:11px;color:var(--sub);text-transform:uppercase;letter-spacing:.5px}
.tonight{color:var(--pink)}
.qbtn{border:1px solid var(--line);background:var(--soft);border-radius:9px;padding:5px 10px;font-size:12px;font-weight:700;cursor:pointer}
.prog{height:5px;border-radius:3px;background:var(--soft);margin-top:5px;overflow:hidden}
.prog i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--pink),var(--purple))}
.sgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:12px}
.s{position:relative;border-radius:12px;overflow:hidden;background:var(--soft);cursor:pointer;aspect-ratio:2/3}
.s img{width:100%;height:100%;object-fit:cover;display:block}
.s .ov{position:absolute;inset:auto 0 0 0;padding:22px 8px 7px;background:linear-gradient(transparent,rgba(20,10,28,.92));color:#fff}
.s .ov b{font-size:11px;font-weight:700;display:block;line-height:1.25;max-height:28px;overflow:hidden}
.s .add{position:absolute;top:6px;right:6px;width:24px;height:24px;border-radius:8px;background:rgba(255,255,255,.93);color:#3A2647;font-size:15px;font-weight:800;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .18s}
.s:hover .add{opacity:1}
.sc{position:absolute;top:6px;left:6px;background:rgba(20,10,28,.72);color:#fff;font-size:10.5px;font-weight:700;padding:2px 6px;border-radius:6px}

/* ---------- launch ---------- */
.launch{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:10px}
.launch a{background:var(--soft);border:1px solid var(--line);border-radius:13px;padding:13px 8px;text-align:center;font-size:13px;font-weight:650;transition:transform .15s,border-color .15s}
.launch a:hover{transform:translateY(-3px);border-color:var(--foil)}
.muted{color:var(--sub);font-size:13.5px;line-height:1.6}
footer{text-align:center;color:var(--sub);font-family:var(--mono);font-size:11px;letter-spacing:.05em;margin-top:30px}
.toast{position:fixed;left:50%;bottom:34px;transform:translate(-50%,90px);background:var(--plum-800);color:var(--foil-text);border:1px solid var(--foil);padding:13px 24px;border-radius:14px;font-weight:650;font-size:14px;box-shadow:0 8px 26px rgba(0,0,0,.5),0 0 20px -4px var(--foil-glow);transition:transform .34s;z-index:99}
.toast.on{transform:translate(-50%,0)}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <p class="hello">Good <span id="partofday">evening</span>.</p>
    <p class="sub" id="datestr"></p>
  </div>
  <div class="clockbox">
    <div class="clock" id="clock">--:--</div>
    <div class="pill" id="phase">--</div>
  </div>
</header>

<div class="consoleline" id="consoleLine">
  <div class="cdot"></div>
  <span id="consoleText">booting&hellip;</span>
</div>

<div class="ribbon">
  <div class="rtop"><span id="wakeLbl">Awake</span><span id="bedLbl">Bed</span></div>
  <div class="ringrow">
    <div class="ringwrap">
      <svg viewBox="0 0 220 220" class="ringsvg">
        <defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="var(--rose)"/><stop offset="1" stop-color="var(--violet)"/>
        </linearGradient></defs>
        <circle class="ring-bg" cx="110" cy="110" r="92"/>
        <circle class="ring-fill" id="ringFill" cx="110" cy="110" r="92"
                stroke-dasharray="578.1" stroke-dashoffset="578.1"/>
        <g id="ringTicks"></g>
        <circle class="ring-now" id="ringNow" cx="110" cy="18" r="7"/>
      </svg>
      <div class="ringcenter"><b id="ringPct">0%</b><span>of day elapsed</span></div>
    </div>
    <div class="rbot">
      <div class="stat"><b id="sAwake">-</b><span>awake</span></div>
      <div class="stat"><b id="sToBed">-</b><span>until bed</span></div>
      <div class="stat"><b id="sWind">-</b><span>until wind-down</span></div>
    </div>
  </div>
</div>

<div class="grid">
  <div>
    <div class="card kawaii">
      <div class="kawaii-stars"></div>
      <span class="sparkle s1">&#10022;</span>
      <span class="sparkle s2">&#10022;</span>
      <span class="sparkle s3">&#10022;</span>
      <h2>Today<em><a id="docketLink" href="#" target="_blank" style="color:inherit">open Docket &#8599;</a></em></h2>
      <div id="verdictZone"></div>
      <p class="muted" id="agendaSynced" style="font-size:11px;margin:0 0 6px"></p>
      <div id="agenda"></div>
    </div>

    <div class="card">
      <h2>Focus timer<em id="tmrLabel">deep work</em></h2>
      <div class="timerwrap">
        <div class="ring">
          <svg width="150" height="150">
            <circle cx="75" cy="75" r="66" fill="none" stroke="var(--soft)" stroke-width="13"/>
            <circle cx="75" cy="75" r="66" fill="none" stroke="url(#g)" stroke-width="13"
                    stroke-linecap="round" id="arc" stroke-dasharray="414.7" stroke-dashoffset="0"/>
            <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="var(--pink)"/><stop offset="1" stop-color="var(--purple)"/>
            </linearGradient></defs>
          </svg>
          <div class="t"><b id="tmr">50:00</b><span id="tmrState">ready</span></div>
        </div>
        <div class="tbtns">
          <button class="primary" id="startBtn" onclick="toggle()">Start</button>
          <button onclick="resetT()">Reset</button>
          <div class="presets">
            <button onclick="setT(25,'pomodoro')">25</button>
            <button onclick="setT(50,'deep work')">50</button>
            <button onclick="setT(90,'long block')">90</button>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Launch</h2>
      <div class="launch" id="apps"></div>
      <div class="launch" id="directLinks" style="margin-top:9px"></div>
    </div>

    <div class="card">
      <h2>Games<em id="gameNote"></em></h2>
      <div class="launch" id="games"></div>
    </div>
  </div>

  <div>
    <div class="card">
      <h2>Airing<em id="seasonLbl"></em></h2>
      <div id="upcoming"></div>
    </div>

    <div class="card">
      <h2>My queue<em id="queueNote"></em></h2>
      <div id="queue"></div>
    </div>

    <div class="card">
      <h2>This season<em>click to track</em></h2>
      <div class="sgrid" id="seasonal"></div>
    </div>
  </div>
</div>

<footer>NightOwl &middot; data built <span id="built"></span> &middot; <span id="staleNote"></span></footer>
</div>
<div class="toast" id="toast"></div>

<script>
const D = __NIGHTOWL_DATA__;
const C = D.config;

/* ---------- schedule maths (mirrors the PowerShell engine) ---------- */
function hm(s){const p=s.split(":");return {h:+p[0],m:+p[1]};}
function windowFor(now){
  const w=hm(C.wake), b=hm(C.bedtime);
  let wake=new Date(now); wake.setHours(w.h,w.m,0,0);
  if(now<wake) wake=new Date(wake.getTime()-864e5);
  let bed=new Date(wake); bed.setHours(b.h,b.m,0,0);
  if(bed<=wake) bed=new Date(bed.getTime()+864e5);
  const wd=new Date(bed.getTime()-C.windDownMinutes*6e4);
  return {wake,bed,wd};
}
function anchorTime(hhmm,W){
  /* Places a clock time (e.g. the night routine's "00:15") on the correct
     calendar date relative to the wake day - same rollover rule Get-NOSchedule
     uses for bedtime, so "12:15 AM" lands the night AFTER wake, not before it. */
  const p=hm(hhmm);
  let d=new Date(W.wake); d.setHours(p.h,p.m,0,0);
  if(d<=W.wake) d.setDate(d.getDate()+1);
  return d;
}
function phaseFor(now,W){
  if(now>=W.bed) return "past bedtime";
  if(now>=W.wd) return "wind-down";
  if(now < new Date(W.wake.getTime()+72e5)) return "morning";
  if(now >= new Date(W.bed.getTime()-18e6)) return "evening";
  return "day";
}
function dur(ms){
  const m=Math.round(Math.abs(ms)/6e4), h=Math.floor(m/60), r=m%60;
  if(h===0) return r+"m";
  return h+"h "+String(r).padStart(2,"0")+"m";
}
/* Same h/m head as dur(), but keeps the running seconds.milliseconds visible
   as a smaller trailing span - this is what actually shows the clock moving,
   since a plain "4h 29m" only changes once a minute. */
function fmtDurMs(ms){
  const neg=ms<0; ms=Math.abs(ms);
  const totalSec=ms/1000;
  const h=Math.floor(totalSec/3600), m=Math.floor((totalSec%3600)/60), s=totalSec%60;
  let head="";
  if(h>0) head=h+"h "+String(m).padStart(2,"0")+"m ";
  else if(m>0) head=m+"m ";
  return (neg?"-":"")+head+'<span class="subms">'+s.toFixed(3).padStart(6,"0")+"s</span>";
}

/* ---------- live header ---------- */
function tick(){
  const now=new Date(), W=windowFor(now), ph=phaseFor(now,W);
  document.getElementById("clock").textContent=now.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",hour12:false});
  document.getElementById("datestr").textContent=now.toLocaleDateString([], {weekday:"long",month:"long",day:"numeric"});
  document.getElementById("phase").textContent=ph;
  const hr=now.getHours();
  document.getElementById("partofday").textContent = hr<5?"night":hr<12?"morning":hr<18?"afternoon":"evening";

  document.documentElement.dataset.night = (now>=W.wd || now<W.wake) ? "1" : "0";

  const span=W.bed-W.wake, done=Math.min(Math.max(now-W.wake,0),span), pct=100*done/span;
  const RING_C=578.1;
  document.getElementById("ringFill").style.strokeDashoffset = RING_C*(1-pct/100);
  document.getElementById("ringPct").textContent = Math.round(pct)+"%";
  const ang=(pct/100)*2*Math.PI;
  document.getElementById("ringNow").setAttribute("cx", (110+92*Math.cos(ang)).toFixed(1));
  document.getElementById("ringNow").setAttribute("cy", (110+92*Math.sin(ang)).toFixed(1));
  document.getElementById("wakeLbl").textContent="Up since "+W.wake.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",hour12:false});
  document.getElementById("bedLbl").textContent="Bed "+W.bed.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",hour12:false});

  renderConsoleLine();
  requestAnimationFrame(()=>{});
}

/* ---------- day ring markers: wind-down + today's calendar events, placed
   once at boot since the underlying data is baked in at build time and
   doesn't change mid-session ---------- */
function renderRingMarks(){
  const now=new Date(), W=windowFor(now);
  const span=W.bed-W.wake;
  const R=92, CX=110, CY=110;
  const pctFor=t=>Math.min(1,Math.max(0,(t-W.wake)/span));
  const dotFor=(pct,cls)=>{
    const ang=pct*2*Math.PI;
    const x=CX+R*Math.cos(ang), y=CY+R*Math.sin(ang);
    return `<circle class="ringtick ${cls||''}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.6"/>`;
  };
  let html = dotFor(pctFor(W.wd), "wd");
  const cal=D.calendar;
  if(cal && cal.events){
    cal.events.forEach(e=>{
      if(e.allDay) return;
      const s=new Date(e.start);
      if(s<W.wake || s>W.bed) return;
      html += dotFor(pctFor(s));
    });
  }
  document.getElementById("ringTicks").innerHTML = html;
}

/* ---------- greeting console: day counter + distilled open-loops line,
   computed server-side in build_hub.py's build_console(); only the live
   "next event" countdown is computed here ---------- */
function renderConsoleLine(){
  const c=D.console;
  const el=document.getElementById("consoleLine");
  el.className="consoleline status-"+c.status;

  let nextPhrase="not synced";
  const cal=D.calendar;
  if(cal && cal.events){
    const now=new Date();
    const upcoming=cal.events.map(e=>({...e,s:new Date(e.start),e:new Date(e.end)}))
      .filter(e=>e.e>now).sort((a,b)=>a.s-b.s);
    nextPhrase = upcoming.length
      ? esc(upcoming[0].title)+(upcoming[0].s<=now?" now":" in "+dur(upcoming[0].s-now))
      : "clear";
  }

  const loopsPhrase = c.openLoops===0
    ? "systems clear"
    : c.openLoops+" open loop"+(c.openLoops===1?"":"s")+(c.topLoop?" &middot; soonest: "+esc(c.topLoop):"");

  document.getElementById("consoleText").innerHTML =
    `<b>DAY ${c.day}</b> &middot; ${loopsPhrase} &middot; next: ${nextPhrase}`;
}

/* Awake / to-bed / to-wind-down run on their own rAF loop rather than tick()'s
   1000ms interval - that's the only way the seconds.milliseconds actually
   look like they're moving instead of relabeling once a second. Throttled to
   ~20 repaints/sec: fast enough to read as live, far short of chasing every
   frame on a 240Hz panel for no visible benefit. */
let ribbonLast=0;
function ribbonLoop(ts){
  if(ts-ribbonLast>=50){
    ribbonLast=ts;
    const now=new Date(), W=windowFor(now);
    document.getElementById("sAwake").innerHTML=fmtDurMs(now-W.wake);
    document.getElementById("sToBed").innerHTML=fmtDurMs(W.bed-now);
    const toWd=W.wd-now;
    document.getElementById("sWind").innerHTML = toWd>0 ? fmtDurMs(toWd) : "started";
  }
  requestAnimationFrame(ribbonLoop);
}

/* ---------- protocol bridge ---------- */
function go(path,msg){
  location.href="nightowl://"+path;
  if(msg) toast(msg);
}
let tt;
function toast(m){
  const t=document.getElementById("toast");
  t.textContent=m; t.classList.add("on");
  clearTimeout(tt); tt=setTimeout(()=>t.classList.remove("on"),2300);
}

/* ---------- focus timer ---------- */
let total=C.deepWorkMinutes*60, left=total, run=false, iv=null;
const CIRC=414.7;
function paint(){
  const m=Math.floor(left/60), s=left%60;
  document.getElementById("tmr").textContent=m+":"+String(s).padStart(2,"0");
  document.getElementById("arc").style.strokeDashoffset=CIRC*(1-left/total);
}
function setT(min,label){
  total=min*60; left=total; run=false; clearInterval(iv);
  document.getElementById("tmrLabel").textContent=label;
  document.getElementById("tmrState").textContent="ready";
  document.getElementById("startBtn").textContent="Start";
  paint();
}
function toggle(){
  if(run){ run=false; clearInterval(iv);
    document.getElementById("startBtn").textContent="Resume";
    document.getElementById("tmrState").textContent="paused"; return; }
  run=true;
  document.getElementById("startBtn").textContent="Pause";
  document.getElementById("tmrState").textContent="running";
  iv=setInterval(()=>{
    left--; paint();
    if(left<=0){ clearInterval(iv); run=false; chime();
      document.getElementById("tmrState").textContent="done";
      document.getElementById("startBtn").textContent="Start";
      toast("Block finished - stand up for a minute");
      // Credits real EXP in the Solo Leveling System - fire-and-forget,
      // doesn't touch anything else the page is doing.
      const mins=Math.round(total/60);
      if(mins>0) go("focus/complete/"+mins); }
  },1000);
}
function resetT(){ left=total; run=false; clearInterval(iv);
  document.getElementById("startBtn").textContent="Start";
  document.getElementById("tmrState").textContent="ready"; paint(); }
function chime(){
  try{
    const a=new (window.AudioContext||window.webkitAudioContext)();
    [880,1174.7].forEach((f,i)=>{
      const o=a.createOscillator(), g=a.createGain();
      o.frequency.value=f; o.type="sine"; o.connect(g); g.connect(a.destination);
      const t=a.currentTime+i*0.18;
      g.gain.setValueAtTime(0,t); g.gain.linearRampToValueAtTime(.22,t+.03);
      g.gain.exponentialRampToValueAtTime(.001,t+.7);
      o.start(t); o.stop(t+.75);
    });
  }catch(e){}
}

/* ---------- agenda (Google Calendar) ---------- */
function fmtT(iso){ return new Date(iso).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",hour12:false}); }
function renderAgenda(){
  const el=document.getElementById("agenda");
  const cal=D.calendar;
  if(!cal){
    document.getElementById("agendaSynced").textContent="not synced";
    el.innerHTML='<p class="muted">No calendar data yet. Run <b>/nightowl</b> in Claude Code to pull today\'s schedule from Google Calendar.</p>';
    return;
  }
  document.getElementById("agendaSynced").textContent="synced "+cal.fetchedAtLocal;
  const now=new Date();
  const rows=cal.events.map(e=>({...e, s:new Date(e.start), e:new Date(e.end)}))
    .filter(e=>e.e>now)
    .sort((a,b)=>a.s-b.s);
  if(!rows.length){ el.innerHTML='<p class="muted">Nothing left on the calendar for today.</p>'; return; }
  el.innerHTML=rows.map(r=>{
    const isNow = r.s<=now && now<r.e;
    const cls = isNow ? "now" : "";
    const when = r.allDay ? "All day" : (fmtT(r.start)+" - "+fmtT(r.end));
    return `<div class="ag ${cls}">
      <div class="bar"></div>
      <div class="m"><b>${esc(r.title)}</b><span>${when}${r.calendar?" &middot; "+esc(r.calendar):""}</span></div>
      ${isNow?'<div class="tag">now</div>':""}
    </div>`;
  }).join("");
}

/* ---------- kawaii Today verdict / evening routine ----------
   Before the routine's first step: a cute distilled read on D.console's
   open-loop signal, with a 30-min heads-up teaser right before it starts.
   From step 1 through lights-out: a live walkthrough of tonight's wind-down
   routine, one step highlighted at a time. Past lights-out: the
   still-awake fallback. Recomputed every 30s alongside the agenda -
   the underlying data doesn't change fast enough to need more. */
function kawaiiVerdictHtml(){
  const c=D.console, n=c.openLoops;
  let msg, glyph;
  if(n===0){
    glyph="\u{1F338}";
    msg="Nothing pressing today - you're all caught up! Take a breather, you've earned it.";
  } else if(n<=2){
    glyph="\u{1F319}";
    msg=n+" thing"+(n===1?"":"s")+" to look after"+(c.topLoop?", starting with <b>"+esc(c.topLoop)+"</b>":"")+". Small steps - you've got this.";
  } else {
    glyph="⭐";
    msg=n+" things asking for your attention"+(c.topLoop?" - top of the pile: <b>"+esc(c.topLoop)+"</b>":"")+". One at a time, okay? I believe in you.";
  }
  return `<div class="kawaii-msg">${glyph} ${msg} \u{1F49F}</div>`;
}
function renderVerdictZone(){
  const el=document.getElementById("verdictZone");
  const now=new Date(), W=windowFor(now);

  const rt=D.nightRoutine||{steps:[]};
  if(!rt.steps||!rt.steps.length){ el.innerHTML=kawaiiVerdictHtml(); return; }

  const steps=rt.steps.map(s=>({...s, at:anchorTime(s.time,W)}));
  const lightsOut=anchorTime(rt.lightsOutTime||"00:45",W);
  // The cutover is the routine's own first step time (21:45 tonight), not a
  // separate guessed clock time - so it can never drift out of sync with the
  // actual routine again. A 30-minute lead-in shows a heads-up teaser instead
  // of jumping straight from task-verdict to "Step 1" with no warning.
  const teaserStart=new Date(steps[0].at.getTime()-30*6e4);

  if(now<teaserStart){ el.innerHTML=kawaiiVerdictHtml(); return; }
  if(now<steps[0].at){
    const mins=Math.round((steps[0].at-now)/6e4);
    el.innerHTML=`<div class="kawaii-msg">\u{1F319} Wind-down starts in ${mins}m. Get comfy ✨</div>`;
    return;
  }
  if(now>=lightsOut){
    el.innerHTML=`<div class="kawaii-msg">\u{1F4A4} Past lights-out. ${esc(rt.stillAwake||"")}</div>`;
    return;
  }
  let idx=0;
  for(let i=0;i<steps.length;i++){ if(now>=steps[i].at) idx=i; }
  const cur=steps[idx];
  const items=(cur.items||[]).map(t=>`<div class="rstep-item">${esc(t)}</div>`).join("");
  el.innerHTML=`<div class="kawaii-msg routine">
    <b>✨ Step ${idx+1}/${steps.length} &middot; ${esc(cur.title)}</b>
    <span class="rstep-time">${cur.time} start</span>
    ${items}
  </div>`;
}

/* ---------- anime ---------- */
function relDay(iso){
  const d=new Date(iso), now=new Date();
  const a=new Date(d.getFullYear(),d.getMonth(),d.getDate());
  const b=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  const diff=Math.round((a-b)/864e5);
  if(diff===0) return "today";
  if(diff===1) return "tomorrow";
  return d.toLocaleDateString([], {weekday:"short"});
}
function watchUrl(title){ return "https://www.crunchyroll.com/search?q="+encodeURIComponent(title); }

function renderUpcoming(){
  const el=document.getElementById("upcoming");
  const rows=D.anime.upcoming.slice(0,9);
  if(!rows.length){ el.innerHTML='<p class="muted">Nothing scheduled in the next week.</p>'; return; }
  el.innerHTML=rows.map(r=>{
    const rd=relDay(r.at), cls=rd==="today"?"tonight":"";
    return `<a class="ep" href="${watchUrl(r.title)}" target="_blank" style="text-decoration:none;color:inherit">
      <img src="${r.cover}" loading="lazy" alt="">
      <div class="m"><b>${esc(r.title)}</b><span>Episode ${r.episode} &middot; watch &#8599;</span></div>
      <div class="when"><b class="${cls}">${r.time}</b><span>${rd}</span></div>
    </a>`;
  }).join("");
}
function renderQueue(){
  const el=document.getElementById("queue");
  const q=D.anime.queue;
  document.getElementById("queueNote").textContent=q.length?q.length+" tracked":"";
  if(!q.length){ el.innerHTML='<p class="muted">Nothing tracked yet. Click a poster below to add it, then use +1 as you watch.</p>'; return; }
  el.innerHTML=q.map(s=>{
    const tot=s.episodes||s.nextEpisode||12;
    const pct=Math.min(100,100*s.progress/tot);
    const behind=s.nextEpisode?Math.max(0,(s.nextEpisode-1)-s.progress):0;
    return `<div class="ep">
      <img src="${s.cover||""}" loading="lazy" alt="">
      <div class="m">
        <b>${esc(s.title)}</b>
        <span>${s.progress} / ${s.episodes||"?"} watched${behind?" &middot; "+behind+" behind":""}</span>
        <div class="prog"><i style="width:${pct}%"></i></div>
      </div>
      <div style="display:flex;gap:5px;flex-shrink:0">
        <a class="qbtn" href="${watchUrl(s.title)}" target="_blank" style="text-decoration:none;display:inline-flex;align-items:center">&#9654;</a>
        <button class="qbtn" data-act="watch" data-id="${s.id}">+1</button>
        <button class="qbtn" data-act="untrack" data-id="${s.id}">&times;</button>
      </div>
    </div>`;
  }).join("");
}
function renderSeasonal(){
  const el=document.getElementById("seasonal");
  el.innerHTML=D.anime.seasonal.map(s=>`
    <div class="s" data-act="track" data-id="${s.id}">
      <img src="${s.cover}" loading="lazy" alt="">
      ${s.score?`<div class="sc">${s.score}</div>`:""}
      <div class="add">+</div>
      <div class="ov"><b>${esc(s.title)}</b></div>
    </div>`).join("");
}

/* Titles are looked up from the data at click time rather than interpolated
   into HTML attributes - quoting them inline breaks on apostrophes. */
const TITLES={};
[...D.anime.queue, ...D.anime.seasonal].forEach(s=>TITLES[s.id]=s.title);
document.addEventListener("click",e=>{
  const el=e.target.closest("[data-act]");
  if(!el) return;
  const id=el.dataset.id, act=el.dataset.act, name=TITLES[id]||"show";
  const msg={watch:"+1 "+name, untrack:"Removed "+name, track:"Tracking "+name}[act];
  go("anime/"+act+"/"+id, msg);
  setTimeout(()=>location.reload(),1600);
});
function esc(s){ return String(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

/* ---------- launchers ---------- */
function renderLaunch(){
  document.getElementById("apps").innerHTML =
    D.apps.map(a=>`<a href="nightowl://launch/${a.key}" onclick="toast('Opening ${a.label}')">${a.label}</a>`).join("");
  document.getElementById("directLinks").innerHTML =
    (D.links||[]).map(l=>`<a href="${l.url}" target="_blank">${esc(l.label)}</a>`).join("");
  document.getElementById("games").innerHTML =
    D.games.map(g=>`<a href="steam://rungameid/${g.id}" onclick="toast('Launching ${esc(g.name)}')">${esc(g.name)}</a>`).join("");
  if(D.state.lastGameMinutes!=null)
    document.getElementById("gameNote").textContent="last session "+D.state.lastGameMinutes+"m / "+C.gameBudgetMinutes+"m budget";
}

/* ---------- boot ---------- */
document.getElementById("seasonLbl").textContent=D.anime.season;
document.getElementById("built").textContent=D.generatedAt;
document.getElementById("staleNote").textContent=D.anime.stale?"anime data is stale (network failed, showing last good copy)":"anime data fresh from AniList";
document.getElementById("docketLink").href=D.docketUrl;
renderUpcoming(); renderQueue(); renderSeasonal(); renderLaunch(); renderAgenda(); renderRingMarks(); renderVerdictZone();
setT(C.deepWorkMinutes,"deep work");
tick(); setInterval(tick,1000);
requestAnimationFrame(ribbonLoop);
setInterval(()=>{ renderAgenda(); renderVerdictZone(); },30000);   // re-checks "now" + routine step without a full reload
</script>
</body>
</html>
"""


def main():
    payload = build_payload()
    html = TEMPLATE.replace("__NIGHTOWL_DATA__", json.dumps(payload, ensure_ascii=False))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    a = payload["anime"]
    print(f"hub built -> {OUT}")
    print(f"  {len(a['upcoming'])} upcoming episodes, {len(a['queue'])} tracked, "
          f"{len(a['seasonal'])} seasonal, stale={a['stale']}")


if __name__ == "__main__":
    main()
