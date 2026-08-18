"""
Claude-in-the-chat as the detector, for one day.

This replaces claude_judge.py's design, not just its model. The old judge sent
ONE frame to the API and asked for one word ("productive"/"lazy") -- which is
both the abandoned punisher vocabulary and the worst possible use of a vision
model: maximum cost per frame, minimum context, no memory between calls.

The economics force a different shape. A frame read in chat costs roughly 1.1k
tokens at 960px. The local detector samples every 15s, which is 240 frames an
hour -- ~260k tokens/hour of pure image, and that is before any reasoning. So
frame-at-a-time is off the table permanently, not just today.

What IS cheap is BREADTH. A 6x5 contact sheet puts 30 timestamps in a single
read for about the price of one frame, and a whole 24-minute session fits in
two reads. That inverts the division of labour:

    local detector  cheap per frame, blind to its own failure modes
    Claude in chat  expensive per frame, sees a whole session at once and
                    can notice that a third of it is mislabelled the same way

So this module never asks Claude to run the timeline. It asks Claude to LABEL
it, and the labels become the ground truth every future detector change is
scored against (open item #5). One day of looking, permanent regression tests.

    py -3.12 src/claude_eyes.py live                    # look at me right now
    py -3.12 src/claude_eyes.py sheet IMG_9874.mp4      # blind sheets to label
    py -3.12 src/claude_eyes.py sheet latest --audit    # sheets WITH the guess
    py -3.12 src/claude_eyes.py score IMG_9874          # labels.json vs detectors

Nothing here uploads anything. The sheets are written to disk and read by
whatever is looking at this repo -- which today is a chat session.
"""
import csv
import json
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS = os.path.join(ROOT, "sessions")

# Grid geometry. 8x8 at 200x150 (analyze_session.py's sheet) was measured as
# readable for presence and place, but posture is marginal at that size -- a
# 200px-wide torso is a few dozen pixels of shoulder-to-hip. 6x5 at 320x240
# trades 34 tiles per read for tiles you can actually judge a lean from.
GRID_COLS, GRID_ROWS = 6, 5
THUMB_W, THUMB_H = 320, 240
LABEL_H = 26
SHEET_MAX_W = 1920          # beyond this the sheet is downscaled on read anyway

# What Claude is allowed to say. Deliberately NOT the detector's vocabulary:
# `present_unclear` is absent because it does not describe a scene, it
# describes a cascade miss. When the image genuinely cannot settle it, that is
# `unsure` -- a different claim, and one that should stay rare enough to notice.
TRUTH_PLACES = ("at_desk", "reclined", "lying_down", "absent", "on_phone", "unsure")

PLACE_COLORS = {                    # BGR, matching analyze_session.py
    "at_desk": (90, 170, 90),
    "lying_down": (170, 120, 60),
    "reclined": (180, 150, 70),
    "on_phone": (60, 60, 200),
    "absent": (150, 150, 150),
    "present_unclear": (60, 160, 220),
}


def hms(seconds):
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def parse_ts(text):
    """Accept 90, '90', or 'MM:SS'."""
    text = str(text)
    if ":" in text:
        m, s = text.split(":")
        return int(m) * 60 + float(s)
    return float(text)


def resolve_video(arg):
    if arg == "latest":
        vids = sorted(f for f in os.listdir(SESSIONS)
                      if f.lower().endswith((".mp4", ".mkv", ".mov"))) \
            if os.path.isdir(SESSIONS) else []
        if not vids:
            raise SystemExit("No recordings in sessions/")
        return os.path.join(SESSIONS, vids[-1])
    path = arg if os.path.isabs(arg) else os.path.join(SESSIONS, arg)
    if not os.path.exists(path):
        raise SystemExit(f"Not found: {path}")
    return path


# --------------------------------------------------------------------------
# sheets
# --------------------------------------------------------------------------

def build_sheets(tiles, outdir, stem="sheet"):
    """
    Lay tiles out into contact sheets and write a manifest beside them.

    `tiles` is a list of (t_seconds, caption, color_or_None, frame).

    The manifest is the part that matters and the part the original sheets
    lacked. Without it the timestamp of tile 37 exists only as pixels burned
    into a JPEG, so a label like "37 was me in bed" cannot be joined back to
    timeline.csv by anything but a human retyping it.
    """
    per_sheet = GRID_COLS * GRID_ROWS
    paths, manifest = [], []

    for s in range(0, len(tiles), per_sheet):
        chunk = tiles[s:s + per_sheet]
        rows_needed = (len(chunk) + GRID_COLS - 1) // GRID_COLS
        canvas = np.full((rows_needed * (THUMB_H + LABEL_H),
                          GRID_COLS * THUMB_W, 3), 25, dtype="uint8")

        for i, (t, caption, color, frame) in enumerate(chunk):
            idx = i + s
            r, c = divmod(i, GRID_COLS)
            y, x = r * (THUMB_H + LABEL_H), c * THUMB_W
            canvas[y + LABEL_H:y + LABEL_H + THUMB_H, x:x + THUMB_W] = \
                cv2.resize(frame, (THUMB_W, THUMB_H))
            # Neutral grey bar when blind. A coloured bar is itself a hint --
            # you can read the detector's answer off a sheet without reading a
            # single word, so the colour has to go too, not just the text.
            bar = color if color is not None else (70, 70, 70)
            ink = (20, 20, 20) if color is not None else (235, 235, 235)
            cv2.rectangle(canvas, (x, y), (x + THUMB_W, y + LABEL_H), bar, -1)
            cv2.putText(canvas, caption, (x + 6, y + 19),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, ink, 1, cv2.LINE_AA)
            manifest.append({"tile": idx, "t_seconds": round(t, 1),
                             "time": hms(t), "sheet": s // per_sheet})

        if canvas.shape[1] > SHEET_MAX_W:
            scale = SHEET_MAX_W / canvas.shape[1]
            canvas = cv2.resize(canvas, (SHEET_MAX_W,
                                         int(canvas.shape[0] * scale)))
        path = os.path.join(outdir, f"{stem}_{s // per_sheet}.jpg")
        cv2.imwrite(path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
        paths.append(path)

    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"tiles": manifest, "grid": [GRID_COLS, GRID_ROWS]}, f, indent=2)
    return paths


def sheet_from_video(video_path, every, audit, t_from, t_to):
    """
    Sample footage into sheets sized for reading in one chat message.

    `audit=False` (the default) writes BLIND tiles: index and timestamp only,
    neutral bar. That is not decoration, it is the whole point -- a tile that
    already says "at_desk" pulls the judgement toward at_desk, and ground truth
    contaminated by the thing it is meant to score is worthless.

    `audit=True` prints the detector's call, which is the right mode when you
    are hunting for WHERE it is wrong rather than establishing what is true.
    """
    name = os.path.splitext(os.path.basename(video_path))[0]
    outdir = os.path.join(SESSIONS, f"{name}_analysis")
    os.makedirs(outdir, exist_ok=True)

    guesses = {}
    if audit:
        csv_path = os.path.join(outdir, "timeline.csv")
        if not os.path.exists(csv_path):
            raise SystemExit(f"--audit needs {csv_path}; run analyze_session.py first.")
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = row.get("pose_place") or row.get("haar_place")
                guesses[round(float(row["t_seconds"]))] = key

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"Could not open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / fps

    start_s = t_from if t_from is not None else 0.0
    end_s = t_to if t_to is not None else duration
    step = max(1, int(round(fps * every)))

    print(f"[*] {os.path.basename(video_path)}: {hms(duration)} @ {fps:g}fps")
    print(f"[*] sampling {hms(start_s)}-{hms(end_s)} every {every}s "
          f"-> ~{int((end_s - start_s) / every)} tiles, "
          f"{'AUDIT (guess shown)' if audit else 'BLIND'}")

    tiles = []
    for frame_no in range(int(start_s * fps), int(end_s * fps), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok:
            break
        t = frame_no / fps
        if audit:
            g = guesses.get(round(t), "?")
            tiles.append((t, f"{len(tiles):>3} {hms(t)} {g}",
                          PLACE_COLORS.get(g, (200, 200, 200)), frame))
        else:
            tiles.append((t, f"{len(tiles):>3}  {hms(t)}", None, frame))
    cap.release()

    if not tiles:
        raise SystemExit("No frames sampled -- check --from/--to.")

    stem = "audit" if audit else "blind"
    paths = build_sheets(tiles, outdir, stem)
    print(f"\n  {len(tiles)} tiles across {len(paths)} sheet(s):")
    for p in paths:
        print(f"    {p}")
    print(f"    {os.path.join(outdir, 'manifest.json')}")
    print(f"\n  Ask Claude to read the sheet(s) and label them. Vocabulary:")
    print(f"    {', '.join(TRUTH_PLACES)}")
    print(f"  Then save the reply as {os.path.join(outdir, 'labels.json')} "
          f"and run:\n    py -3.12 src/claude_eyes.py score {name}\n")
    return 0


def sheet_from_camera(frames, spread):
    """
    Look at the room right now.

    Spreading N frames over `spread` seconds rather than grabbing them
    back-to-back is what makes this a sample of a MOMENT instead of a burst.
    A burst answers "is the detector flickering"; a spread answers "what is he
    doing", which is the question a live look is actually for.
    """
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from capture import Camera

    stamp = datetime.now()
    outdir = os.path.join(SESSIONS, f"live_{stamp:%Y%m%d_%H%M%S}")
    os.makedirs(outdir, exist_ok=True)

    cam = Camera(0)
    print(f"[*] camera on {cam.backend_name}, {frames} frames over {spread}s")
    gap = spread / max(1, frames - 1) if frames > 1 else 0

    tiles = []
    t0 = time.time()
    for i in range(frames):
        frame = cam.grab()
        if frame is None:
            cam.reconnect()
            frame = cam.grab()
        if frame is None:
            print(f"[!] lost the camera at frame {i}")
            break
        elapsed = time.time() - t0
        clock = datetime.now()
        tiles.append((elapsed, f"{i:>2}  {clock:%H:%M:%S}", None, frame))
        if i < frames - 1 and gap:
            time.sleep(gap)
    cam.release()

    if not tiles:
        raise SystemExit("No frames captured.")
    paths = build_sheets(tiles, outdir, "live")
    print(f"\n  {len(tiles)} frames:")
    for p in paths:
        print(f"    {p}")
    print()
    return 0


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def load_labels(outdir):
    """
    Read labels.json, accepting either shape.

        {"ranges": [{"from": "00:00", "to": "12:30", "place": "at_desk"}, ...]}
        {"tiles":  {"0": "at_desk", "1": "absent", ...}}

    Tiles are what you naturally produce from a contact sheet; ranges are what
    you naturally produce from a memory ("I was in bed from 40 to 58"). Both
    resolve to the same thing: a function from t_seconds to a true place.
    """
    path = os.path.join(outdir, "labels.json")
    if not os.path.exists(path):
        raise SystemExit(f"No labels at {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    spans = []
    for r in data.get("ranges", []):
        spans.append((parse_ts(r["from"]), parse_ts(r["to"]), r["place"]))

    if data.get("tiles"):
        man_path = os.path.join(outdir, "manifest.json")
        if not os.path.exists(man_path):
            raise SystemExit(f"tiles: labels need {man_path}")
        with open(man_path, encoding="utf-8") as f:
            by_tile = {t["tile"]: t["t_seconds"]
                       for t in json.load(f)["tiles"]}
        stamps = sorted(by_tile.values())
        # A tile stands for the interval up to the next tile, not for an
        # instant -- otherwise every label would cover one frame and score
        # essentially nothing.
        for tile, place_ in data["tiles"].items():
            t = by_tile.get(int(tile))
            if t is None:
                continue
            later = [s for s in stamps if s > t]
            spans.append((t, later[0] if later else t + 1, place_))

    bad = sorted({p for _, _, p in spans} - set(TRUTH_PLACES))
    if bad:
        raise SystemExit(f"Unknown place(s) in labels.json: {bad}\n"
                         f"Allowed: {', '.join(TRUTH_PLACES)}")
    spans.sort()
    return spans, data


def truth_at(spans, t):
    for lo, hi, place_ in spans:
        if lo <= t < hi:
            return place_
    return None


def score(name):
    outdir = os.path.join(SESSIONS, f"{name}_analysis")
    csv_path = os.path.join(outdir, "timeline.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"No timeline at {csv_path}")
    spans, meta = load_labels(outdir)

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    keys = [k[:-6] for k in rows[0] if k.endswith("_place")
            and not k.endswith("_1frame")]
    covered = [r for r in rows if truth_at(spans, float(r["t_seconds"]))]
    if not covered:
        raise SystemExit("Labels cover none of the timeline.")

    print("=" * 70)
    print(f"GROUND TRUTH: {name}")
    print(f"  labelled by : {meta.get('labeled_by', 'unspecified')}")
    print(f"  coverage    : {len(covered)}/{len(rows)} bursts")
    print("=" * 70)

    # `unsure` is excluded from the denominator. Scoring a detector against a
    # frame the judge could not read punishes it for the camera's failure, not
    # its own.
    scored = [r for r in covered
              if truth_at(spans, float(r["t_seconds"])) != "unsure"]
    n_unsure = len(covered) - len(scored)
    if n_unsure:
        print(f"\n  {n_unsure} burst(s) labelled 'unsure' -- excluded from scoring.")

    for key in keys:
        hits = 0
        confusion = {}
        for r in scored:
            true = truth_at(spans, float(r["t_seconds"]))
            got = r[f"{key}_place"]
            if got == true:
                hits += 1
            else:
                confusion[(true, got)] = confusion.get((true, got), 0) + 1
        acc = hits / len(scored) if scored else 0
        print(f"\n[{key}]  {hits}/{len(scored)} correct  ({acc:.0%})")
        if confusion:
            print(f"  {'truth':<18}{'said':<18}{'bursts':>7}")
            print("  " + "-" * 45)
            for (true, got), c in sorted(confusion.items(), key=lambda kv: -kv[1])[:8]:
                print(f"  {true:<18}{got:<18}{c:>7}")

    out = os.path.join(outdir, "score.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"session": name, "scored_bursts": len(scored),
                   "unsure": n_unsure,
                   "accuracy": {k: sum(
                       1 for r in scored
                       if r[f"{k}_place"] == truth_at(spans, float(r["t_seconds"]))
                   ) / len(scored) for k in keys}}, f, indent=2)
    print(f"\n  written: {out}")
    print("  This session is now a regression test. Any threshold change can be")
    print("  re-scored against it without labelling anything again.\n")
    return 0


# --------------------------------------------------------------------------
# today's resolver hook
# --------------------------------------------------------------------------

def arbitrate(local_place, claude_place, seconds_since_look):
    """
    Whose call goes in TODAY's log when the two disagree.

    >>> YOURS TO WRITE. <<<

    This is a values decision, not a technical one, which is why it is a stub
    like should_intervene() rather than something I picked for you.

    The tension: Claude sees the scene far better but looks rarely (a sheet
    every few minutes at best), so `claude_place` is high-quality and STALE.
    `local_place` is mediocre and current. Three defensible policies:

      trust-claude   Claude's label wins until the next look. Best labels,
                     but a 4-minute-old "at_desk" survives you leaving the room.
      tie-break      Claude only fills in where local says present_unclear.
                     Given the finding above -- present_unclear is 93/293
                     bursts and 80% of them are really at_desk -- this alone
                     would fix most of the damage, and it never overrides a
                     confident local reading with a stale one.
      decay          Claude wins while fresh, then hands back. Needs you to
                     decide what "fresh" is, and that number is the whole
                     policy.

    Args:
        local_place:          place() output this tick, e.g. "present_unclear"
        claude_place:         most recent Claude label, or None if never looked
        seconds_since_look:   age of claude_place, or None

    Returns:
        (place, source) -- source is "local" or "claude", and goes in the log's
        `why` so any run can be traced to who decided it.
    """
    # Stub: local always wins, so nothing silently changes until you choose.
    return local_place, "local"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd, rest = args[0], args[1:]

    def flag_value(name, cast, default):
        if name in rest:
            i = rest.index(name)
            val = cast(rest[i + 1])
            del rest[i:i + 2]
            return val
        return default

    if cmd == "live":
        frames = flag_value("--frames", int, 6)
        spread = flag_value("--spread", float, 25.0)
        return sheet_from_camera(frames, spread)

    if cmd == "sheet":
        every = flag_value("--every", float, 30.0)
        t_from = flag_value("--from", parse_ts, None)
        t_to = flag_value("--to", parse_ts, None)
        audit = "--audit" in rest
        rest[:] = [a for a in rest if not a.startswith("--")]
        if not rest:
            print("[!] Give a video filename, or 'latest'.")
            return 1
        return sheet_from_video(resolve_video(rest[0]), every, audit, t_from, t_to)

    if cmd == "score":
        if not rest:
            print("[!] Give a session name, e.g. IMG_9874")
            return 1
        return score(rest[0])

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
