"""
Perfect Ari, as a plan the resolver can compare against.

This is what finally lets `plan_for_now()` return something other than None
(open item #8). The profile is the plan until The Docket is wired in.

Two rules carried over from `mode_log.py`, both load-bearing:

  * None means UNKNOWN, never OFF-PLAN. No block, no camera, no claim.
  * `absent` is often the plan working. Roughly half of Perfect Ari's day
    happens away from the desk -- gym, dance, shower, lunch, meal prep. A
    tracker that read "nobody in frame" as drift would flag him hardest at
    exactly the moments he was most on plan.

Nothing here writes a message. It produces the facts a message can be built
from, so that whatever writes the words -- Aria, or the page itself -- has
nothing to invent.
"""
import json
import os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, "profile.json")

# Perfect Ari block -> Aria's register (persona/aria.yaml `modes`). Her own
# mode text already answers "how hard should this push": study mode says the
# bit gets one line at most because every joke costs him re-entry, while gamer
# mode says the bit gets full room. That is a better tone policy than anything
# invented here, and it is his.
#
# NOT used to auto-switch her mode -- assistant/modes.py is explicit that an
# inferred mode is worse than none. This is passed as a hint about register,
# and she decides.
BLOCK_REGISTER = {
    "Deep work": "study",
    "Chem lecture": "study",
    "Protected study": "study",
    "Notion recap": "study",
    "Gym": "gym",
    "Dance": "dance",
    "Free time": "gamer",
}


def load(path=PROFILE):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def blocks_sorted(profile):
    return sorted(profile["blocks"], key=lambda b: _minutes(b["start"]))


def block_at(profile, now):
    """
    Which block `now` falls in, plus when it started and ends.

    Blocks tile the day half-open [start, next_start), so there is always
    exactly one -- including across midnight, where the last block of the list
    wraps. The 01:00 night ritual therefore covers 01:00-07:00, which is why
    sleeping is never reported as drift.
    """
    bs = blocks_sorted(profile)
    if not bs:
        return None
    mins = now.hour * 60 + now.minute
    current = bs[-1]                      # wrap: before the first start
    nxt = bs[0]
    for i, b in enumerate(bs):
        if _minutes(b["start"]) <= mins:
            current = b
            nxt = bs[(i + 1) % len(bs)]

    start_min = _minutes(current["start"])
    started = now.replace(hour=start_min // 60, minute=start_min % 60,
                          second=0, microsecond=0)
    if started > now:                     # wrapped from yesterday
        started -= timedelta(days=1)

    end_min = _minutes(nxt["start"])
    ends = now.replace(hour=end_min // 60, minute=end_min % 60,
                       second=0, microsecond=0)
    if ends <= started:
        ends += timedelta(days=1)

    return {**current, "started": started, "ends": ends,
            "register": BLOCK_REGISTER.get(current["name"]),
            "elapsed_min": round((now - started).total_seconds() / 60),
            "remaining_min": round((ends - now).total_seconds() / 60)}


def plan_for_now(now=None, profile=None):
    """
    Drop-in for `mode_log.plan_for_now()`.

    Returns the block dict, or None when there is genuinely no plan on record.
    Callers must treat None as unknown -- inventing a violation out of missing
    data is the failure mode that would make the whole thing untrustworthy.
    """
    try:
        profile = profile or load()
    except (OSError, ValueError):
        return None
    return block_at(profile, now or datetime.now())


def deviation(block, mode, minutes_in_mode, camera_ok=True):
    """
    Compare observed mode against the block. Facts only -- no prose.

    Status is one of:
        unknown   no plan, or the camera is down. NOT a judgement.
        on_plan   the observed mode is one the block expects
        drifting  off the expected set, but inside the grace window
        off_plan  off the expected set for longer than grace

    The grace window exists so that standing up mid-study-block does not
    register as failure. It is about noticing a block that did not happen, not
    about policing the clock.
    """
    if not camera_ok or mode == "camera_lost":
        return {"status": "unknown", "reason": "camera feed is down",
                "expected": [], "observed": mode}
    if block is None:
        return {"status": "unknown", "reason": "no block on record",
                "expected": [], "observed": mode}

    expected = list(block.get("modes") or [])
    away_ok = bool(block.get("away_ok"))

    # An empty `modes` list means the block is genuinely free -- free time and
    # lunch are not supposed to have a correct answer.
    if not expected:
        return {"status": "on_plan", "reason": "block has no expected mode",
                "expected": [], "observed": mode, "free": True}

    if mode in expected or (away_ok and mode in ("away", "screen_abandoned")):
        return {"status": "on_plan", "reason": "matches the block",
                "expected": expected, "observed": mode}

    grace = 20
    try:
        grace = int(load().get("grace_minutes", 20))
    except (OSError, ValueError):
        pass

    status = "drifting" if minutes_in_mode < grace else "off_plan"
    return {"status": status, "expected": expected, "observed": mode,
            "minutes": minutes_in_mode, "grace_minutes": grace,
            "reason": f"{mode} is not in {expected}"}


def facts(block, mode, why, minutes_in_mode, screen, spot, now, reading=None):
    """
    Everything true about this moment, as a flat dict.

    This is the ONLY thing handed to whatever writes the words. A 7B model
    given room to speculate will speculate -- the persona file already carries
    scar tissue from qwen2.5 inventing file contents it never read -- so the
    contract is that every noun in the output has to appear here first.
    """
    dev = deviation(block, mode, minutes_in_mode,
                    camera_ok=(spot != "camera_lost"))
    out = {
        "clock": now.strftime("%H:%M"),
        "observed_mode": mode,
        "why_the_tracker_says_so": why,
        "minutes_in_this_mode": minutes_in_mode,
        "camera_sees": spot,
        "screen_app": screen.get("app") or screen.get("title") or "unknown",
        "screen_category": screen.get("category"),
        "screen_idle": screen.get("idle"),
        "screen_idle_seconds": round(screen.get("idle_seconds") or 0),
        "deviation": dev,
    }
    if reading:
        # Posture is deliberately NOT sent to Aria's prompt list -- it is here
        # for the panel only. She gets the facts named in aria_link._prompt,
        # and adding a field there silently widens what she may assert.
        out["posture"] = reading.get("posture")
        out["torso_angle"] = (round(reading["torso_angle"], 1)
                              if reading.get("torso_angle") is not None else None)
    if block:
        out.update({
            "block_name": block["name"],
            "block_emoji": block.get("emoji", ""),
            "block_window": f"{block['start']}-{block['ends']:%H:%M}",
            "block_note": block.get("note", ""),
            "minutes_into_block": block["elapsed_min"],
            "minutes_left_in_block": block["remaining_min"],
            "block_expects": block.get("modes") or ["anything"],
            "being_away_is_fine_here": bool(block.get("away_ok")),
            "register": block.get("register"),
        })
    return out


if __name__ == "__main__":
    import sys
    # The Windows console is cp1252, and profile.json is deliberately full of
    # emoji. Printing a block name would otherwise die with UnicodeEncodeError
    # in the *reporting* path, which is a miserable way to lose a working run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    now = datetime.now()
    if len(sys.argv) > 1:                 # profile_plan.py 15:40
        h, m = sys.argv[1].split(":")
        now = now.replace(hour=int(h), minute=int(m))
    p = load()
    print(f"\n  now: {now:%H:%M}\n")
    b = block_at(p, now)
    print(f"  block      {b['emoji']} {b['name']}  ({b['start']} -> {b['ends']:%H:%M})")
    print(f"  elapsed    {b['elapsed_min']}m in, {b['remaining_min']}m left")
    print(f"  expects    {b['modes'] or ['anything']}")
    print(f"  away ok    {b['away_ok']}")
    print(f"  register   {b['register']}")
    print()
    for mode in ("deep_work", "leisure", "away", "camera_lost"):
        d = deviation(b, mode, 25)
        print(f"  {mode:<13} -> {d['status']:<9} {d['reason']}")
    print()
