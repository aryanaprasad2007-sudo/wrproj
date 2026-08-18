"""Deterministic pre-read for the `speedrun` skill.

Answers the questions about today's Top 5 that are arithmetic rather than
judgment: what time it is against today's plan, which Top 5 items own a
block and whether that block is past / live / still ahead, which are
checkable in Notion, and how long each has been slipping.

The model reads the briefing this prints and spends its tokens on the half
that IS judgment -- who can actually act on each item, and what the fastest
path through it looks like. Re-deriving the arithmetic from a 25KB JSON on
every invocation is what `credit-efficient-execution` exists to stop.

Run:
    py -3.12 triage.py              human-readable briefing
    py -3.12 triage.py --json       same data, machine-readable
    py -3.12 triage.py --at 21:30   pretend it is 9:30 PM (for testing)

NEVER bare `python` -- see CLAUDE.md. This file prints plan blocks, which
carry emoji, into a cp1252 console; stdout is reconfigured below for the
same reason every other __main__ in this project does it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

DOCKET = Path(r"C:\Users\aware\OneDrive\Desktop\wrproj\Daily-Docket")
DATA = DOCKET / "docket_data.json"
SLIPS = DOCKET / "slips.json"

# How similar a plan block's text must be to a Top 5 entry before we claim
# they are the same thing. MEASURED on the real 2026-08-17 board, not guessed:
#
#   true pairs   0.547  "Correct the Primerica hours row" vs its 3:45 block
#                0.965  the credit freeze
#                0.980  the CHEM Appendix A homework
#   best FALSE   0.411  CHEM 3A homework vs CHEM 3A *lecture*
#
# 0.48 splits that 0.411 / 0.547 gap. The lecture-vs-homework pair is the one
# that matters: both are "CHEM 3A", so a threshold low enough to fuse them
# would report the homework's block as 1:00-3:30 PM -- a real time, already
# past, entirely wrong. Re-measure before moving this, and note that a
# below-threshold best score is printed rather than swallowed, so drift shows.
MATCH_MIN = 0.48

# Words too common to prove two strings are about the same task.
STOP = {
    "the", "a", "an", "and", "or", "of", "to", "at", "in", "on", "for",
    "with", "your", "you", "is", "it", "that", "this", "new", "top", "from",
}


# --------------------------------------------------------------------------
# time parsing
# --------------------------------------------------------------------------

# The plan writes ranges with an EN DASH (U+2013), not a hyphen, and hangs
# the meridiem wherever it reads best: "9:15 - 11:00 AM", "1:00 - 3:30 PM",
# "11:00 AM - 12:00 PM". A split on "-" matches none of these and fails
# silently, reporting a fully-scheduled day as fully unscheduled.
RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\s*[\u2013\u2014-]\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?",
    re.I,
)


def to_min(hour: int, minute: int, meridiem: str) -> int:
    """Clock time -> minutes since midnight."""
    hour %= 12
    if meridiem.upper() == "PM":
        hour += 12
    return hour * 60 + minute


def parse_range(text):
    """'1:00 - 3:30 PM' -> (780, 930). Returns (None, None) if unreadable."""
    m = RANGE_RE.search(text or "")
    if not m:
        return None, None
    sh, sm, smer, eh, em, emer = m.groups()
    smer = (smer or emer or "").upper()
    emer = (emer or smer or "").upper()
    if not smer:
        return None, None  # no meridiem anywhere -- refuse to guess
    start = to_min(int(sh), int(sm or 0), smer)
    end = to_min(int(eh), int(em or 0), emer)
    # "11:30 - 12:30 PM": the start inherited PM and now lands AFTER the end.
    # The only reading that runs forward is the other meridiem.
    if start > end:
        start = to_min(int(sh), int(sm or 0), "AM" if smer == "PM" else "PM")
    return start, end


def hhmm(mins) -> str:
    if mins is None:
        return "--:--"
    h, m = divmod(int(mins) % (24 * 60), 60)
    ap = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12}:{m:02d} {ap}"


def dur(mins) -> str:
    """Minutes -> '1h 45m' / '25m'."""
    mins = int(mins)
    h, m = divmod(abs(mins), 60)
    out = (f"{h}h " if h else "") + (f"{m}m" if m or not h else "")
    return out.strip()


def day_label(when: dt.datetime) -> str:
    """The exact string the renderer stamps into docket_data.json's `date`."""
    return f"{when:%A}, {when:%B} {when.day}, {when.year}"


# --------------------------------------------------------------------------
# matching Top 5 entries to plan blocks
# --------------------------------------------------------------------------

def norm(s: str) -> str:
    """Lowercase, strip emoji/symbols and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.category(c).startswith("S"))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def similarity(a: str, b: str) -> float:
    """Blend raw string ratio with distinctive-token overlap.

    Ratio alone under-scores true pairs the renderer phrased differently
    ("Freeze credit at X, Y and Z" vs "Freeze credit - X, Y, Z"); token
    overlap alone over-scores two School tasks that merely share vocabulary.
    Taking the max keeps near-identical strings at their honest high score
    while rescuing the reworded ones.
    """
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta = {w for w in na.split() if w not in STOP and len(w) > 3}
    tb = {w for w in nb.split() if w not in STOP and len(w) > 3}
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(ratio, 0.45 * ratio + 0.55 * overlap)


def slip_key(item: dict) -> str:
    """Same identity the renderer uses -- imported so it cannot drift."""
    try:
        if str(DOCKET) not in sys.path:
            sys.path.insert(0, str(DOCKET))
        from build_docket import slip_key as real  # type: ignore
        return real(item)
    except Exception:
        nid = item.get("notionId")
        if nid:
            return "nid:" + nid
        return "txt:" + hashlib.md5(
            (item.get("text") or "").encode("utf-8")
        ).hexdigest()[:12]


# --------------------------------------------------------------------------
# ordering policy
# --------------------------------------------------------------------------
#
# Every item handed to pick_order() carries these DETERMINISTIC fields:
#
#   rank        0-based position in topPriorities (the 6 AM run's judgment)
#   start,end   its plan block in minutes since midnight, or None
#   state       "live" | "past" | "ahead" | "unscheduled"
#   until       minutes until its block starts (negative once underway/past)
#   length      how many minutes the plan gave it, or None
#   has_notion  True if it can be checked off straight into Notion
#   slips       how many board-days it has survived uncleared
#
# Two reference policies are implemented below so the shape is obvious.

def _by_deck_clear(items, now):
    """Shortest planned block first -- clear the deck, build momentum."""
    return sorted(
        items,
        key=lambda i: (i["length"] is None, i["length"] or 0, i["rank"]),
    )


def _by_frog_first(items, now):
    """Most-slipped then longest first -- best energy on the real thing."""
    return sorted(
        items,
        key=lambda i: (-i["slips"], -(i["length"] or 0), i["rank"]),
    )


def pick_order(items, now):
    """Return `items` in the order Ari should actually attack them.

    TODO(Ari): this is the one real decision in this file, and it is yours.
    Replace the body below with the policy you want. Worth weighing:

      * state == "live" means the plan says this is happening RIGHT NOW.
        Does a live block outrank everything, or is a sprint allowed to
        ignore the clock and just go hardest-first?
      * state == "past" means the plan gave it a slot and it did not happen.
        That is either the most urgent thing on the list or the clearest
        sign it should be dropped -- a values call, not a derivable one.
      * "ahead" items with a small `until` cannot be properly started, only
        *staged*. Do they sort in, or get held back until their block?
      * `slips` is the honest anti-rot signal already in your ledger.
      * Deliberate omission: nothing here knows about dependencies -- today
        the email lockdown genuinely unblocks the other Admin items, and
        the data does not carry that. If order should respect it, it has
        to be stated.

    Return the list; the briefing prints it as the run order.
    """
    # PLACEHOLDER -- keeps the skill usable until you pick. Respects the
    # plan: scheduled things in clock order, unscheduled last, ties by rank.
    return sorted(
        items,
        key=lambda i: (i["start"] is None, i["start"] or 0, i["rank"]),
    )


# --------------------------------------------------------------------------
# briefing
# --------------------------------------------------------------------------

def build(now_min: int):
    data = json.loads(DATA.read_text(encoding="utf-8"))
    try:
        slips = json.loads(SLIPS.read_text(encoding="utf-8"))
    except Exception:
        slips = {}

    blocks = []
    for b in (data.get("plan") or []):
        s, e = parse_range(b.get("time", ""))
        blocks.append({**b, "start": s, "end": e})

    items = []
    for rank, t in enumerate(data.get("topPriorities") or []):
        best, best_score = None, 0.0
        for b in blocks:
            sc = similarity(t.get("text", ""), b.get("text", ""))
            if sc > best_score:
                best, best_score = b, sc
        if best_score < MATCH_MIN:
            best = None

        start = best["start"] if best else None
        end = best["end"] if best else None
        if start is None:
            state, until = "unscheduled", None
        elif now_min < start:
            state, until = "ahead", start - now_min
        elif now_min < (end or start):
            state, until = "live", start - now_min
        else:
            state, until = "past", start - now_min

        led = slips.get(slip_key(t)) or {}
        items.append({
            "rank": rank,
            "text": t.get("text", ""),
            "why": t.get("why", ""),
            "area": t.get("area", ""),
            "notionId": t.get("notionId"),
            "has_notion": bool(t.get("notionId")),
            "block": (best or {}).get("time"),
            "block_text": (best or {}).get("text"),
            "match": round(best_score, 2),
            "start": start,
            "end": end,
            "length": (end - start) if (start is not None and end is not None) else None,
            "state": state,
            "until": until,
            "slips": 0 if led.get("cleared") else int(led.get("count") or 0),
        })

    # The next hard commitment the sprint has to finish before.
    nxt = None
    timed = sorted(
        [x for x in blocks if x["start"] is not None], key=lambda x: x["start"]
    )
    for b in timed:
        if b.get("fixed") and b["start"] > now_min:
            nxt = b
            break

    return data, items, nxt


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Top 5 sprint briefing.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--at", metavar="HH:MM", help="pretend it is this time (24h)")
    args = ap.parse_args()

    now = dt.datetime.now()
    if args.at:
        h, _, m = args.at.partition(":")
        now = now.replace(hour=int(h), minute=int(m or 0))
    now_min = now.hour * 60 + now.minute

    data, items, nxt = build(now_min)
    ordered = pick_order(items, now_min)

    expect = day_label(now)
    board_date = data.get("date", "?")
    stale = board_date != expect

    if args.json:
        print(json.dumps({
            "now": hhmm(now_min),
            "board_date": board_date,
            "expected_date": expect,
            "stale": stale,
            "nowTask": data.get("nowTask"),
            "order": [i["rank"] for i in ordered],
            "items": ordered,
            "next_fixed": nxt,
            "backlog": data.get("topBacklog") or [],
        }, indent=2, ensure_ascii=False))
        return 0

    print(f"SPRINT BRIEFING  --  {expect}  @ {hhmm(now_min)}")
    print(
        f"board: {board_date}"
        + ("   *** STALE -- this is NOT today's board ***" if stale else "   [today]")
    )

    nt = data.get("nowTask") or {}
    if nt:
        print(f"RIGHT NOW (pinned since {nt.get('since', '?')}): {nt.get('text', '')}")

    if nxt:
        print(
            f"next fixed anchor: {nxt['time']}  {nxt['text']}"
            f"   -> {dur(nxt['start'] - now_min)} of runway"
        )
    else:
        print("next fixed anchor: none left today -- the rest of the day is open")

    print()
    print(f"TOP {len(items)}  (run order from pick_order)")
    print("-" * 72)
    for n, i in enumerate(ordered, 1):
        marks = []
        if i["state"] == "live":
            marks.append("LIVE NOW")
        elif i["state"] == "past":
            marks.append(f"BLOCK PASSED ({dur(-i['until'])} ago)")
        elif i["state"] == "ahead":
            marks.append(f"starts in {dur(i['until'])}")
        else:
            # Show the best score we rejected. A near-miss (just under
            # MATCH_MIN) means the match logic drifted, not that the item
            # is genuinely unscheduled -- worth seeing rather than swallowing.
            near = f" (best match {i['match']}, under {MATCH_MIN})" if i["match"] else ""
            marks.append("NO BLOCK ON THE PLAN" + near)
        if i["length"]:
            marks.append(f"planned {dur(i['length'])}")
        marks.append("checkable" if i["has_notion"] else "no Notion row -- cannot check off")
        if i["slips"] >= 2:
            marks.append(f"slipped {i['slips']}x")

        print(f"{n}. [#{i['rank'] + 1} this morning] {i['text']}")
        print(f"   {i['area']}  |  " + "  |  ".join(marks))
        if i["block"]:
            print(f"   block: {i['block']}  (matched {i['match']})")
        print(f"   why: {i['why'][:180]}")
        print()

    unsched = [i for i in items if i["state"] == "unscheduled"]
    if unsched:
        print(f"! {len(unsched)} item(s) have no time block -- they need a slot "
              f"or they will not happen:")
        for i in unsched:
            print(f"    - {i['text']}")
        print()

    backlog = data.get("topBacklog") or []
    print(
        f"refills available in topBacklog: {len(backlog)}"
        + (f"  (next: {backlog[0].get('text', '')})" if backlog else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
