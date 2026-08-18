"""
The mode log -- what you were actually doing, all day, in one timeline.

This is the durable artifact the whole system exists to produce. Neither
sensor can write it alone:

    camera  -> WHERE you are and HOW you're sitting (desk, bed, gone; posture)
    screen  -> WHAT is in front of you (VS Code, Canvas, Steam, Crunchyroll)
    clock   -> WHETHER THAT'S FINE (bed + anime at 23:30 is recovery;
               the same two readings at 14:00 are drift)

It logs RUNS, not samples: one line per contiguous stretch in a mode. A day of
samples would be ~4,000 rows of mostly-identical noise; a day of runs is a few
dozen rows that answer "how long did I focus on school" by reading them.

    python src/mode_log.py            # run until Ctrl+C
    python src/mode_log.py today      # print today's timeline and exit

Nothing leaves this machine and no images are stored -- each burst is
classified in memory and discarded. The log holds labels and timestamps only.
"""
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

from camera_state import CameraState
from capture import Camera
from pose_detector import PoseDetector, place
from window_sensor import WindowClassifier, sample as screen_sample

# Pose, not Haar. Measured head-to-head on 24 minutes of real footage
# (sessions/IMG_9874_analysis), 293 bursts:
#
#   flicker            haar 84 flips   pose 15
#   longest at_desk    haar 2:25       pose 12:40
#   false "absent"     haar 8          pose 0   (verified frame by frame --
#                                                he was visible in all 8)
#
# Haar also called 32% of a straight desk session "present_unclear". The face
# cascade simply does not find a head reliably at this camera angle, and the
# pose model finds the person in frames YOLO-detect misses entirely.

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHER_PS1 = os.path.join(ROOT, "src", "watcher_nudge.ps1")


def load_config():
    with open(os.path.join(ROOT, "modes.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def is_night(hour, cfg):
    """Night window, handling the fact that it wraps past midnight."""
    start, end = cfg["night_starts_hour"], cfg["night_ends_hour"]
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def resolve_mode(spot, screen, now, cfg):
    """
    Fuse both sensors and the clock into one mode.

    Order matters: the earliest matching rule wins, and the rules are sorted
    by how much they *know*. Presence is settled before content, because
    "nobody is there" makes every question about the screen moot.

    Returns (mode, why) -- `why` is kept so the log can be audited later and
    so an intervention can quote the reason instead of asserting it.
    """
    cat = screen["category"]
    idle = screen["idle"]
    passive = screen["passive"]
    night = is_night(now.hour, cfg)

    work = cat in cfg["work_categories"]
    leisure = cat in cfg["leisure_categories"]

    # --- the camera is lying to us ---------------------------------------
    # Must come first, and must never fall through. When Iriun loses the phone
    # it streams a placeholder card rather than failing, so the frame is valid,
    # person-free, and utterly convincing -- without this branch the pipeline
    # reports "absent" and the day's log grows a stretch of `away` that never
    # happened. Falling through is worse still: none of the later branches
    # match, so it would land in the at-desk section and log deep_work.
    #
    # The screen sensor is unaffected by any of this, so it still gets a say.
    # Active input is proof of a human at the keyboard no matter what the
    # camera thinks -- the same reasoning the present_unclear branch uses.
    if spot == "camera_lost":
        if work and not idle:
            return "deep_work", f"{cat}, active input, CAMERA DOWN"
        if not idle:
            return "present_unclear", f"{cat}, active input, CAMERA DOWN"
        # No camera and no input. There is genuinely nothing to go on, and
        # "away" would be a guess dressed as an observation.
        return "camera_lost", f"camera feed dead, screen={cat}, idle"

    # --- nobody in frame -------------------------------------------------
    if spot == "absent":
        if cat == "locked" or (idle and not passive):
            return "away", "no person, screen idle or locked"
        if passive:
            # Video playing to an empty room. Common and harmless, but it is
            # not watching -- do not credit it as leisure time.
            return "away", f"no person, {cat} playing unattended"
        return "screen_abandoned", f"no person but {cat} left active"

    # --- phone beats everything on screen --------------------------------
    # The phone is a second screen this system cannot read. Whatever the
    # monitor claims, attention is demonstrably somewhere else.
    #
    # Unreachable while trust_phone_detection is false in modes.json, which is
    # the default here because the phone is the camera. Kept intact so that
    # swapping in a dedicated webcam is a one-line config change, not a rewrite.
    if spot == "on_phone":
        return ("phone_night" if night else "on_phone"), "phone in hand"

    # --- lying down / reclined (pose detector only) ----------------------
    # The Haar detector cannot produce these, so this block is dead unless a
    # PoseDetector is in use. It is the case you described in your own words:
    # bed + TV at night is recovery, and the same scene at 2pm is not.
    if spot in ("lying_down", "reclined"):
        if work and not idle:
            # Actually working, just not at the desk. Laptop in bed counts.
            return "deep_work", f"{cat}, active, reclined"
        if passive:
            return ("recovery" if night else "watching_in_bed"), f"{cat} while lying down"
        if leisure:
            return ("recovery" if night else "leisure"), f"{cat} while lying down"
        if idle:
            return ("recovery" if night else "resting"), "lying down, screen idle"
        return "resting", f"lying down, screen={cat}"

    # --- present, but the camera can't read posture ----------------------
    if spot == "present_unclear":
        if work and not idle:
            # Typing is proof of engagement; the head just wasn't found.
            return "deep_work", f"{cat}, active input, head not located"
        if passive and idle:
            return ("recovery" if night else "watching"), f"{cat}, reclined or turned away"
        return "present_unclear", f"person present, posture unknown, screen={cat}"

    # --- at the desk, head up --------------------------------------------
    if work:
        if not idle:
            return "deep_work", f"at desk, {cat}, active"
        # Idle at the desk on work: reading, thinking, or stalled. The camera
        # confirms you are still in the chair, which is the whole reason the
        # window sensor refuses to guess this one.
        return "work_paused", f"at desk, {cat}, no input {screen['idle_seconds']:.0f}s"

    if leisure:
        if passive and idle:
            return ("recovery" if night else "watching"), f"at desk, {cat}, watching"
        return ("recovery" if night else "leisure"), f"at desk, {cat}, active"

    if cat == "locked":
        return "present_unclear", "at desk, screen locked"

    return "unknown", f"at desk, unmapped screen category '{cat}'"


def plan_for_now(now):
    """
    What The Docket says this block is for.

    Not wired up yet. Returning None means "no plan on record", and every
    caller must treat that as *unknown*, never as *off-plan* -- inventing a
    violation from missing data is exactly the failure mode that would make
    the intervention card untrustworthy.
    """
    return None


# --- intervention policy --------------------------------------------------
#
# OFF by default: `interventions_enabled` in modes.json must be set to true
# before this ever puts a card on the screen. The logic below is complete and
# was written because "do all" was asked for explicitly, but flipping on a
# real desktop popup is a bigger change than writing a function, and that
# activation stays a deliberate choice made by editing modes.json, not
# something implied by a chat message.
#
# Three questions this settles, and the reasoning behind each:
#
#   WHICH MODES QUALIFY. leisure, watching, screen_abandoned, on_phone,
#   phone_night. NOT work_paused -- it could be real thinking, and
#   interrupting that is worse than the drift it might not even be. NOT
#   recovery or away -- recovery is the plan working, and away is not a claim
#   about you at all, it is a claim about where the camera thinks you are.
#
#   HOW LONG IS TOO LONG. Per-mode, not one global number, because "too long"
#   means different things per mode: leisure/watching get a real runway (a
#   deliberate break should not trigger a card ten minutes in); phone gets a
#   shorter one; screen_abandoned shortest of all, since nothing is even
#   claimed to be happening there.
#
#   NIGHT EXEMPTION. Handled upstream, not here: resolve_mode() already
#   returns `recovery` instead of `leisure`/`watching` during night hours (see
#   is_night()), so those two structurally cannot reach this function at
#   night in the first place. screen_abandoned gets no night exemption on
#   purpose -- a screen left running while you're away at 2am is not less
#   worth flagging than at 2pm, arguably more.
#
# Repeat-rate is deliberately NOT handled in this function -- see the
# docstring for why, and INTERVENE_COOLDOWN_MINUTES for the actual guard.
INTERVENE_THRESHOLD_MINUTES = {
    "leisure": 45,
    "watching": 45,
    "on_phone": 15,
    "phone_night": 15,
    "screen_abandoned": 20,
}

# Once fired, the SAME continuous run will not fire again for this many
# minutes. Without this, a mode that sits over threshold for an hour would
# re-fire on every single 15s sample -- the repeat-rate guard the open items
# list called for. Enforced by the caller (main()), which is the only place
# that knows whether THIS run already fired.
INTERVENE_COOLDOWN_MINUTES = 20


def should_intervene(mode, seconds_in_mode, now, cfg):
    """
    Decide whether this moment is over its threshold.

    Pure and stateless on purpose: given the same (mode, seconds_in_mode) it
    always answers the same way, so it's trivially testable without faking a
    clock across repeated calls. It does NOT know whether a card already
    fired for this run -- that's the caller's job (see
    INTERVENE_COOLDOWN_MINUTES), kept separate so this function only ever
    answers one question.

    Args:
        mode:            current resolved mode, e.g. "leisure", "deep_work"
        seconds_in_mode: how long it has been unbroken
        now:             datetime of this sample (unused by the default
                         policy -- kept in the signature because a future
                         policy will likely want it, e.g. a stricter
                         threshold near a Docket-planned block)
        cfg:             modes.json

    Returns:
        (True, reason) to fire the card, or (False, None) to stay quiet.
    """
    if not cfg.get("interventions_enabled", False):
        return False, None

    threshold = INTERVENE_THRESHOLD_MINUTES.get(mode)
    if threshold is None:
        return False, None

    minutes = seconds_in_mode / 60.0
    if minutes < threshold:
        return False, None

    return True, f"{mode}, {minutes:.0f} minutes unbroken"


def fire_watcher_card(reason, cfg):
    """
    Launch the observer's card, non-blocking.

    `reason` is `should_intervene()`'s own return value -- built entirely
    from the mode name and elapsed minutes, nothing composed here. That is
    the house rule watcher_nudge.ps1 documents: every claim in -Message must
    come from recorded data.

    subprocess.Popen, not run()/check_call(): the sample loop must not stall
    for the card's ~14s lifetime. Popen only makes the PYTHON side
    non-blocking, though -- the powershell.exe process itself is launched
    WITHOUT passing -NoWait through to Show-NOWatcher, so it keeps running
    for the card's duration. Show-NOWatcher's WPF window lives in a
    background runspace inside that same OS process; if powershell.exe
    exited the moment this call returned, the runspace and the window would
    be torn down with it before anyone saw the card.
    """
    if not os.path.exists(WATCHER_PS1):
        return
    title = cfg.get("intervene_title", "I am aware.")
    # PowerShell's escape for a literal ' inside a '...'-quoted string is ''
    # (doubled), not a backslash -- the ps1 file's own house rule already
    # keeps -Message to plain generated text, but this holds even if that
    # ever changes.
    def esc(s):
        return str(s).replace("'", "''")
    command = (f". '{esc(WATCHER_PS1)}'; "
              f"Show-NOWatcher -Title '{esc(title)}' -Message '{esc(reason)}'")
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        pass    # a missing/broken powershell must never crash the tracker loop


class ModeLogger:
    def __init__(self, cfg):
        self.cfg = cfg
        self.log_dir = os.path.join(ROOT, cfg.get("log_dir", "logs"))
        os.makedirs(self.log_dir, exist_ok=True)

        self.current = None       # committed run: {mode, why, start, samples}
        self.pending = None       # candidate mode not yet held long enough
        self.pending_since = None

    def log_path(self, when):
        return os.path.join(self.log_dir, f"modes-{when:%Y-%m-%d}.jsonl")

    def observe(self, mode, why, now):
        """
        Feed one sample in. Returns the run that just closed, if any.

        Debounce lives here. A mode must hold for min_run_seconds before it
        replaces the current one, otherwise glancing at Discord for eight
        seconds would slice a two-hour work block into three rows and the
        daily rollup would report fragmentation that never happened.
        """
        if self.current is None:
            self.current = {"mode": mode, "why": why, "start": now, "samples": 1}
            return None

        if mode == self.current["mode"]:
            self.current["samples"] += 1
            self.current["why"] = why          # keep the most recent evidence
            self.pending = None                # the blip did not stick
            return None

        if self.pending != mode:
            self.pending = mode
            self.pending_since = now
            return None

        if (now - self.pending_since).total_seconds() < self.cfg["min_run_seconds"]:
            return None

        # Held long enough -- commit. The new run is backdated to when it
        # actually began, not to now, or every switch would lose the debounce
        # window and the timeline would drift later and later all day.
        closed = self.close(self.pending_since)
        self.current = {"mode": mode, "why": why,
                        "start": self.pending_since, "samples": 1}
        self.pending = None
        return closed

    def close(self, end):
        """Write the current run out and return it."""
        if self.current is None:
            return None
        run = self.current
        seconds = (end - run["start"]).total_seconds()
        row = {
            "mode": run["mode"],
            "start": run["start"].isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "minutes": round(seconds / 60, 1),
            "samples": run["samples"],
            "why": run["why"],
        }
        with open(self.log_path(run["start"]), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        self.current = None
        return row


def show_today():
    cfg = load_config()
    path = os.path.join(ROOT, cfg.get("log_dir", "logs"),
                        f"modes-{datetime.now():%Y-%m-%d}.jsonl")
    if not os.path.exists(path):
        print(f"[!] Nothing logged today yet ({path})")
        return 1

    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    totals = {}
    print(f"\n  {'start':<6} {'end':<6} {'min':>6}  {'mode':<17} why")
    print("  " + "-" * 76)
    for r in rows:
        totals[r["mode"]] = totals.get(r["mode"], 0) + r["minutes"]
        print(f"  {r['start'][11:16]:<6} {r['end'][11:16]:<6} {r['minutes']:>6.1f}  "
              f"{r['mode']:<17} {r['why'][:34]}")

    print(f"\n  {'TOTALS':<13}")
    for mode, mins in sorted(totals.items(), key=lambda kv: -kv[1]):
        bar = "#" * int(mins / 5)
        print(f"  {mode:<17} {mins:>6.1f} min  {bar}")
    print()
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "today":
        return show_today()

    cfg = load_config()
    print("[*] Loading detector ...")
    detector = PoseDetector()
    cam = Camera(0)
    cam_state = CameraState(cam, detector)
    screen_clf = WindowClassifier()
    logger = ModeLogger(cfg)

    interval = cfg["interval_seconds"]
    print(f"[*] Camera on {cam.backend_name}; sampling every {interval}s")
    print("[*] Ctrl+C to stop -- the run in progress is flushed on exit.\n")

    stop = {"now": False}

    def handle(_sig, _frm):
        stop["now"] = True

    signal.signal(signal.SIGINT, handle)

    # Cooldown state for should_intervene(): which run last fired, and when.
    # A NEW run is always allowed to fire once regardless of cooldown -- the
    # cooldown only suppresses the SAME run re-firing every single sample
    # once it's over threshold.
    last_intervene_run = None
    last_intervene_at = None

    try:
        while not stop["now"]:
            tick = time.time()
            now = datetime.now()

            cam_reading = CameraState.reduce(cam_state.raw_burst())
            spot = place(cam_reading, cfg.get("trust_phone_detection", False))
            screen = screen_sample(screen_clf)
            mode, why = resolve_mode(spot, screen, now, cfg)

            closed = logger.observe(mode, why, now)
            if closed:
                print(f"\r  {closed['start'][11:16]}-{closed['end'][11:16]}  "
                      f"{closed['minutes']:>5.1f}m  {closed['mode']:<17} "
                      f"{closed['why'][:40]}")

            run_start = logger.current["start"] if logger.current else None
            held = (now - run_start).total_seconds() if run_start else 0
            fire, reason = should_intervene(mode, held, now, cfg)
            if fire:
                is_new_run = (run_start != last_intervene_run)
                cooled_down = (last_intervene_at is None or
                              (now - last_intervene_at).total_seconds()
                              >= INTERVENE_COOLDOWN_MINUTES * 60)
                if is_new_run or cooled_down:
                    print(f"\r  [intervene] {reason}")
                    fire_watcher_card(reason, cfg)
                    last_intervene_run = run_start
                    last_intervene_at = now

            print(f"\r  {now:%H:%M:%S}  {mode:<17} {spot:<16} "
                  f"{screen['category']:<10} {int(held//60)}m   ",
                  end="", flush=True)

            slept = time.time() - tick
            if slept < interval:
                time.sleep(interval - slept)
    finally:
        closed = logger.close(datetime.now())
        cam.release()
        if closed:
            print(f"\n\n[*] Flushed: {closed['mode']} for {closed['minutes']:.1f} min")
        print("[*] Stopped. See: python src/mode_log.py today")
    return 0


if __name__ == "__main__":
    sys.exit(main())
