"""
System Bridge — turn real focus into real EXP.

Three independent, additive EXP sources feed the Hunter Progression dashboard,
each with its own idempotent per-day ledger so none of them can double-pay or
step on each other:

  1. Lifestyle tracker deep-work minutes (../logs/modes-*.jsonl) - ambient
     desk monitoring via camera + window sensor, credited per deep_work
     minute. FIXED 2026-08-12: this used to read ../activity_log.csv, the
     abandoned productive/lazy/away punisher-era format. That file has been
     permanently empty since the project pivoted to lifestyle tracking, so
     this source silently paid 0 EXP for weeks -- not broken, just reading a
     file nothing writes anymore. Now reads the real mode log via
     psychowl_data.mode_totals(), the same aggregation psychowl's hub uses,
     so this and the hub can't disagree about what a day's deep work was.
  2. NightOwl focus-timer sessions (nightowl/data/focus_sessions.json) - a
     deliberate "I'm doing a focus block right now" action, distinct from the
     tracker's ambient signal, so it gets its own ledger rather than being
     summed into the same one. (The two COULD measure overlapping real
     minutes if both are running at once - this isn't reconciled, it's a fun
     gamification layer, not an audit system. Documented here rather than
     pretended away.)
  3. NightOwl "clean wind-down nights" - scanned from nightowl.log's own
     MODE -> transitions: did sleep mode hold for a real stretch (>=3h) before
     the next work/game override? A flat bonus once per night, not a claim
     about actual sleep - NightOwl only ever knows what mode it was in.

Why a generated "live" file (same reason as before): browsers block a file://
page from fetching local JSON, so the data gets baked straight into the HTML
as `window.SYSTEM_FEED` (tracker), `window.NIGHTOWL_FEED` (focus sessions) and
`window.NIGHTOWL_NIGHTS` (clean-night bonuses).

Run:  python system_bridge.py      (from the Solo-Leveling-System folder)
Then open the generated solo_leveling_live.html.
"""
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGS_DIR = os.path.join(ROOT, "logs")
TEMPLATE = os.path.join(HERE, "solo_leveling_system.html")
LIVE = os.path.join(HERE, "solo_leveling_live.html")
FEED_JSON = os.path.join(HERE, "system_feed.json")

# nightowl/ is a sibling of Solo-Leveling-System/, both under wrproj/.
NIGHTOWL_FOCUS = os.path.join(ROOT, "nightowl", "data", "focus_sessions.json")
NIGHTOWL_LOG = os.path.join(ROOT, "nightowl", "logs", "nightowl.log")

# src/psychowl_data.py already knows how to total a day's mode log correctly
# (half-written final lines, missing files, all handled once) -- reusing it
# means this ledger and psychowl's own "today, measured" card are reading the
# exact same aggregation, not two implementations that can quietly drift.
sys.path.insert(0, os.path.join(ROOT, "src"))
import psychowl_data  # noqa: E402

XP_PER_FOCUS_MIN = 1        # 1 EXP per deep_work minute (lifestyle tracker)
XP_PER_NIGHTOWL_MIN = 1      # 1 EXP per minute of a completed NightOwl focus block
DEEP_WORK_MIN = 25           # a DAY needs this much deep_work to count as "a deep-work day"
CLEAN_NIGHT_BONUS = 20       # flat EXP for a wind-down that held >= MIN_CLEAN_HOURS
MIN_CLEAN_HOURS = 3
MODE_LOG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+MODE -> (\w+)")
_DAY_FILE_RE = re.compile(r"^modes-(\d{4}-\d{2}-\d{2})\.jsonl$")


def aggregate_tracker_days():
    """
    Per-day deep_work minutes and "how much of tracked time was deep work",
    one entry per modes-YYYY-MM-DD.jsonl file that exists.

    productivePct mirrors the old CSV version's meaning (productive checks /
    all checks that day) as closely as the new data allows: deep_work minutes
    over ALL tracked minutes that day, not just work-shaped ones -- so a day
    that was mostly `away` (a full gym+class day, say) doesn't score as
    "unproductive" the way a stalled desk session would.
    """
    if not os.path.isdir(LOGS_DIR):
        return []
    feed = []
    for name in sorted(os.listdir(LOGS_DIR)):
        m = _DAY_FILE_RE.match(name)
        if not m:
            continue
        day = m.group(1)
        totals = psychowl_data.mode_totals(day)
        if not totals["runs"]:
            continue
        by_mode = {t["mode"]: t["minutes"] for t in totals["totals"]}
        deep = by_mode.get("deep_work", 0.0)
        tracked = totals["trackedMinutes"]
        pct = round(100 * deep / tracked) if tracked else 0
        feed.append({
            "date": day,
            "minutes": round(deep, 1),
            "productivePct": pct,
            "deepWork": deep >= DEEP_WORK_MIN,
        })
    return feed


def aggregate_nightowl_focus():
    """Per-day minutes from completed NightOwl focus-timer blocks."""
    if not os.path.exists(NIGHTOWL_FOCUS):
        return []
    try:
        # PowerShell's Out-File -Encoding utf8 writes a BOM; plain "utf-8"
        # chokes on it (silently, into this except) - utf-8-sig strips it.
        with open(NIGHTOWL_FOCUS, "r", encoding="utf-8-sig") as f:
            sessions = json.load(f)
    except Exception:
        return []

    per_day = defaultdict(float)
    for s in sessions:
        day = s.get("date")
        mins = s.get("minutes")
        if day and isinstance(mins, (int, float)):
            per_day[day] += mins

    return [{"date": d, "minutes": round(m, 1)} for d, m in sorted(per_day.items())]


def scan_clean_nights(max_lines=20000):
    """Nights where NightOwl's own sleep mode held >= MIN_CLEAN_HOURS before the
    next work/game override - a flat bonus per calendar night it happened,
    keyed by the date sleep mode was entered."""
    if not os.path.exists(NIGHTOWL_LOG):
        return []

    events = []
    with open(NIGHTOWL_LOG, "r", encoding="utf-8-sig", errors="ignore") as f:
        lines = f.readlines()[-max_lines:]
    for line in lines:
        m = MODE_LOG_RE.match(line.strip())
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        events.append((ts, m.group(2)))
    events.sort(key=lambda e: e[0])

    nights = []
    seen_dates = set()
    for i, (ts, mode) in enumerate(events):
        date_key = ts.strftime("%Y-%m-%d")
        if mode != "sleep" or date_key in seen_dates:
            continue
        seen_dates.add(date_key)
        for ts2, mode2 in events[i + 1:]:
            if mode2 in ("work", "game"):
                if (ts2 - ts).total_seconds() / 3600.0 >= MIN_CLEAN_HOURS:
                    nights.append({"date": date_key, "bonus": CLEAN_NIGHT_BONUS})
                break
            # any other mode (winddown/anime/reset) doesn't end the night - keep looking
    return nights


# ---- JS that runs BEFORE the dashboard boots: credits EXP from all three feeds ----
INJECTOR = """
<script>
/* --- System Bridge: real focus -> real EXP (injected, runs before the app) --- */
(function(){
  var KEY = "slSystem_v1";
  var FEED = __FEED__;
  var NIGHTOWL_FEED = __NIGHTOWL_FEED__;
  var NIGHTOWL_NIGHTS = __NIGHTOWL_NIGHTS__;
  var XP_PER_MIN = __XP_PER_MIN__;
  var XP_PER_NO_MIN = __XP_PER_NO_MIN__;
  function xpToNext(l){return Math.round(50*Math.pow(l,1.5))+50;}
  var s;
  try { s = JSON.parse(localStorage.getItem(KEY) || "null"); } catch(e) { s = null; }
  if(!s) s = {};                       // the app's load() backfills everything else
  if(typeof s.level   !== "number") s.level = 1;
  if(typeof s.xp      !== "number") s.xp = 0;
  if(typeof s.totalXp !== "number") s.totalXp = 0;
  if(typeof s.statPoints !== "number") s.statPoints = 0;
  s.focusLog = s.focusLog || {};             // webcam coach: date -> minutes already paid
  s.nightOwlFocusLog = s.nightOwlFocusLog || {};   // NightOwl focus blocks: date -> minutes already paid
  s.nightsLog = s.nightsLog || {};                 // clean nights: date -> already paid (bool)
  var totalGain = 0, noGain = 0, nightsGain = 0;

  function award(xp){
    s.xp += xp; s.totalXp += xp;
    while(s.xp >= xpToNext(s.level)){ s.xp -= xpToNext(s.level); s.level++; s.statPoints += 3; }
  }

  for(var i=0;i<FEED.length;i++){
    var d = FEED[i];
    var paid = s.focusLog[d.date] || 0;
    var delta = d.minutes - paid;
    if(delta > 0){ var gain = Math.round(delta * XP_PER_MIN); award(gain); totalGain += gain; s.focusLog[d.date] = d.minutes; }
  }
  for(var i=0;i<NIGHTOWL_FEED.length;i++){
    var d = NIGHTOWL_FEED[i];
    var paid = s.nightOwlFocusLog[d.date] || 0;
    var delta = d.minutes - paid;
    if(delta > 0){ var gain = Math.round(delta * XP_PER_NO_MIN); award(gain); noGain += gain; s.nightOwlFocusLog[d.date] = d.minutes; }
  }
  for(var i=0;i<NIGHTOWL_NIGHTS.length;i++){
    var n = NIGHTOWL_NIGHTS[i];
    if(!s.nightsLog[n.date]){ award(n.bonus); nightsGain += n.bonus; s.nightsLog[n.date] = true; }
  }

  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch(e){}
  window.__FOCUS_FEED__ = FEED;
  window.__FOCUS_GAIN__ = totalGain;
  window.__NO_FEED__ = NIGHTOWL_FEED;
  window.__NO_GAIN__ = noGain;
  window.__NIGHTS_GAIN__ = nightsGain;
  window.__NIGHTS_COUNT__ = NIGHTOWL_NIGHTS.length;
})();
</script>
"""

# ---- JS that runs AFTER the dashboard boots: shows both feeds as chips ----
BANNER = """
<script>
/* --- System Bridge: focus banners --- */
(function(){
  function boot(){
    var feed = window.__FOCUS_FEED__ || [];
    var noFeed = window.__NO_FEED__ || [];
    var today = new Date();
    var ts = today.getFullYear()+"-"+String(today.getMonth()+1).padStart(2,"0")+"-"+String(today.getDate()).padStart(2,"0");
    var t = null, no = null;
    for(var i=0;i<feed.length;i++){ if(feed[i].date===ts) t = feed[i]; }
    for(var i=0;i<noFeed.length;i++){ if(noFeed[i].date===ts) no = noFeed[i]; }
    var wrap = document.querySelector(".wrap") || document.body;

    var box = document.createElement("div");
    box.className = "panel";
    box.style.borderColor = "rgba(120,200,255,0.55)";
    var mins = t ? t.minutes : 0;
    var pct  = t ? t.productivePct : 0;
    var gain = window.__FOCUS_GAIN__ || 0;
    box.innerHTML =
      '<div class="ptitle"><span class="dot"></span> FOCUS FEED &mdash; from your Productivity Coach <span class="ln"></span></div>' +
      '<div style="display:flex;gap:26px;flex-wrap:wrap;align-items:baseline">' +
        '<div><div style="font-family:ui-monospace,monospace;font-size:34px;color:#9be4ff;text-shadow:0 0 18px rgba(79,195,255,.5)">'+mins+'<span style="font-size:13px;color:#8197c2"> min</span></div><div style="font-size:11px;letter-spacing:.2em;color:#5d6f96;text-transform:uppercase">Focused today</div></div>' +
        '<div><div style="font-family:ui-monospace,monospace;font-size:34px;color:'+(pct>=70?"#5fe3a1":pct>=40?"#ffb454":"#ff6b81")+'">'+pct+'<span style="font-size:13px;color:#8197c2">%</span></div><div style="font-size:11px;letter-spacing:.2em;color:#5d6f96;text-transform:uppercase">Locked in</div></div>' +
        (gain>0 ? '<div><div style="font-family:ui-monospace,monospace;font-size:34px;color:#ffd877">+'+gain+'<span style="font-size:13px;color:#8197c2"> EXP</span></div><div style="font-size:11px;letter-spacing:.2em;color:#5d6f96;text-transform:uppercase">Credited this session</div></div>' : '') +
      '</div>' +
      '<div style="font-size:11px;color:#5d6f96;margin-top:10px">'+(t? 'Real deep-work minutes from the lifestyle tracker\\'s mode log. Every deep-work minute is 1 EXP.' : 'No tracker data for today yet &mdash; run <b>py -3.12 src/mode_log.py</b> (or psychowl) and re-generate to see your focus here.')+'</div>';
    if(wrap.firstChild) wrap.insertBefore(box, wrap.children[1] || null);
    else wrap.appendChild(box);

    var noGain = window.__NO_GAIN__ || 0;
    var nightsGain = window.__NIGHTS_GAIN__ || 0;
    var nightsCount = window.__NIGHTS_COUNT__ || 0;
    var noBox = document.createElement("div");
    noBox.className = "panel";
    noBox.style.borderColor = "rgba(205,110,235,0.55)";
    noBox.innerHTML =
      '<div class="ptitle"><span class="dot" style="background:#cd6eeb;box-shadow:0 0 10px rgba(205,110,235,.6)"></span> NIGHTOWL FEED &mdash; focus blocks + clean wind-downs <span class="ln"></span></div>' +
      '<div style="display:flex;gap:26px;flex-wrap:wrap;align-items:baseline">' +
        '<div><div style="font-family:ui-monospace,monospace;font-size:34px;color:#cd6eeb;text-shadow:0 0 18px rgba(205,110,235,.5)">'+(no?no.minutes:0)+'<span style="font-size:13px;color:#8197c2"> min</span></div><div style="font-size:11px;letter-spacing:.2em;color:#5d6f96;text-transform:uppercase">Deep work blocks today</div></div>' +
        '<div><div style="font-family:ui-monospace,monospace;font-size:34px;color:#9be4ff">'+nightsCount+'<span style="font-size:13px;color:#8197c2"> nights</span></div><div style="font-size:11px;letter-spacing:.2em;color:#5d6f96;text-transform:uppercase">Clean wind-downs banked</div></div>' +
        ((noGain+nightsGain)>0 ? '<div><div style="font-family:ui-monospace,monospace;font-size:34px;color:#ffd877">+'+(noGain+nightsGain)+'<span style="font-size:13px;color:#8197c2"> EXP</span></div><div style="font-size:11px;letter-spacing:.2em;color:#5d6f96;text-transform:uppercase">Credited this session</div></div>' : '') +
      '</div>' +
      '<div style="font-size:11px;color:#5d6f96;margin-top:10px">Finishing a NightOwl focus-timer block pays '+__XP_PER_NO_MIN__+' EXP/min. Holding a wind-down for '+__MIN_CLEAN_HOURS__+'+ hours without overriding back to work/game banks +'+__CLEAN_NIGHT_BONUS__+' EXP the next morning.</div>';
    wrap.insertBefore(noBox, box.nextSibling);
  }
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
</script>
"""


def build():
    feed = aggregate_tracker_days()
    nightowl_feed = aggregate_nightowl_focus()
    nightowl_nights = scan_clean_nights()

    with open(FEED_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "generated": datetime.now().isoformat(timespec="seconds"),
            "xpPerFocusMin": XP_PER_FOCUS_MIN,
            "xpPerNightOwlMin": XP_PER_NIGHTOWL_MIN,
            "cleanNightBonus": CLEAN_NIGHT_BONUS,
            "days": feed,
            "nightowlDays": nightowl_feed,
            "nightowlNights": nightowl_nights,
        }, f, indent=2)

    if not os.path.exists(TEMPLATE):
        raise SystemExit("Template not found: " + TEMPLATE)
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()

    injector = (INJECTOR
                .replace("__FEED__", json.dumps(feed))
                .replace("__NIGHTOWL_FEED__", json.dumps(nightowl_feed))
                .replace("__NIGHTOWL_NIGHTS__", json.dumps(nightowl_nights))
                .replace("__XP_PER_MIN__", str(XP_PER_FOCUS_MIN))
                .replace("__XP_PER_NO_MIN__", str(XP_PER_NIGHTOWL_MIN)))
    banner = (BANNER
              .replace("__XP_PER_NO_MIN__", str(XP_PER_NIGHTOWL_MIN))
              .replace("__MIN_CLEAN_HOURS__", str(MIN_CLEAN_HOURS))
              .replace("__CLEAN_NIGHT_BONUS__", str(CLEAN_NIGHT_BONUS)))

    # Injector must run BEFORE the app's main <script> reads localStorage.
    marker = '<script>\n"use strict";'
    if marker in html:
        html = html.replace(marker, injector + "\n" + marker, 1)
    else:
        html = html.replace("</head>", injector + "\n</head>", 1)
    # Banner runs after everything.
    html = html.replace("</body>", banner + "\n</body>", 1)

    with open(LIVE, "w", encoding="utf-8") as f:
        f.write(html)

    total_days = len(feed)
    total_min = round(sum(d["minutes"] for d in feed), 1)
    no_min = round(sum(d["minutes"] for d in nightowl_feed), 1)
    print("System Bridge complete.")
    print("  days of tracker deep work: {}".format(total_days))
    print("  total deep work:          {} min".format(total_min))
    print("  NightOwl focus:           {} min across {} day(s)".format(no_min, len(nightowl_feed)))
    print("  clean wind-down nights:   {}".format(len(nightowl_nights)))
    print("  feed written:             {}".format(FEED_JSON))
    print("  live dashboard:           {}".format(LIVE))
    if not feed and not nightowl_feed:
        print("\n  (No tracker logs (logs/modes-*.jsonl) and no NightOwl focus")
        print("   sessions yet. Run the tracker (py -3.12 src/mode_log.py, or")
        print("   psychowl) or complete a NightOwl focus block, then re-run this.)")


if __name__ == "__main__":
    build()
