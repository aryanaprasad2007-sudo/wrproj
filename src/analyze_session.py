"""
Replay detectors over recorded footage.

Because this reads a file rather than the camera, it is re-runnable and fair:
every detector sees the identical frames at the identical timestamps, so
"pose beats Haar" becomes a measurement instead of an impression.

    py -3.12 src/analyze_session.py latest --both
    py -3.12 src/analyze_session.py class.mp4 --pose --every 5

    --haar    face cascade + person box (the original)
    --pose    YOLOv8 keypoints; adds posture, so it can see lying down
    --both    run both on the same frames and report where they disagree
    --every N seconds between samples (default 3)

Sampling takes a BURST of consecutive frames rather than one, because that is
what production does -- a single frame is a noisy measurement. Recorded footage
gives bursts for free: consecutive frames in the file already are one.

Outputs (into sessions/<name>_analysis/):
    timeline.csv     one row per burst
    sheet_N.jpg      contact sheets for labelling
"""
import csv
import os
import sys
from collections import Counter

import cv2
import numpy as np

from camera_state import BURST_FRAMES, CameraState
from camera_state import place as haar_place
from local_detector import LocalDetector
from pose_detector import PoseDetector
from pose_detector import place as pose_place

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS = os.path.join(ROOT, "sessions")

DEFAULT_EVERY = 3
THUMB_SECONDS = 30

# Phone footage is 4K, and that hurts twice over. YOLO resizes to 640
# internally so the extra pixels buy nothing there, but the Haar cascade runs
# on the full-resolution person crop -- measured at 523 ms/frame on 4K versus
# 75 ms at 720p, with *higher* confidence downscaled. Anything already smaller
# than this is left alone.
MAX_WIDTH = 1280
GRID_COLS, GRID_ROWS = 8, 8
THUMB_W, THUMB_H = 200, 150
LABEL_H = 22

PLACE_COLORS = {                    # BGR
    "at_desk": (90, 170, 90),
    "lying_down": (170, 120, 60),
    "reclined": (180, 150, 70),
    "on_phone": (60, 60, 200),
    "absent": (150, 150, 150),
    "present_unclear": (60, 160, 220),
}


def resolve_video(arg):
    if arg == "latest":
        vids = sorted(f for f in os.listdir(SESSIONS) if f.endswith(".mp4")) \
            if os.path.isdir(SESSIONS) else []
        if not vids:
            raise SystemExit("No recordings in sessions/")
        return os.path.join(SESSIONS, vids[-1])
    path = arg if os.path.isabs(arg) else os.path.join(SESSIONS, arg)
    if not os.path.exists(path):
        raise SystemExit(f"Not found: {path}")
    return path


def hms(seconds):
    return f"{int(seconds)//60:02d}:{int(seconds)%60:02d}"


def reduce_burst(frames):
    """
    Vote a burst down to one reading. Thin alias for CameraState.reduce.

    This used to be its own implementation, and that was the bug: posture was
    voted HERE and nowhere else, so replays saw posture while the live
    pipeline never did -- making `reclined` and `lying_down` unreachable in
    mode_log.py and the dashboard even though the replays produced them
    happily. Two reducers meant the thing being scored was not the thing being
    run. The logic now lives in CameraState.reduce; this name stays so the
    replay code reads the same as before.
    """
    return CameraState.reduce(frames)


def analyze(video_path, use_haar, use_pose, every):
    name = os.path.splitext(os.path.basename(video_path))[0]
    outdir = os.path.join(SESSIONS, f"{name}_analysis")
    os.makedirs(outdir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"Could not open {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 5.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_every = max(BURST_FRAMES, int(round(fps * every)))
    n_bursts = max(1, total // sample_every)

    print(f"[*] {os.path.basename(video_path)}: {total} frames @ {fps:g}fps "
          f"({hms(total / fps)})")
    print(f"[*] {n_bursts} bursts of {BURST_FRAMES} = "
          f"{n_bursts * BURST_FRAMES} inferences per detector")

    detectors = {}
    if use_haar:
        print("[*] loading Haar detector ...")
        detectors["haar"] = (LocalDetector(), haar_place)
    if use_pose:
        print("[*] loading pose detector (downloads ~6.5MB on first use) ...")
        detectors["pose"] = (PoseDetector(), pose_place)

    # torch here is the CPU-only build. Measured per-frame costs at 720p:
    # haar ~75ms, pose ~32ms; plus ~320ms to seek and read each burst.
    per_frame = (0.075 if use_haar else 0) + (0.032 if use_pose else 0)
    est = (n_bursts * (0.32 + BURST_FRAMES * per_frame)) / 60
    print(f"[*] rough estimate: {est:.0f} min on CPU. Ctrl+C is safe.\n")

    rows = []
    thumbs = []
    thumb_every_bursts = max(1, int(round(THUMB_SECONDS / every)))

    # Seek to each burst rather than decoding the whole file. Reading every
    # frame of 24 minutes of 4K just to sample 300 of them costs 24 minutes of
    # pure decoding; seeking costs about 1.5. The frames within a burst are
    # still read consecutively, which is what makes them a burst.
    starts = list(range(0, max(1, total - BURST_FRAMES), sample_every))
    try:
        for b_i, start in enumerate(starts):
            cap.set(cv2.CAP_PROP_POS_FRAMES, start)
            burst = []
            for _ in range(BURST_FRAMES):
                ok, frame = cap.read()
                if not ok:
                    break
                if frame.shape[1] > MAX_WIDTH:
                    scale = MAX_WIDTH / frame.shape[1]
                    frame = cv2.resize(frame, (MAX_WIDTH, int(frame.shape[0] * scale)))
                burst.append(frame)

            if burst:
                t = start / fps
                row = {"t_seconds": round(t, 1), "time": hms(t)}
                headline = None

                for key, (det, placer) in detectors.items():
                    obs = [det.observe(f) for f in burst]
                    red = reduce_burst(obs)
                    single = placer(reduce_burst(obs[:1]))   # 1-frame baseline
                    p = placer(red)
                    headline = headline or p
                    row.update({
                        f"{key}_place": p,
                        f"{key}_place_1frame": single,
                        f"{key}_present": red["present"],
                        f"{key}_head": red["head_up"],
                        f"{key}_posture": red["posture"],
                        f"{key}_angle": red["torso_angle"],
                        f"{key}_facing": red["facing"] or "",
                        f"{key}_phone": red["phone"],
                    })

                rows.append(row)
                if b_i % thumb_every_bursts == 0:
                    thumbs.append((hms(t), headline, burst[0].copy()))
                if len(rows) % 10 == 0:
                    done = (b_i + 1) / len(starts)
                    print(f"\r  {hms(t)} / {hms(total / fps)}  "
                          f"({len(rows)} bursts, {done:.0%})", end="", flush=True)
    except KeyboardInterrupt:
        print("\n[*] Stopped early -- writing what was analyzed so far.")
    finally:
        cap.release()

    if not rows:
        raise SystemExit("No bursts analyzed.")
    print(f"\r  {len(rows)} bursts analyzed{' ' * 30}\n")

    csv_path = os.path.join(outdir, "timeline.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    sheets = build_sheets(thumbs, outdir)
    report(rows, sheets, csv_path, list(detectors), every)


def build_sheets(thumbs, outdir):
    per_sheet = GRID_COLS * GRID_ROWS
    paths = []
    for s in range(0, len(thumbs), per_sheet):
        chunk = thumbs[s:s + per_sheet]
        rows_needed = (len(chunk) + GRID_COLS - 1) // GRID_COLS
        canvas = np.full((rows_needed * (THUMB_H + LABEL_H),
                          GRID_COLS * THUMB_W, 3), 25, dtype="uint8")
        for i, (t, label, frame) in enumerate(chunk):
            r, c = divmod(i, GRID_COLS)
            y, x = r * (THUMB_H + LABEL_H), c * THUMB_W
            canvas[y + LABEL_H:y + LABEL_H + THUMB_H, x:x + THUMB_W] = \
                cv2.resize(frame, (THUMB_W, THUMB_H))
            color = PLACE_COLORS.get(label, (200, 200, 200))
            cv2.rectangle(canvas, (x, y), (x + THUMB_W, y + LABEL_H), color, -1)
            cv2.putText(canvas, f"{i + s:>3} {t} {label}", (x + 4, y + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)
        path = os.path.join(outdir, f"sheet_{s // per_sheet}.jpg")
        cv2.imwrite(path, canvas)
        paths.append(path)
    return paths


def flips(values):
    return sum(1 for a, b in zip(values, values[1:]) if a != b)


def runs_of(rows, key, every):
    out = []
    if not rows:
        return out
    cur, start = rows[0][key], rows[0]["t_seconds"]
    for prev, row in zip(rows, rows[1:]):
        if row[key] != cur:
            out.append((cur, start, prev["t_seconds"] - start + every))
            cur, start = row[key], row["t_seconds"]
    out.append((cur, start, rows[-1]["t_seconds"] - start + every))
    return out


def report(rows, sheets, csv_path, keys, every):
    n = len(rows)
    print("=" * 70)
    print("SESSION ANALYSIS")
    print("=" * 70)

    for key in keys:
        col = f"{key}_place"
        print(f"\n[{key}]")
        counts = Counter(r[col] for r in rows)
        print(f"  {'place':<18}{'bursts':>8}{'share':>8}{'wall':>10}")
        print("  " + "-" * 44)
        for p, c in counts.most_common():
            print(f"  {p:<18}{c:>8}{c/n:>7.0%}{hms(c * every):>10}")

        f_burst = flips([r[col] for r in rows])
        f_single = flips([r[f"{key}_place_1frame"] for r in rows])
        print(f"  flicker: {f_single} flips single-frame -> {f_burst} with "
              f"{BURST_FRAMES}-frame burst")

        postures = Counter(r[f"{key}_posture"] for r in rows
                           if r[f"{key}_posture"] != "unknown")
        if postures:
            print(f"  posture: {dict(postures)}")
        angles = [r[f"{key}_angle"] for r in rows if r[f"{key}_angle"] is not None]
        if angles:
            angles.sort()
            print(f"  torso angle: median {angles[len(angles)//2]:.0f}deg  "
                  f"range {angles[0]:.0f}-{angles[-1]:.0f}")

        print(f"  longest stretches:")
        runs = runs_of(rows, col, every)
        for p in counts:
            top = sorted((r for r in runs if r[0] == p), key=lambda r: -r[2])[:2]
            if top:
                print(f"    {p:<18}" +
                      ", ".join(f"{hms(d)} at {hms(s)}" for _, s, d in top))

    if len(keys) == 2:
        a, b = keys
        agree = sum(1 for r in rows if r[f"{a}_place"] == r[f"{b}_place"])
        print(f"\n[{a} vs {b}]")
        print(f"  agree on {agree}/{n} bursts ({agree/n:.0%})")
        disagree = Counter((r[f"{a}_place"], r[f"{b}_place"])
                           for r in rows if r[f"{a}_place"] != r[f"{b}_place"])
        if disagree:
            print(f"  {'haar says':<18}{'pose says':<18}{'bursts':>7}")
            print("  " + "-" * 45)
            for (pa, pb), c in disagree.most_common(8):
                print(f"  {pa:<18}{pb:<18}{c:>7}")
            print("\n  Every row above is a frame where they cannot both be right.")
            print("  The contact sheets are how you settle it.")

    print(f"""
{'=' * 70}
NEXT: label the contact sheets.

Each tile shows its index, timestamp, and what the detector decided. Tell me
the indices it got WRONG and what you were actually doing -- e.g.
"40-58 I was in bed watching anime", "72 I'd left the room".

That is ground truth. From there any threshold change can be scored against
this exact session instead of guessed.
""")
    for p in sheets:
        print(f"  {p}")
    print(f"\n  timeline: {csv_path}")


def calibrate(video_path, samples=40):
    """
    Measure what "sitting upright" looks like on this camera.

    Record yourself sitting normally at the desk, then run this. The modal
    signed torso angle IS the baseline -- no protractor, no measuring the
    mount. Re-run it whenever the camera moves, which on a phone mount is
    often.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"Could not open {video_path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"[*] sampling {samples} frames from {os.path.basename(video_path)} ...")
    det = PoseDetector(phone_model=None)
    angles = []
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        if frame.shape[1] > MAX_WIDTH:
            scale = MAX_WIDTH / frame.shape[1]
            frame = cv2.resize(frame, (MAX_WIDTH, int(frame.shape[0] * scale)))
        o = det.observe(frame)
        if o["present"] and o["torso_angle"] is not None:
            angles.append(o["torso_angle"])
    cap.release()

    if len(angles) < samples // 4:
        print(f"[!] Only {len(angles)}/{samples} frames gave a shoulder+hip pair.")
        print("    Too few to calibrate -- is the person visible and seated?")
        return 1

    angles.sort()
    median = angles[len(angles) // 2]
    spread = angles[int(len(angles) * 0.84)] - angles[int(len(angles) * 0.16)]

    print(f"\n  {len(angles)}/{samples} frames usable")
    print(f"  median  {median:+.0f} deg")
    print(f"  spread  {spread:.0f} deg (68% of samples)\n")
    hist = {}
    for a in angles:
        hist[int(a // 10) * 10] = hist.get(int(a // 10) * 10, 0) + 1
    for b in sorted(hist):
        print(f"   {b:+4d}..{b+10:+4d}  {'#' * hist[b]} {hist[b]}")

    print(f"\n  -> set UPRIGHT_TORSO_ANGLE = {median:.0f} in src/pose_detector.py")
    if spread > 40:
        print("\n  [!] Spread is wide. Either the camera moved during this clip, or")
        print("      the footage includes real posture changes. Calibrate on a clip")
        print("      where you stay seated and upright throughout.")
    return 0


def main():
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        return 1

    if "--calibrate" in args:
        args.remove("--calibrate")
        pos = [a for a in args if not a.startswith("--")]
        if not pos:
            print("[!] Give a video filename, or 'latest'.")
            return 1
        return calibrate(resolve_video(pos[0]))

    every = DEFAULT_EVERY
    if "--every" in args:
        i = args.index("--every")
        every = float(args[i + 1])
        del args[i:i + 2]

    use_pose = "--pose" in args or "--both" in args
    use_haar = "--haar" in args or "--both" in args or not use_pose
    positional = [a for a in args if not a.startswith("--")]
    if not positional:
        print("[!] Give a video filename, or 'latest'.")
        return 1

    analyze(resolve_video(positional[0]), use_haar, use_pose, every)
    return 0


if __name__ == "__main__":
    sys.exit(main())
