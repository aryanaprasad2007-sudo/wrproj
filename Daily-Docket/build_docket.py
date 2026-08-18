"""
The Docket — build the daily worklist artifact.

Deterministic renderer: reads the day's pulled data (docket_data.json) plus your
persistent interests (interests.json) and writes:
  - docket.html         a full standalone page (bookmark this)
  - docket_widget.html  a fragment for pulling up as a Cowork artifact

Lanes: Right Now (a single standing focus item, pinned above everything — set
and cleared only by Claude in chat, never resets on rebuild, see `nowTask` in
docket_data.json) · Top 5 Today (what matters, checkable) · Today's Plan (the
day's shape, calendar anchors highlighted) · Carried Over (unfinished from
yesterday) · Due Today/Overdue · Cross-Check (where Notion, Calendar, and
Gmail disagree) · Today's Schedule · Needs a Reply/Action · This Week ·
Exploration (interests) · Notion Hub (links into every part of the workspace,
with live counts).

Click any row to check it off; state is saved per-day in the browser and resets
with tomorrow's fresh board.

After writing, the build self-verifies (see verify()) and exits non-zero with a
DOCKET BUILD FAILED line if the board doesn't match the data it came from.

Run:  py build_docket.py     (from the Daily-Docket folder)
"""
import json
import os
import sys
import html
import base64
import hashlib
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "docket_data.json")
INTERESTS = os.path.join(HERE, "interests.json")
LEDGER = os.path.join(HERE, "slips.json")
OUT = os.path.join(HERE, "docket.html")
WIDGET = os.path.join(HERE, "docket_widget.html")

EXPL_SHOWN = 3            # Exploration rows per day; the rest rotate in later
SLIP_ESCALATE = 3         # times carried before a row demands a decision
LEDGER_KEEP_DAYS = 21     # how long a cleared item stays in slips.json
SOURCE_ORDER = ("Notion", "Calendar", "Gmail")

# Y2K-cute palette (2026-08-11, per Ari — replaced the old plum-foil dark
# tones). Saturated "jelly bean" hues, not washed pastels: the page background
# carries the pastel cotton-candy wash, these are the functional accents and
# need to hold their own as TEXT on a white/pastel card, so they're deepened
# just enough to clear normal contrast while staying unmistakably candy.
AREA_COLOR = {
    "School": "#0ea5e9", "Pre-Med": "#8b5cf6", "Trading": "#059669",
    "Health": "#db2777", "Personal": "#ea580c", "Admin": "#6b5b95",
    "Interest": "#b45309",
}
PRIO_COLOR = {"High": "#e11d48", "Medium": "#f59e0b", "Low": "#8b7ba8"}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def parse_day(s):
    """Parse the board's own date string ("Sunday, July 26, 2026")."""
    try:
        return datetime.strptime(s or "", "%A, %B %d, %Y")
    except Exception:
        return None


def slip_key(t):
    """Stable identity for a carried item: its Notion page id when it has one,
    otherwise a hash of its text."""
    nid = t.get("notionId")
    if nid:
        return "nid:" + nid
    return "txt:" + hashlib.md5((t.get("text") or "").encode("utf-8")).hexdigest()[:12]


def update_ledger(d, day):
    """Track how many distinct board-days each carried item has survived.

    Lives here, not in the morning prompt, so the count is arithmetic rather
    than a judgement call — and so rebuilding the same day never inflates it.
    Returns (ledger, slips) where slips maps key -> times carried.
    """
    led = load(LEDGER, {})
    if not isinstance(led, dict):
        led = {}
    seen = set()
    for t in d.get("carriedOver", []):
        k = slip_key(t)
        seen.add(k)
        e = led.get(k)
        if e is None:
            led[k] = {"first": day, "last": day, "count": 1,
                      "text": t.get("text"), "area": t.get("area")}
        else:
            if e.get("last") != day:          # idempotent across same-day rebuilds
                e["count"] = int(e.get("count", 1)) + 1
                e["last"] = day
            e.pop("cleared", None)            # it came back
            e["text"] = t.get("text") or e.get("text")
            e["area"] = t.get("area") or e.get("area")
    # Anything no longer carried has left the board. Record when so the Sunday
    # rollup can count it — we know it cleared, not whether he finished it.
    for k, e in led.items():
        if k not in seen and not e.get("cleared"):
            e["cleared"] = day

    today = parse_day(day)
    if today:
        for k in [k for k, e in led.items()
                  if parse_day(e.get("cleared") or "")
                  and (today - parse_day(e["cleared"])).days > LEDGER_KEEP_DAYS]:
            del led[k]

    return led, dict((k, int(e.get("count", 1))) for k, e in led.items())


def weekly_rollup(led, day):
    """Sunday-only: how the board actually moved this week, from the ledger."""
    today = parse_day(day)
    if not today:
        return []
    cleared = [e for e in led.values()
               if parse_day(e.get("cleared") or "")
               and 0 <= (today - parse_day(e["cleared"])).days <= 7]
    still = [e for e in led.values() if not e.get("cleared")]

    rows = []
    rows.append(("%d item%s cleared off the board this week"
                 % (len(cleared), "" if len(cleared) == 1 else "s"),
                 "left the carried-over lane — cleared, not necessarily celebrated"))
    if still:
        worst = max(still, key=lambda e: int(e.get("count", 1)))
        rows.append(("%d still carrying" % len(still),
                     "longest: “%s” — %d× since %s"
                     % ((worst.get("text") or "")[:70], int(worst.get("count", 1)),
                        worst.get("first", "?"))))
        by_area = {}
        for e in still:
            by_area[e.get("area") or "Unfiled"] = by_area.get(e.get("area") or "Unfiled", 0) + 1
        area, n = max(by_area.items(), key=lambda kv: kv[1])
        if n > 1:
            rows.append(("%s is where things stick" % area,
                         "%d of the %d open items" % (n, len(still))))
    else:
        rows.append(("Nothing is carrying", "the board is genuinely clear"))
    return rows


def visible_interests(interests, d, date_str):
    """Rotate the Exploration lane so it stays short without burying anything.
    Retired items (their Notion task is Done) drop out entirely."""
    items = [t for t in (list(interests) + list(d.get("exploration", [])))
             if not t.get("retired")]
    if len(items) <= EXPL_SHOWN:
        return items, 0
    offset = (parse_day(date_str) or datetime.now()).toordinal() % len(items)
    return ([items[(offset + i) % len(items)] for i in range(EXPL_SHOWN)],
            len(items) - EXPL_SHOWN)


def sync_stamp(d):
    """Per-source sync line. One all-or-nothing stamp went dark whenever a
    single connector hiccuped, hiding that the other two were fine."""
    src = d.get("sources")
    if not isinstance(src, dict) or not src:
        v = d.get("verified", "")
        return ('<br><span class="ver">%s</span>' % esc(v)) if v else ""
    names = ([n for n in SOURCE_ORDER if n in src]
             + [n for n in src if n not in SOURCE_ORDER])
    parts = ['<span class="%s">%s %s</span>'
             % ("ver" if str(src[n]).lower() == "ok" else "verwarn",
                "✓" if str(src[n]).lower() == "ok" else "⚠", esc(n))
             for n in names]
    return "<br>" + " · ".join(parts)


def chip(text, color):
    return ('<span class="chip" style="color:%s;border-color:%s33;background:%s14">%s</span>'
            % (color, color, color, esc(text)))


def cal_attr(cal):
    """A timed commitment that is NOT yet on Google Calendar rides along as
    base64'd JSON in data-cal; the row then renders a "+ Cal" button that
    creates the event (see SCRIPT). Base64 because the payload carries quotes,
    emoji and URLs, and HTML-escaping that into an attribute is a footgun.

    Presence of `cal` is the assertion "this is real and your calendar doesn't
    know about it" — the board never auto-writes, it only offers the tap."""
    if not cal:
        return ""
    raw = json.dumps(cal, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return ' data-cal="%s"' % base64.b64encode(raw).decode("ascii")


CALBTN = '<button class="calbtn" type="button">+ Cal</button>'


def task_row(text, prio=None, area=None, source=None, meta=None, scope="",
             nid=None, cal=None):
    left = PRIO_COLOR.get(prio, "#d9c6f2")
    chips = ""
    if area:
        chips += chip(area, AREA_COLOR.get(area, "#7c6f9c"))
    if source:
        chips += chip(source, "#7c6f9c")
    metahtml = ('<div class="meta">%s</div>' % esc(meta)) if meta else ""
    key = hashlib.md5(("%s|%s" % (scope, text)).encode("utf-8")).hexdigest()[:10]
    # Rows backed by a Command Center page carry data-nid; checking them writes
    # Status=Done straight to Notion (see SCRIPT). Others toggle locally only.
    nidattr = (' data-nid="%s"' % esc(nid)) if nid else ""
    return (
        '<div class="row" data-k="%s"%s%s style="border-left-color:%s">'
        '<div class="box"></div>'
        '<div class="rowmain"><div class="rowtext">%s</div>%s'
        '<div class="chips">%s%s</div></div></div>'
        % (key, nidattr, cal_attr(cal), left, esc(text), metahtml, chips,
           CALBTN if cal else "")
    )


def top_row(rank, text, why, area, nid=None, cal=None):
    chip_html = chip(area, AREA_COLOR.get(area, "#7c6f9c")) if area else ""
    why_html = ('<div class="meta">%s</div>' % esc(why)) if why else ""
    key = hashlib.md5(("top|%s" % text).encode("utf-8")).hexdigest()[:10]
    # A Top 5 entry that mirrors a Command Center row carries its page id too,
    # so the lane Ari reads first is checkable like every other lane.
    nidattr = (' data-nid="%s"' % esc(nid)) if nid else ""
    # data-slot identifies this row's POSITION (0-based), independent of its
    # content. When the row is checked off, SCRIPT's auto-refill repaints this
    # same element in place from topBacklog — the slot stays, the item changes.
    return (
        '<div class="row toprow" data-k="%s" data-slot="%d"%s%s style="border-left-color:#ff5eb8">'
        '<div class="topnum">%d</div>'
        '<div class="box"></div>'
        '<div class="rowmain"><div class="rowtext">%s</div>%s'
        '<div class="chips">%s%s</div></div></div>'
        % (key, rank - 1, nidattr, cal_attr(cal), rank, esc(text), why_html, chip_html,
           CALBTN if cal else "")
    )


def plan_row(time_s, text, area, why=None, fixed=False, cal=None):
    """One block in the day's shape. `fixed` blocks are real calendar
    commitments (immovable); the rest are the suggested shape around them.

    A block carrying `cal` is a hard commitment your calendar has NOT got —
    rendered dashed rather than solid, because claiming it's locked in when
    nothing would ever fire a reminder is exactly the lie that let the Jul 28
    Zoom session slip past. `fixed` and `cal` are mutually exclusive; verify()
    fails the build if a block claims both."""
    chip_html = chip(area, AREA_COLOR.get(area, "#7c6f9c")) if area else ""
    why_html = ('<div class="meta">%s</div>' % esc(why)) if why else ""
    key = hashlib.md5(("plan|%s|%s" % (time_s, text)).encode("utf-8")).hexdigest()[:10]
    cls = " fixedblock" if fixed else (" unscheduled" if cal else "")
    return (
        '<div class="row planrow%s" data-k="%s"%s>'
        '<div class="plantime">%s</div>'
        '<div class="box"></div>'
        '<div class="rowmain"><div class="rowtext">%s</div>%s'
        '<div class="chips">%s%s</div></div></div>'
        % (cls, key, cal_attr(cal), esc(time_s),
           esc(text), why_html, chip_html, CALBTN if cal else "")
    )


FLAG_COLOR = {"conflict": "#e11d48", "watch": "#f59e0b", "info": "#0ea5e9"}


def flag_row(text, severity, sources):
    color = FLAG_COLOR.get(severity, "#7c6f9c")
    label = {"conflict": "conflict", "watch": "watch", "info": "fyi"}.get(severity, severity)
    src = ('<div class="meta">%s</div>' % esc(sources)) if sources else ""
    return (
        '<div class="flag" style="border-left-color:%s">'
        '<span class="fdot" style="background:%s;box-shadow:0 0 8px %s"></span>'
        '<div class="rowmain"><div class="rowtext">%s</div>%s</div>'
        '<span class="chip" style="color:%s;border-color:%s33;background:%s14">%s</span></div>'
        % (color, color, color, esc(text), src, color, color, color, label)
    )


def rollup_row(text, note=None):
    note_html = ('<div class="meta">%s</div>' % esc(note)) if note else ""
    return ('<div class="flag" style="border-left-color:#059669">'
            '<span class="fdot" style="background:#059669;box-shadow:0 0 8px #059669"></span>'
            '<div class="rowmain"><div class="rowtext">%s</div>%s</div></div>'
            % (esc(text), note_html))


def hub_group(g):
    items = ""
    for i in g.get("items", []):
        note = ('<span class="hubnote">%s</span>' % esc(i.get("note"))) if i.get("note") else ""
        items += ('<a class="hubitem" href="%s" target="_blank" rel="noopener">'
                  '<span class="hubtitle">%s</span>%s</a>'
                  % (esc(i.get("url")), esc(i.get("title")), note))
    return ('<div class="hubgroup"><div class="hubhead">%s</div>%s</div>'
            % (esc(g.get("group")), items))


def lane(title, subtitle, rows_html, accent="#0ea5e9", empty="Nothing here — clear.",
         fold=False):
    """A board lane. `fold` makes it a <details> that the script collapses on
    phones, where a long reference lane buries the morning-critical top of the
    board. It ships `open`, so if the script never runs the lane shows in full
    rather than hiding itself."""
    body = rows_html if rows_html else ('<div class="empty">%s</div>' % esc(empty))
    sub = ('<span class="lanesub">%s</span>' % esc(subtitle)) if subtitle else ""
    head = ('<span class="ldot"></span><h2>%s</h2>%s<span class="lline"></span>'
            % (esc(title), sub))
    if fold:
        return (
            '<section class="lane">'
            '<details class="lanefold" data-foldnarrow open>'
            '<summary class="lanehead" style="--accent:%s">%s</summary>'
            '<div class="lanebody">%s</div></details></section>'
            % (accent, head, body)
        )
    return (
        '<section class="lane">'
        '<div class="lanehead" style="--accent:%s">%s</div>'
        '<div class="lanebody">%s</div></section>'
        % (accent, head, body)
    )


def count_box(value, label, color=None):
    bstyle = (' style="color:%s"' % color) if color else ""
    cstyle = (' style="border-color:%s66"' % color) if color else ""
    idattr = ' id="progVal"' if label == "Checked off" else ""
    return ('<div class="count"%s><b%s%s>%s</b><span>%s</span></div>'
            % (cstyle, idattr, bstyle, esc(value), esc(label)))


def now_module(d):
    """The RIGHT NOW module: a single standing focus item, pinned above
    everything else. Unlike every other row on the board, it does NOT reset on
    tomorrow's rebuild and it is NOT checked off by clicking — it only changes
    when Ari tells Claude in chat that it's done, and Claude writes the next
    nowTask into docket_data.json and republishes. No data-nid/data-k here on
    purpose: this module makes no Notion write of its own, so it can't drift
    out of sync with verify()'s notionId accounting."""
    now = d.get("nowTask")
    if not now or not now.get("text"):
        return (
            '<section class="lane nowlane nowidle">'
            '<div class="lanehead" style="--accent:#9c86bd"><span class="ldot"></span>'
            '<h2>RIGHT NOW</h2><span class="lanesub">nothing in focus</span>'
            '<span class="lline"></span></div>'
            '<div class="nowbody"><div class="nowtext nowempty">'
            'Ask Claude to set your next focus.</div></div></section>'
        )
    why_html = ('<div class="nowwhy">%s</div>' % esc(now.get("why"))) if now.get("why") else ""
    chip_html = chip(now.get("area"), AREA_COLOR.get(now.get("area"), "#7c6f9c")) if now.get("area") else ""
    since_html = ('<div class="nowsince">In focus since %s</div>' % esc(now.get("since"))) if now.get("since") else ""
    return (
        '<section class="lane nowlane">'
        '<div class="lanehead" style="--accent:#ff5eb8"><span class="ldot pulse"></span>'
        '<h2>RIGHT NOW</h2><span class="lanesub">tell Claude when you&#x27;re done \\u2014 this stays until you do</span>'
        '<span class="lline"></span></div>'
        '<div class="nowbody"><div class="nowtext">%s</div>%s'
        '<div class="nowchips">%s</div>%s</div></section>'
        % (esc(now.get("text")), why_html, chip_html, since_html)
    )


def render_inner(d, interests, slips=None, ledger=None):
    slips = slips or {}
    date_str = d.get("date") or datetime.now().strftime("%A, %B %d, %Y")
    # Stamped here, at render time — never read from docket_data.json. A
    # hand-written timestamp drifts from when the board was actually built.
    generated = datetime.now().isoformat(timespec="seconds")
    status = d.get("statusLine", "")
    trading = d.get("trading", "")

    carry = d.get("carriedOver", [])
    carry_rows = ""
    escalated = 0
    for t in carry:
        n = slips.get(slip_key(t), 1)
        when = t.get("when") or ""
        prio = t.get("priority")
        if n >= 2:
            when = (when + " · " if when else "") + "slipped %d×" % n
        if n >= SLIP_ESCALATE:
            # Past this point it isn't drifting, it's stuck. Force the red rail
            # and name the decision — a slip that never escalates just accretes.
            when += " — decide today: reschedule it or drop it"
            prio = "High"
            escalated += 1
        carry_rows += task_row(t.get("text"), prio, t.get("area"),
                               t.get("source"), when, scope="carry",
                               nid=t.get("notionId"), cal=t.get("cal"))

    due_rows = "".join(task_row(t.get("text"), t.get("priority"), t.get("area"),
                                t.get("source"), t.get("when"), scope="due",
                                nid=t.get("notionId"), cal=t.get("cal"))
                       for t in d.get("dueToday", []))

    sched_rows = "".join(task_row(e.get("text"), None, e.get("area"), None, e.get("time"), scope="sched")
                         for e in d.get("schedule", []))

    mail_rows = ""
    for m in d.get("email", []):
        who = m.get("who")
        meta = (who + " · " + m.get("action", "")) if who else m.get("action", "")
        mail_rows += task_row(m.get("subject"), m.get("priority"), None, "email", meta, scope="mail")

    week_rows = "".join(task_row(t.get("text"), t.get("priority"), t.get("area"),
                                 t.get("source"), t.get("due"), scope="week",
                                 nid=t.get("notionId"), cal=t.get("cal"))
                        for t in d.get("thisWeek", []))

    top5 = d.get("topPriorities", [])
    top_rows = "".join(top_row(i + 1, t.get("text"), t.get("why"), t.get("area"),
                               t.get("notionId"), cal=t.get("cal"))
                        for i, t in enumerate(top5))
    # The runner-up pool: ranked candidates that didn't make today's Top 5.
    # Never rendered as rows up front — SCRIPT promotes one into a slot's place
    # each time that slot is checked off, so "Top 5" stays full (or shrinks
    # honestly once the pool runs dry) across the whole day, not just at 6 AM.
    backlog = [{"text": t.get("text"), "why": t.get("why"), "area": t.get("area"),
                "notionId": t.get("notionId"), "cal": t.get("cal"),
                "areaColor": AREA_COLOR.get(t.get("area"), "#7c6f9c")}
               for t in d.get("topBacklog", [])]
    backlog_json = json.dumps(backlog, ensure_ascii=False).replace("</", "<\\/")
    top_section = ""
    if top_rows:
        top_section = (
            '<section class="lane top5">'
            '<div class="lanehead" style="--accent:#ff5eb8"><span class="ldot"></span>'
            '<h2>TOP 5 TODAY</h2><span class="lanesub">what matters most, judged across everything</span>'
            '<span class="lline"></span></div>'
            '<div class="lanebody">%s</div></section>'
            '<script type="application/json" id="topBacklogData">%s</script>'
            % (top_rows, backlog_json)
        )

    plan_items = d.get("plan", [])
    plan_rows = "".join(plan_row(p.get("time"), p.get("text"), p.get("area"),
                                 p.get("why"), p.get("fixed"), cal=p.get("cal"))
                        for p in plan_items)
    plan_lane = ""
    if plan_rows:
        plan_lane = lane("TODAY'S PLAN",
                         "the shape of your day — highlighted blocks are real commitments",
                         plan_rows, accent="#8b5cf6")

    expl, expl_more = visible_interests(interests, d, date_str)
    expl_rows = "".join(task_row(t.get("text"), None, "Interest", None, t.get("note"), scope="expl",
                                 nid=t.get("notionId")) for t in expl)
    expl_sub = "your interests, alive"
    if expl_more:
        expl_sub += " · %d of %d today, the rest rotate in" % (len(expl), len(expl) + expl_more)

    flags = d.get("crosscheck", [])
    flag_rows = "".join(flag_row(f.get("text"), f.get("severity"), f.get("sources"))
                        for f in flags)
    flags_lane = ""
    if flag_rows:
        flags_lane = lane("CROSS-CHECK", "where your connectors disagree — resolved daily",
                          flag_rows, accent="#fb7185")

    hub_groups = d.get("notionHub", [])
    hub_html = ""
    if hub_groups:
        # The single biggest lane on the board (~21% of page height on a phone),
        # and pure navigation — folded so it stops burying everything above it.
        hub_html = (
            '<section class="lane hublane">'
            '<details class="lanefold" data-foldnarrow open>'
            '<summary class="lanehead" style="--accent:#8b5cf6"><span class="ldot"></span>'
            '<h2>NOTION HUB</h2><span class="lanesub">%d links across your whole workspace</span>'
            '<span class="lline"></span></summary>'
            '<div class="hub">%s</div></details></section>'
            % (sum(len(g.get("items", [])) for g in hub_groups),
               "".join(hub_group(g) for g in hub_groups))
        )

    counts = ""
    if carry:
        counts += count_box(len(carry), "Carried over", "#f97316")
    if escalated:
        counts += count_box(escalated, "Need a decision", "#e11d48")
    counts += count_box(len(d.get("dueToday", [])), "Due today")
    counts += count_box(len(d.get("email", [])), "Inbox actions")
    counts += count_box(len(d.get("thisWeek", [])), "This week")
    if flags:
        counts += count_box(len(flags), "Flags", "#fb7185")
    counts += count_box(len(expl) + expl_more, "Exploration")
    counts += count_box("0 / 0", "Checked off", "#059669")

    hero = ""
    if carry_rows:
        hero += lane("CARRIED OVER — unfinished from yesterday", "close these out first",
                     carry_rows, accent="#f97316")
    hero += lane("DUE TODAY / OVERDUE", "hit these first", due_rows,
                 accent="#e11d48", empty="No hard deadlines today. Breathe, then build.")

    grid = ""
    grid += lane("TODAY'S SCHEDULE", "from your calendar", sched_rows,
                 accent="#0ea5e9", empty="Open day — anchor it: gym → deep work → wind down.")
    grid += lane("NEEDS A REPLY / ACTION", "from your inbox", mail_rows,
                 accent="#eab308", empty="Inbox is clear. 📭")
    grid += lane("THIS WEEK", "coming up", week_rows,
                 accent="#8b5cf6", empty="Nothing scheduled this week yet.")
    grid += lane("EXPLORATION", expl_sub, expl_rows,
                 accent="#059669", empty="Add an interest and it shows up here.")

    # Sundays only — the board resets daily, so this is the one place the week
    # accumulates into something he can learn from.
    rollup_html = ""
    if date_str.startswith("Sunday") and ledger:
        rollup_html = lane("WEEK IN REVIEW", "how the board actually moved",
                           "".join(rollup_row(a, b)
                                   for a, b in weekly_rollup(ledger, date_str)),
                           accent="#059669", fold=True)

    trading_html = ('<div class="trading">📈 %s</div>' % esc(trading)) if trading else ""

    gen_disp = esc(generated.replace("T", " "))
    # Per-source, so one flaky connector no longer blanks the whole stamp —
    # green means that source really was read this run, amber means it wasn't.
    ver_html = sync_stamp(d)
    now_html = now_module(d)
    inner = (
        '<div class="wrap">'
        '%s'
        '<div class="top"><div>'
        '<div class="brand">The Docket</div>'
        '<h1 class="date">%s</h1>'
        '<div class="status">%s</div>%s</div>'
        '<div class="gen">updated<br>%s%s</div></div>'
        '<div class="counts">%s</div>'
        '<div class="mcpbanner" id="mcpbanner"></div>'
        '<div class="top5wrap">%s</div>'
        '%s'
        '<div class="hero">%s</div>'
        '%s'
        '<div class="grid">%s</div>'
        '%s%s'
        '<div class="foot">Your daily hub — rebuilt every morning from Google Calendar · Gmail · your whole Notion workspace '
        '(Command Center, Financial Tracker, Instratix, IHSS, every dashboard &amp; plan) · interests.json, cross-checked for conflicts. '
        'Click any row to check it off — green-boxed rows sync straight to Notion.</div>'
        '</div>'
        % (now_html, esc(date_str), esc(status), trading_html, gen_disp, ver_html, counts,
           top_section, plan_lane, hero, flags_lane, grid, rollup_html, hub_html)
    )
    return date_str, inner


STYLE = """
/* ============================================================
   Y2K CUTE — 2026-08-11, per Ari: bright cotton-candy bubble UI,
   NOT the old plum-foil dark theme. This is now the standing
   aesthetic direction for The Docket — keep it whenever this file
   is touched, don't drift back to dark/plain purple.
   Light is the primary world (Ari: dark UIs hurt his focus); dark
   mode gets its own neon-rave pass rather than being generic.
   ============================================================ */
.dk-scope{
  /* ---- tokens: light (default) ---- */
  --ink:#3b2159; --ink-dim:#6b4f8e; --ink-faint:#9c86bd;
  --panel:rgba(255,255,255,.86); --panel-border:#ffcdec;
  --panel-fade:rgba(255,255,255,.7); --panel-soft:rgba(255,255,255,.55);
  --hairline:rgba(139,92,246,.16);
  --pink:#ff5eb8; --pink-deep:#db2777; --lilac:#8b5cf6; --sky:#0ea5e9;
  --ok:#059669; --warn:#f59e0b; --bad:#e11d48;
  --brand-a:#ff6ec7; --brand-b:#8b5cf6; --brand-c:#22c3ff;
  --idle-edge:#ecd9ff; --chip-fallback:#7c6f9c;
  --check-glyph:#fff;
  --f-display:'Segoe Print','Comic Sans MS','Chalkboard SE',cursive;
  --f-body:'Trebuchet MS','Segoe UI',Verdana,sans-serif;
  --f-mono:'Cascadia Code',ui-monospace,Consolas,'SFMono-Regular',monospace;
  font-family:var(--f-body);color:var(--ink);
  background:
    radial-gradient(3px 3px at 9% 14%,#ffd6f0,transparent 60%),
    radial-gradient(2.5px 2.5px at 23% 6%,#c9e8ff,transparent 60%),
    radial-gradient(3px 3px at 88% 10%,#ffe2b8,transparent 60%),
    radial-gradient(2px 2px at 68% 22%,#d9c6ff,transparent 60%),
    radial-gradient(2.5px 2.5px at 4% 62%,#ffd6f0,transparent 60%),
    radial-gradient(2px 2px at 95% 58%,#c9e8ff,transparent 60%),
    radial-gradient(3px 3px at 78% 88%,#ffe2b8,transparent 60%),
    radial-gradient(2px 2px at 12% 92%,#d9c6ff,transparent 60%),
    radial-gradient(1000px 560px at 6% -10%,#fff1fb 0%,transparent 60%),
    radial-gradient(900px 520px at 104% -4%,#eaf6ff 0%,transparent 58%),
    radial-gradient(760px 520px at 50% 118%,#fff4e3 0%,transparent 60%),
    linear-gradient(165deg,#fffafd 0%,#f6f1ff 45%,#eef8ff 100%);
  padding:26px 18px 40px;-webkit-font-smoothing:antialiased;
}
/* ---- tokens: dark (Y2K neon-rave variant, not generic dark UI) ---- */
@media(prefers-color-scheme:dark){ .dk-scope{
  --ink:#ffe9fa; --ink-dim:#e3bdfb; --ink-faint:#b28fd9;
  --panel:rgba(38,16,58,.74); --panel-border:rgba(255,110,199,.4);
  --panel-fade:rgba(38,16,58,.5); --panel-soft:rgba(60,28,90,.4);
  --hairline:rgba(255,110,199,.22);
  --pink:#ff6ec7; --pink-deep:#ff8fd6; --lilac:#b18cff; --sky:#5ad1ff;
  --ok:#4fe3b0; --warn:#ffcf6b; --bad:#ff7a90;
  --brand-a:#ff9ee0; --brand-b:#c7a8ff; --brand-c:#7fe3ff;
  --idle-edge:#4a2f70; --chip-fallback:#c6a8ee;
  --check-glyph:#1a0a2e;
  background:
    radial-gradient(2px 2px at 10% 12%,#ffb3e6,transparent 60%),
    radial-gradient(2px 2px at 85% 8%,#9fe8ff,transparent 60%),
    radial-gradient(2px 2px at 70% 30%,#d6b8ff,transparent 60%),
    radial-gradient(2px 2px at 6% 60%,#ffb3e6,transparent 60%),
    radial-gradient(2px 2px at 92% 70%,#9fe8ff,transparent 60%),
    radial-gradient(900px 520px at 85% -8%,rgba(255,110,199,.20),transparent 70%),
    radial-gradient(760px 480px at 0% 105%,rgba(120,220,255,.14),transparent 70%),
    linear-gradient(175deg,#1c0d33 0%,#150a28 55%,#0d0619 100%);
}}
:root[data-theme="dark"] .dk-scope{
  --ink:#ffe9fa; --ink-dim:#e3bdfb; --ink-faint:#b28fd9;
  --panel:rgba(38,16,58,.74); --panel-border:rgba(255,110,199,.4);
  --panel-fade:rgba(38,16,58,.5); --panel-soft:rgba(60,28,90,.4);
  --hairline:rgba(255,110,199,.22);
  --pink:#ff6ec7; --pink-deep:#ff8fd6; --lilac:#b18cff; --sky:#5ad1ff;
  --ok:#4fe3b0; --warn:#ffcf6b; --bad:#ff7a90;
  --brand-a:#ff9ee0; --brand-b:#c7a8ff; --brand-c:#7fe3ff;
  --idle-edge:#4a2f70; --chip-fallback:#c6a8ee;
  --check-glyph:#1a0a2e;
  background:
    radial-gradient(2px 2px at 10% 12%,#ffb3e6,transparent 60%),
    radial-gradient(2px 2px at 85% 8%,#9fe8ff,transparent 60%),
    radial-gradient(2px 2px at 70% 30%,#d6b8ff,transparent 60%),
    radial-gradient(2px 2px at 6% 60%,#ffb3e6,transparent 60%),
    radial-gradient(2px 2px at 92% 70%,#9fe8ff,transparent 60%),
    radial-gradient(900px 520px at 85% -8%,rgba(255,110,199,.20),transparent 70%),
    radial-gradient(760px 480px at 0% 105%,rgba(120,220,255,.14),transparent 70%),
    linear-gradient(175deg,#1c0d33 0%,#150a28 55%,#0d0619 100%);
}
:root[data-theme="light"] .dk-scope{
  --ink:#3b2159; --ink-dim:#6b4f8e; --ink-faint:#9c86bd;
  --panel:rgba(255,255,255,.86); --panel-border:#ffcdec;
  --panel-fade:rgba(255,255,255,.7); --panel-soft:rgba(255,255,255,.55);
  --hairline:rgba(139,92,246,.16);
  --pink:#ff5eb8; --pink-deep:#db2777; --lilac:#8b5cf6; --sky:#0ea5e9;
  --ok:#059669; --warn:#f59e0b; --bad:#e11d48;
  --brand-a:#ff6ec7; --brand-b:#8b5cf6; --brand-c:#22c3ff;
  --idle-edge:#ecd9ff; --chip-fallback:#7c6f9c; --check-glyph:#fff;
  background:
    radial-gradient(1000px 560px at 6% -10%,#fff1fb 0%,transparent 60%),
    radial-gradient(900px 520px at 104% -4%,#eaf6ff 0%,transparent 58%),
    radial-gradient(760px 520px at 50% 118%,#fff4e3 0%,transparent 60%),
    linear-gradient(165deg,#fffafd 0%,#f6f1ff 45%,#eef8ff 100%);
}
.dk-scope *{box-sizing:border-box}
.dk-scope .wrap{max-width:1080px;margin:0 auto}
.dk-scope .top{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px;margin-bottom:6px}
.dk-scope .brand{font-family:var(--f-display);font-size:15px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;
  background:linear-gradient(90deg,var(--brand-a),var(--brand-b) 55%,var(--brand-c));-webkit-background-clip:text;background-clip:text;color:transparent}
.dk-scope h1.date{font-family:var(--f-display);margin:2px 0 0;font-size:32px;font-weight:700;letter-spacing:0;color:var(--pink-deep);text-wrap:balance;
  text-shadow:1px 1px 0 rgba(255,255,255,.7),0 0 22px rgba(255,94,184,.28)}
.dk-scope .status{color:var(--ink-dim);font-size:14px;margin-top:5px;max-width:660px;line-height:1.5}
.dk-scope .trading{color:var(--ok);font-size:12.5px;margin-top:8px;font-weight:700;letter-spacing:.01em}
.dk-scope .gen{font-family:var(--f-mono);font-size:11px;color:var(--ink-faint);text-align:right}
.dk-scope .ver{color:var(--ok);letter-spacing:.02em;font-weight:600}
.dk-scope .verwarn{color:var(--warn);letter-spacing:.02em;font-weight:600}
.dk-scope .counts{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 8px}
.dk-scope .count{background:var(--panel);border:2px solid var(--panel-border);border-radius:16px;padding:9px 14px;min-width:92px;box-shadow:0 4px 10px -6px rgba(139,92,246,.35)}
.dk-scope .count b{display:block;font-family:var(--f-mono);font-size:22px;color:var(--ink);font-variant-numeric:tabular-nums}
.dk-scope .count span{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-faint);font-weight:700}
.dk-scope .lane{position:relative;background:linear-gradient(180deg,var(--panel),var(--panel-fade));border:2px solid var(--panel-border);border-radius:24px;padding:16px 18px;margin-bottom:16px;backdrop-filter:blur(6px);
  box-shadow:0 1px 0 rgba(255,255,255,.8) inset,0 10px 22px -14px rgba(139,92,246,.35)}
.dk-scope .lane::before,.dk-scope .lane::after{content:"\\2726";position:absolute;pointer-events:none;color:var(--pink);opacity:.8;text-shadow:0 0 8px rgba(255,94,184,.45)}
.dk-scope .lane::before{top:-10px;left:16px;font-size:15px}
.dk-scope .lane::after{bottom:-10px;right:16px;font-size:11px;color:var(--sky);text-shadow:0 0 8px rgba(14,165,233,.4)}
.dk-scope .lanehead{display:flex;align-items:center;gap:9px;margin-bottom:12px}
.dk-scope .lanehead h2{margin:0;font-size:12.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--pink-deep);font-weight:800}
.dk-scope .ldot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
.dk-scope .lanesub{font-size:11px;color:var(--ink-faint);letter-spacing:.02em}
.dk-scope .lanefold > summary{cursor:pointer;list-style:none}
.dk-scope .lanefold > summary::-webkit-details-marker{display:none}
.dk-scope .lanefold > summary::after{content:"\\25be";color:var(--ink-faint);font-size:10px;flex:none;margin-left:2px}
.dk-scope .lanefold:not([open]) > summary::after{content:"\\25b8"}
.dk-scope .lanefold:not([open]) > summary{margin-bottom:0}
.dk-scope .lanefold > summary:hover .lanesub{color:var(--ink-dim)}
.dk-scope .lline{flex:1;height:1px;background:linear-gradient(90deg,var(--hairline),transparent)}
.dk-scope .grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}
@media(max-width:760px){.dk-scope .grid{grid-template-columns:1fr}}
.dk-scope .row{display:flex;gap:11px;align-items:flex-start;padding:9px 6px;border-left:3px solid var(--idle-edge);padding-left:11px;border-bottom:1px solid var(--hairline);cursor:pointer;transition:opacity .15s,background .15s,transform .1s;border-radius:0 12px 12px 0}
.dk-scope .row:last-child{border-bottom:none}
.dk-scope .row:hover{background:rgba(255,94,184,.08)}
.dk-scope .row:active{transform:scale(.995)}
.dk-scope .box{width:17px;height:17px;border:2px solid var(--idle-edge);border-radius:50%;margin-top:2px;flex:none;position:relative;transition:.15s;background:linear-gradient(180deg,#fff,#fff0f9);box-shadow:0 1px 0 rgba(255,255,255,.9) inset}
.dk-scope .row.done .box{background:linear-gradient(160deg,#ff9bd8,var(--pink));border-color:var(--pink)}
.dk-scope .row.done .box::after{content:"\\2665";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:9px;color:var(--check-glyph);line-height:1}
.dk-scope .row.done .rowtext{text-decoration:line-through;color:var(--ink-faint)}
.dk-scope .row.done{opacity:.62}
.dk-scope .rowmain{flex:1;min-width:0}
.dk-scope .rowtext{font-size:14px;line-height:1.4;font-weight:500}
.dk-scope .meta{font-size:11.5px;color:var(--ink-dim);margin-top:2px}
.dk-scope .chips{margin-top:5px;display:flex;gap:6px;flex-wrap:wrap}
.dk-scope .chip{font-size:10px;letter-spacing:.05em;text-transform:uppercase;border:1.5px solid;border-radius:20px;padding:2px 9px;font-weight:700}
.dk-scope .empty{color:var(--ink-faint);font-size:13px;padding:6px 2px}
.dk-scope .foot{margin-top:22px;color:var(--ink-faint);font-size:11px;text-align:center;line-height:1.6}
.dk-scope .hero .lane{border-color:rgba(225,29,72,.35)}
.dk-scope .top5{border-color:rgba(255,94,184,.55);
  background:linear-gradient(180deg,rgba(255,94,184,.14),rgba(139,92,246,.08)),linear-gradient(180deg,var(--panel),var(--panel-fade));
  margin-bottom:16px}
.dk-scope .topnum{width:24px;height:24px;border-radius:50%;background:linear-gradient(140deg,var(--pink),var(--lilac));color:#fff;font-family:var(--f-display);font-weight:700;font-size:13px;display:flex;align-items:center;justify-content:center;flex:none;margin-top:1px;box-shadow:0 1px 0 rgba(255,255,255,.6) inset,0 3px 8px -3px rgba(219,39,119,.55)}
.dk-scope .top5 .rowtext{font-size:15.5px;font-weight:700;color:var(--ink)}
.dk-scope .top5 .row.done .topnum{opacity:.5}
.dk-scope .planrow{border-left-color:var(--idle-edge)}
.dk-scope .planrow.fixedblock{border-left-color:var(--lilac);background:rgba(139,92,246,.09)}
.dk-scope .plantime{font-family:var(--f-mono);font-size:11px;color:var(--ink-faint);min-width:88px;flex:none;padding-top:3px;line-height:1.3;font-variant-numeric:tabular-nums}
.dk-scope .planrow.fixedblock .plantime{color:var(--lilac);font-weight:700}
@media(max-width:560px){.dk-scope .plantime{min-width:68px;font-size:10px}}
.dk-scope .mcpbanner{display:none;background:#fff4de;border:1.5px solid #ffcf8a;color:#92400e;font-size:12px;line-height:1.45;padding:9px 13px;border-radius:14px;margin:10px 0 4px}
/* A hard commitment the calendar doesn't know about: dashed, never solid. */
.dk-scope .planrow.unscheduled .plantime{color:var(--lilac);font-weight:700;opacity:.75}
.dk-scope .row[data-cal]{border-left-style:dashed}
.dk-scope .calbtn{font:inherit;font-family:var(--f-body);font-size:10px;font-weight:800;letter-spacing:.03em;text-transform:uppercase;color:#0284c7;background:linear-gradient(180deg,#ecfbff,#d3f2ff);border:1.5px solid rgba(2,132,199,.4);border-radius:999px;padding:3px 10px;cursor:pointer;line-height:1.5;box-shadow:0 1px 0 rgba(255,255,255,.8) inset}
.dk-scope .calbtn:hover{background:linear-gradient(180deg,#e0f8ff,#bdeeff)}
.dk-scope .calbtn[disabled]{cursor:default;opacity:.75}
.dk-scope .calbtn.ok{color:var(--ok);border-color:rgba(5,150,105,.4);background:linear-gradient(180deg,#eafff6,#d3f7e8)}
.dk-scope .calbtn.err{color:var(--bad);border-color:rgba(225,29,72,.4);background:linear-gradient(180deg,#fff0f3,#ffdbe4)}
.dk-scope .row[data-nid] .box{border-color:rgba(5,150,105,.55)}
.dk-scope .row[data-nid] .box::before{content:"";position:absolute;inset:-7px;border-radius:50%}
.dk-scope .row.pending{opacity:.7;pointer-events:none}
.dk-scope .synced{font-size:11px;margin-top:4px;letter-spacing:.02em;display:flex;align-items:center;gap:5px;font-weight:600}
.dk-scope .synced[data-kind="ok"]{color:var(--ok)}
.dk-scope .synced[data-kind="pending"]{color:var(--ink-dim)}
.dk-scope .synced[data-kind="err"]{color:var(--bad)}
.dk-scope .synced::before{content:"";width:5px;height:5px;border-radius:50%;background:currentColor;flex:none}
.dk-scope .flag{display:flex;gap:10px;align-items:flex-start;padding:9px 8px 9px 11px;border-left:3px solid var(--idle-edge);border-bottom:1px solid var(--hairline);border-radius:0 12px 12px 0}
.dk-scope .flag:last-child{border-bottom:none}
.dk-scope .fdot{width:8px;height:8px;border-radius:50%;flex:none;margin-top:5px}
.dk-scope .flag .chip{flex:none;margin-top:2px}
.dk-scope .hublane{border-color:rgba(139,92,246,.4)}
.dk-scope .hub{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
@media(max-width:560px){.dk-scope .hub{grid-template-columns:1fr}}
.dk-scope .hubgroup{background:var(--panel-soft);border:1.5px solid rgba(139,92,246,.22);border-radius:16px;padding:10px 12px}
.dk-scope .hubhead{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--lilac);margin-bottom:7px;font-weight:800}
.dk-scope .hubitem{display:block;padding:4px 7px;margin:0 -4px;border-radius:10px;color:var(--ink);text-decoration:none;font-size:12.5px;line-height:1.35;transition:background .15s}
.dk-scope .hubitem:hover{background:rgba(139,92,246,.14)}
.dk-scope .hubnote{display:block;font-size:10.5px;color:var(--ink-faint);margin-top:1px}
.dk-scope .nowlane{position:relative;border-color:rgba(255,94,184,.6);
  background:linear-gradient(135deg,rgba(255,94,184,.20),rgba(255,187,110,.12) 60%,rgba(139,92,246,.12)),linear-gradient(180deg,var(--panel),var(--panel-fade));
  box-shadow:0 0 0 3px rgba(255,255,255,.4) inset,0 14px 28px -16px rgba(219,39,119,.4);margin-bottom:16px}
.dk-scope .nowlane .lanehead{margin-bottom:10px}
.dk-scope .nowlane .lanehead h2::after{content:" \\2728";font-size:11px}
.dk-scope .ldot.pulse{animation:dkpulse 1.8s ease-in-out infinite}
@keyframes dkpulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.55;transform:scale(1.4)}}
.dk-scope .nowbody{padding:2px 2px 0}
.dk-scope .nowtext{font-family:var(--f-display);font-size:22px;font-weight:700;color:var(--pink-deep);line-height:1.3;text-wrap:balance}
.dk-scope .nowlane.nowidle .nowtext.nowempty{font-family:var(--f-body);font-size:14px;font-weight:500;color:var(--ink-faint)}
.dk-scope .nowwhy{font-size:12.5px;color:var(--ink-dim);margin-top:6px;line-height:1.45}
.dk-scope .nowchips{margin-top:9px;display:flex;gap:6px;flex-wrap:wrap}
.dk-scope .nowsince{font-size:10.5px;color:var(--ink-faint);margin-top:8px;letter-spacing:.02em}
.dk-scope .nowlane.nowidle{background:var(--panel-soft);box-shadow:none}
"""

SCRIPT = """
<script>
(function(){
  var KEY="docketChecks_v1";
  var SERVER="Notion";           // claude.ai connector display name
  var TOOL="notion-update-page"; // upstream tool name
  // The Docket never writes to Calendar on its own — every event is one
  // deliberate tap. CAL_SERVER is the expected display name; the real one is
  // resolved from listTools() at load, so a rename doesn't silently kill the
  // button. CAL_TOOL's argument names were observed live before shipping.
  var CAL_SERVER="Google Calendar";
  var CAL_TOOL="create_event";
  var calServer=null;            // resolved at load; null until then
  var scope=document.querySelector("[data-day]");
  var day=scope?scope.getAttribute("data-day"):"";
  var store={};
  try{store=JSON.parse(localStorage.getItem(KEY)||"{}");}catch(e){store={};}
  if(store.day!==day){store={day:day,done:{},cal:{}};}
  if(!store.done)store.done={};
  if(!store.cal)store.cal={};   // rows whose event this browser already created
  if(typeof store.topNext!=="number")store.topNext=0;  // cursor into topBacklog, shared across slots
  if(!store.topSlot)store.topSlot={};                  // slot index -> backlog index, once promoted
  function save(){try{localStorage.setItem(KEY,JSON.stringify(store));}catch(e){}}

  // window.claude.mcp is present only in a published claude.ai artifact. In the
  // bookmarked local file it's absent — rows then toggle visually only.
  var mcp=(window.claude&&window.claude.mcp)?window.claude.mcp:null;
  var rows=Array.prototype.slice.call(document.querySelectorAll(".row[data-k]"));

  // Reference lanes (Notion Hub, Week in Review) ship expanded and get folded
  // only on a phone, where the hub alone runs ~21% of the page and buries the
  // morning-critical top of the board. Folding is the opt-in direction on
  // purpose: if this never runs, the board shows too much, never too little.
  if(window.matchMedia&&window.matchMedia("(max-width: 760px)").matches){
    Array.prototype.forEach.call(
      document.querySelectorAll("details.lanefold[data-foldnarrow]"),
      function(el){ el.open=false; });
  }

  function progress(){
    var done=rows.filter(function(r){return r.classList.contains("done");}).length;
    var el=document.getElementById("progVal");
    if(el)el.textContent=done+" / "+rows.length;
  }
  function note(r,msg,kind){
    var n=r.querySelector(".synced");
    if(!n){n=document.createElement("div");n.className="synced";r.querySelector(".rowmain").appendChild(n);}
    n.textContent=msg; n.setAttribute("data-kind",kind||"");
  }
  function clearNote(r){var n=r.querySelector(".synced"); if(n)n.parentNode.removeChild(n);}
  function banner(msg){
    var b=document.getElementById("mcpbanner");
    if(b){b.textContent=msg; b.style.display="block";}
  }
  // Each error code has a distinct fix — never collapse them into one message.
  function errMsg(code){
    switch(code){
      case "needs_reauth":         return "Reconnect Notion in claude.ai \\u2192 Settings \\u2192 Connectors, then tap again";
      case "server_not_connected": return "Add Notion in claude.ai \\u2192 Settings \\u2192 Connectors, then tap again";
      case "selection_required":   return "Pick your Notion connector when claude.ai asks, then tap again";
      case "not_in_manifest":
      case "blocked_by_policy":     return "This Docket isn't allowed to update Notion";
      case "server_unavailable":   return "Notion's unreachable right now \\u2014 tap to retry";
      case "tool_error":           return "Notion refused the update \\u2014 tap to retry";
      default:                     return "Couldn't reach Notion \\u2014 tap to retry";
    }
  }

  // One Command Center task can surface in two lanes at once (a Top 5 entry
  // mirroring its Carried Over row). There's only one write, so every copy has
  // to move together or the board contradicts itself.
  function twins(r){
    var nid=r.getAttribute("data-nid");
    if(!nid)return [];
    return rows.filter(function(o){return o!==r&&o.getAttribute("data-nid")===nid;});
  }
  function pending(r,on){
    r.classList.toggle("pending",on);
    twins(r).forEach(function(o){o.classList.toggle("pending",on);});
  }

  function setState(r,k,on){
    r.classList.toggle("done",on);
    if(on)store.done[k]=1; else delete store.done[k];
    twins(r).forEach(function(o){
      var tk=o.getAttribute("data-k");
      o.classList.toggle("done",on);
      if(on)store.done[tk]=1; else delete store.done[tk];
    });
    save(); progress();
  }

  // ---- "+ Cal": put a timed commitment on Google Calendar, one tap ----
  // A calendar write is never automatic here. The morning run only ever
  // ATTACHES the payload (data-cal); creating the event is Ari's gesture, so
  // an unattended run can't invent events out of parsed email.
  function calErr(code){
    switch(code){
      case "needs_reauth":         return "Reconnect Google Calendar in claude.ai \\u2192 Settings \\u2192 Connectors";
      case "server_not_connected": return "Add Google Calendar in claude.ai \\u2192 Settings \\u2192 Connectors";
      case "selection_required":   return "Pick your Google Calendar connector when claude.ai asks";
      case "not_in_manifest":
      case "blocked_by_policy":     return "This Docket isn't allowed to add calendar events";
      case "approval_required":    return "Your org requires approval to add events";
      case "tool_error":           return "Calendar refused the event \\u2014 tap to retry";
      // server_unavailable / upstream_error / cancelled are AMBIGUOUS for a
      // write: the rejection is not proof the event wasn't created. Never
      // auto-retry these; make Ari look first.
      case "server_unavailable":
      case "cancelled":
      default:                     return "Couldn't confirm \\u2014 check your calendar before tapping again";
    }
  }
  function calDone(b){
    b.textContent="\\u2713 On calendar"; b.className="calbtn ok"; b.disabled=true;
  }
  // Wires (or re-wires) a row's "+ Cal" button. Reusable — called once per
  // row at load, and again by paintSlot() when auto-refill hands a Top 5 slot
  // a fresh item that carries its own `cal` payload.
  function wireCalBtn(r){
    var b=r.querySelector(".calbtn");
    if(!b)return;
    b.className="calbtn"; b.disabled=false; b.textContent="+ Cal";
    if(store.cal[r.getAttribute("data-k")]){ calDone(b); return; }
    b.addEventListener("click",function(ev){
      ev.stopPropagation();                 // don't toggle the row's check-off
      if(b.disabled)return;
      if(!mcp||!calServer){
        b.textContent=mcp?"Calendar not connected":"Not available here";
        b.className="calbtn err"; b.disabled=true; return;
      }
      var payload;
      try{
        payload=JSON.parse(new TextDecoder().decode(
          Uint8Array.from(atob(r.getAttribute("data-cal")),function(c){return c.charCodeAt(0);})));
      }catch(e){ b.textContent="Bad event data"; b.className="calbtn err"; b.disabled=true; return; }
      b.disabled=true; b.textContent="Adding\\u2026"; b.className="calbtn";
      mcp.callTool(calServer,CAL_TOOL,payload).then(function(){
        store.cal[r.getAttribute("data-k")]=1; save(); calDone(b);
      }).catch(function(e){
        b.disabled=false; b.className="calbtn err";
        b.textContent=calErr(e&&e.code);
      });
    });
  }

  // ---- Top 5 auto-refill: when a slot clears, the next-ranked candidate
  // takes its place — same numbered slot, new item — instead of just sitting
  // there checked off until tomorrow's rebuild. topBacklog is the ranked
  // runner-up pool the morning run computed but didn't render; store.topNext
  // is a shared cursor into it (first slot to clear claims the next
  // candidate), and store.topSlot remembers which slots have already been
  // promoted so a page reload replays the same state instead of losing it.
  var backlog=[];
  try{
    var bEl=document.getElementById("topBacklogData");
    if(bEl)backlog=JSON.parse(bEl.textContent||"[]");
  }catch(e){backlog=[];}

  function paintSlot(r,item,idx){
    clearNote(r);
    r.classList.remove("done","pending");
    var k="topb-"+r.getAttribute("data-slot")+"-"+idx;
    r.setAttribute("data-k",k);
    if(item.notionId)r.setAttribute("data-nid",item.notionId); else r.removeAttribute("data-nid");
    r.querySelector(".rowtext").textContent=item.text||"";
    var main=r.querySelector(".rowmain");
    var chips=r.querySelector(".chips");
    var meta=r.querySelector(".meta");
    if(item.why){
      if(!meta){meta=document.createElement("div");meta.className="meta";main.insertBefore(meta,chips);}
      meta.textContent=item.why;
    }else if(meta){meta.parentNode.removeChild(meta);}
    chips.innerHTML="";
    if(item.area){
      var c=document.createElement("span");
      c.className="chip"; c.textContent=item.area;
      var col=item.areaColor||"#7c6f9c";
      c.style.color=col; c.style.borderColor=col+"33"; c.style.background=col+"14";
      chips.appendChild(c);
    }
    if(item.cal){
      try{
        r.setAttribute("data-cal",btoa(unescape(encodeURIComponent(JSON.stringify(item.cal)))));
        var btn=document.createElement("button");
        btn.className="calbtn"; btn.type="button"; btn.textContent="+ Cal";
        chips.appendChild(btn);
        wireCalBtn(r);
      }catch(e){ r.removeAttribute("data-cal"); }
    }else{
      r.removeAttribute("data-cal");
    }
    if(store.done[k])r.classList.add("done");
    progress();
  }

  function maybeRefill(r){
    if(!r.classList.contains("toprow"))return;    // only the Top 5 lane refills
    var slot=r.getAttribute("data-slot");
    if(slot===null||store.topNext>=backlog.length)return;  // pool's dry — slot just stays cleared
    var idx=store.topNext++;
    store.topSlot[slot]=idx;
    save();
    var item=backlog[idx];
    // A beat of delay so the strike-through registers before the item changes
    // underneath it — an instant swap reads as the checkbox not having worked.
    setTimeout(function(){ paintSlot(r,item,idx); },1400);
  }

  // Replay any slots already promoted earlier today, before wiring clicks —
  // so the "done" state below is read against each slot's CURRENT occupant.
  Object.keys(store.topSlot).forEach(function(slot){
    var r=rows.filter(function(x){return x.classList.contains("toprow")&&x.getAttribute("data-slot")===slot;})[0];
    var item=backlog[store.topSlot[slot]];
    if(r&&item)paintSlot(r,item,store.topSlot[slot]);
  });

  rows.forEach(function(r){
    if(store.done[r.getAttribute("data-k")])r.classList.add("done");
    r.addEventListener("click",function(){
      if(r.classList.contains("pending"))return;
      var k=r.getAttribute("data-k");        // read live — refill can change this
      var nid=r.getAttribute("data-nid");
      var on=!r.classList.contains("done");     // intended new state
      setState(r,k,on);                          // optimistic
      if(!mcp||!nid){
        if(nid)note(r,"Visual only in this view","");
        if(on)maybeRefill(r);
        return;
      }
      // Write it through to the Command Center.
      pending(r,true);
      note(r,on?"Saving to Command Center\\u2026":"Reopening in Command Center\\u2026","pending");
      mcp.callTool(SERVER,TOOL,{
        page_id:nid, command:"update_properties",
        properties:{ "Status": on?"Done":"To Do" }
      }).then(function(){
        pending(r,false);
        note(r,on?"Done in Command Center":"Set back to To Do","ok");
        setTimeout(function(){ if(!r.classList.contains("pending"))clearNote(r); },3200);
        if(on)maybeRefill(r);
      }).catch(function(e){
        pending(r,false);
        setState(r,k,!on);                        // revert — the write didn't stick
        note(r,errMsg(e&&e.code),"err");
      });
    });
  });
  progress();

  Array.prototype.forEach.call(document.querySelectorAll(".row[data-cal]"),wireCalBtn);

  // Confirm the connector wiring on load, so a mismatch is visible immediately.
  if(!mcp){
    if(document.querySelector(".row[data-nid]"))
      banner("Live Notion sync isn't available in this view \\u2014 check-offs are visual only. Open the published Docket on claude.ai to sync to your Command Center.");
    return;
  }
  mcp.listTools().then(function(res){
    var servers=(res&&res.servers)||[];
    var names=servers.map(function(s){return s.server;});
    var srv=servers.filter(function(s){return s.server===SERVER;})[0];
    if(!srv){
      banner("Notion isn't connected as \\""+SERVER+"\\". Connected: "+(names.join(", ")||"none")+". Check-offs won't sync until this matches.");
    }else{
      var tools=(srv.tools||[]).map(function(t){return t.name;});
      if(tools.indexOf(TOOL)<0)
        banner("Notion is connected but exposes no \\""+TOOL+"\\" tool. Available: "+(tools.join(", ")||"none")+".");
    }
    // Resolve the calendar connector by CAPABILITY, not by name: whichever
    // connected server actually exposes create_event wins. Falls back to the
    // expected display name so a listTools() hiccup doesn't disable the button.
    var cal=servers.filter(function(s){
      return (s.tools||[]).some(function(t){return t.name===CAL_TOOL;});
    })[0];
    calServer=cal?cal.server:null;
    if(!calServer&&document.querySelector(".row[data-cal]"))
      banner("Google Calendar isn't connected \\u2014 the \\"+ Cal\\" buttons can't add events. Connected: "+(names.join(", ")||"none")+".");
  }).catch(function(){
    calServer=CAL_SERVER;  // listTools failed; try the expected name anyway
  });
})();
</script>
"""


def cal_payloads(d):
    """Every `cal` payload the data expects to become a "+ Cal" button."""
    return [t["cal"]
            for name in ("topPriorities", "carriedOver", "dueToday", "thisWeek", "plan")
            for t in d.get(name, []) if t.get("cal")]


def notion_ids(d, interests):
    """Every notionId the data expects to see wired into a row."""
    ids = [t.get("notionId")
           for name in ("topPriorities", "carriedOver", "dueToday", "thisWeek")
           for t in d.get(name, []) if t.get("notionId")]
    ids += [t.get("notionId")
            for t in list(interests) + list(d.get("exploration", []))
            if t.get("notionId")]
    return ids


def verify(d, interests, full, day, slips=None):
    """Check the rendered board against the data it came from.

    Catches the failures that would otherwise ship silently: a board that isn't
    today's, and Command Center rows that lost their notionId — the id is what
    makes a checkbox green and writes Status=Done back to Notion, so losing it
    breaks check-off without changing how the board looks.

    Returns a list of problems (empty = clean).
    """
    problems = []

    date_ok = bool(day) and day in full
    if not date_ok:
        problems.append("today's date (%s) is not in the rendered page" % day)

    # A Command Center row without its page id renders as a dead grey checkbox.
    orphans = ["%s: %s" % (name, (t.get("text") or "")[:60])
               for name in ("carriedOver", "dueToday", "thisWeek")
               for t in d.get(name, [])
               if t.get("source") == "Command Center" and not t.get("notionId")]
    if orphans:
        problems.append(
            "%d Command Center item(s) carry no notionId, so their check-offs "
            "won't reach Notion: %s" % (len(orphans), "; ".join(orphans)))

    # ...and every id the data does carry has to survive into the HTML.
    ids = notion_ids(d, interests)
    rendered = full.count('data-nid="')
    if rendered != len(ids):
        problems.append("%d notionId(s) in the data but %d data-nid attribute(s) "
                        "in the page" % (len(ids), rendered))

    hub = d.get("notionHub", [])
    plan = d.get("plan", [])

    # A plan block can't be both a locked calendar commitment and something
    # your calendar has never heard of. Claiming `fixed` for an unscheduled
    # commitment is what made the Jul 28 Zoom session look handled when the
    # only thing holding it was the board itself.
    both = [(p.get("time") or "") + " " + (p.get("text") or "")[:50]
            for p in plan if p.get("fixed") and p.get("cal")]
    if both:
        problems.append("%d plan block(s) claim both fixed (already on Calendar) "
                        "and cal (not on Calendar): %s" % (len(both), "; ".join(both)))

    # Same canary as data-nid: a cal payload that doesn't reach the HTML is a
    # "+ Cal" button that silently never appears.
    cals = cal_payloads(d)
    cal_rendered = full.count('data-cal="')
    if cal_rendered != len(cals):
        problems.append("%d cal payload(s) in the data but %d data-cal attribute(s) "
                        "in the page" % (len(cals), cal_rendered))
    incomplete = ["%s: missing %s" % ((c.get("summary") or "?")[:40],
                                      ", ".join(f for f in ("summary", "startTime", "endTime")
                                                if not c.get(f)))
                  for c in cals
                  if not all(c.get(f) for f in ("summary", "startTime", "endTime"))]
    if incomplete:
        problems.append("%d cal payload(s) can't create an event: %s"
                        % (len(incomplete), "; ".join(incomplete)))
    print("  VERIFY date       : %s" % ("found" if date_ok else "MISSING"))
    print("  VERIFY notion hub : %d groups / %d links"
          % (len(hub), sum(len(g.get("items", [])) for g in hub)))
    print("  VERIFY notion ids : %d in data -> %d rendered" % (len(ids), rendered))
    print("  VERIFY trading    : %s" % ("present" if d.get("trading") else "absent"))
    print("  VERIFY top 5      : %d picked, %d checkable"
          % (len(d.get("topPriorities", [])),
             sum(1 for t in d.get("topPriorities", []) if t.get("notionId"))))
    print("  VERIFY top backlog: %d candidate(s) ready to fill a cleared slot"
          % len(d.get("topBacklog", [])))
    print("  VERIFY plan       : %d blocks (%d fixed, %d unscheduled)"
          % (len(plan), sum(1 for p in plan if p.get("fixed")),
             sum(1 for p in plan if p.get("cal"))))
    print("  VERIFY cal buttons: %d in data -> %d rendered"
          % (len(cals), cal_rendered))
    slips = slips or {}
    carried = d.get("carriedOver", [])
    print("  VERIFY slips      : %d carried, worst %d×, %d need a decision"
          % (len(carried),
             max([slips.get(slip_key(t), 1) for t in carried] or [0]),
             sum(1 for t in carried if slips.get(slip_key(t), 1) >= SLIP_ESCALATE)))
    src = d.get("sources")
    print("  VERIFY sources    : %s"
          % (", ".join("%s=%s" % (k, v) for k, v in src.items())
             if isinstance(src, dict) and src
             else ("legacy 'verified' string" if d.get("verified") else "NONE — stamp hidden")))
    return problems


def build():
    d = load(DATA, {})
    interests = load(INTERESTS, {"items": []}).get("items", [])
    board_day = d.get("date") or datetime.now().strftime("%A, %B %d, %Y")
    ledger, slips = update_ledger(d, board_day)
    save_json(LEDGER, ledger)
    day, inner = render_inner(d, interests, slips, ledger)

    full = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>The Docket</title><style>html,body{margin:0;padding:0}%s</style></head>'
        '<body class="dk-scope" data-day="%s">%s%s</body></html>'
        % (STYLE, esc(day), inner, SCRIPT)
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(full)
    # index.html mirrors docket.html so the Cowork preview server serves the latest at "/".
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(full)

    widget = (
        '<style>%s.dk-scope{border-radius:16px;overflow:hidden}</style>'
        '<div class="dk-scope" data-day="%s">%s</div>%s'
        % (STYLE, esc(day), inner, SCRIPT)
    )
    with open(WIDGET, "w", encoding="utf-8") as f:
        f.write(widget)

    shown, more = visible_interests(interests, d, day)
    c = {
        "carry": len(d.get("carriedOver", [])),
        "due": len(d.get("dueToday", [])),
        "mail": len(d.get("email", [])),
        "week": len(d.get("thisWeek", [])),
        "expl": len(shown) + more,
    }
    print("The Docket built -> docket.html + docket_widget.html")
    print("  carried over: %(carry)s | due today: %(due)s | email: %(mail)s | this week: %(week)s | exploration: %(expl)s" % c)

    problems = verify(d, shown, full, day, slips)
    if problems:
        for p in problems:
            print("DOCKET BUILD FAILED: %s" % p)
        sys.exit(1)


if __name__ == "__main__":
    build()
