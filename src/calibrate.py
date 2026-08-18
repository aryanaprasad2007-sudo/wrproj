"""
Calibration capture.

Walks you through a set of poses, records what the local detector says for
each, and prints a table showing which signals actually separate them. The
point is to replace guesses with measurements before any rule gets wired to
the screen flash.

Run it yourself in a terminal (it waits for you to press Enter between poses):

    python src/calibrate.py

Output:
  calibration/samples.csv   every frame's raw signals, for re-analysis
  calibration/<pose>_N.jpg  sample frames, so you can see what it saw
"""
import csv
import os
import time
from collections import Counter

import cv2

from capture import Camera
from local_detector import LocalDetector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "calibration")

BED_CLASS_ID = 59      # "bed" in COCO
COUCH_CLASS_ID = 57    # "couch" -- YOLO sometimes calls a bed a couch

SECONDS_PER_POSE = 15
INTERVAL = 0.5
SAMPLE_FRAMES = 3      # jpgs saved per pose

POSES = [
    ("working",
     "Sit at your desk and work normally. Look at your screen, type, read."),
    ("turned_away",
     "Stay in the chair but turn away from the monitor, as if talking to\n"
     "     someone behind you."),
    ("head_down",
     "Stay in the chair, head down, looking into your lap as if scrolling\n"
     "     your phone. (Your phone IS the camera, so YOLO can't see it --\n"
     "     this pose is what 'on my phone' actually looks like to this rig.)"),
    ("in_bed",
     "Go lie down on the bed."),
    ("away",
     "Leave the chair and step out of frame entirely."),
]


def box_overlap_fraction(inner, outer):
    """How much of `inner` sits inside `outer`, 0.0-1.0."""
    if inner is None or outer is None:
        return 0.0
    ax1, ay1, ax2, ay2 = inner
    bx1, by1, bx2, by2 = outer
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area = (ax2 - ax1) * (ay2 - ay1)
    return inter / area if area else 0.0


def scan_furniture(detector, frame):
    """Return the largest bed/couch box in frame, or None."""
    if detector.yolo is None:
        return None
    best, best_area = None, 0
    for r in detector.yolo.predict(frame, verbose=False, conf=0.30):
        for b in r.boxes:
            if int(b.cls[0]) in (BED_CLASS_ID, COUCH_CLASS_ID):
                x1, y1, x2, y2 = (int(v) for v in b.xyxy[0])
                area = (x2 - x1) * (y2 - y1)
                if area > best_area:
                    best, best_area = (x1, y1, x2, y2), area
    return best


def capture_pose(cam, detector, name, writer, save_every):
    rows = []
    deadline = time.time() + SECONDS_PER_POSE
    i = 0
    while time.time() < deadline:
        frame = cam.grab()
        if frame is None:
            time.sleep(0.2)
            continue

        person_box, phone, phone_conf = detector._yolo_scan(frame)
        head_found, facing = (False, None)
        if person_box is not None:
            head_found, facing = detector._find_head(frame, person_box)
        verdict, conf, reason = detector.classify(frame)

        furniture = scan_furniture(detector, frame)
        overlap = box_overlap_fraction(person_box, furniture)

        row = {
            "pose": name,
            "verdict": verdict,
            "reason": reason,
            "person": person_box is not None,
            "head_found": head_found,
            "facing": facing or "",
            "phone": phone,
            "furniture_overlap": round(overlap, 3),
        }
        rows.append(row)
        writer.writerow(row)

        if i % save_every == 0 and i // save_every < SAMPLE_FRAMES:
            path = os.path.join(OUTDIR, f"{name}_{i // save_every}.jpg")
            cv2.imwrite(path, frame)

        i += 1
        print(f"  {verdict:<11} head={head_found!s:<5} facing={facing or '-':<7} "
              f"overlap={overlap:.2f}")
        time.sleep(INTERVAL)
    return rows


def summarize(all_rows):
    print("\n" + "=" * 74)
    print("CALIBRATION SUMMARY")
    print("=" * 74)
    header = f"{'pose':<13}{'n':>3}  {'verdicts':<34}{'head':>6}{'facing':>18}"
    print(header)
    print("-" * 74)

    for name, _ in POSES:
        rows = [r for r in all_rows if r["pose"] == name]
        if not rows:
            print(f"{name:<13}  0  (no samples)")
            continue
        n = len(rows)
        verdicts = Counter(r["verdict"] for r in rows)
        vtxt = " ".join(f"{k}:{v}" for k, v in verdicts.most_common())
        head_rate = sum(r["head_found"] for r in rows) / n
        facings = Counter(r["facing"] for r in rows if r["facing"])
        ftxt = " ".join(f"{k}:{v}" for k, v in facings.most_common()) or "-"
        overlap = sum(r["furniture_overlap"] for r in rows) / n
        print(f"{name:<13}{n:>3}  {vtxt:<34}{head_rate:>5.0%}{ftxt:>18}")
        if overlap > 0.05:
            print(f"{'':<16}mean furniture overlap: {overlap:.2f}")

    print("-" * 74)
    print("""
What to look for:

  * 'working' should be mostly 'productive'. If it isn't, the head detector
    is missing you at your real working posture -- that's the thing to fix
    first, since it's the pose you'll be in most.

  * 'turned_away' and 'head_down' should NOT read 'productive'. If they do,
    the detector can't tell working from not working, and no streak policy
    downstream can rescue that.

  * Compare the 'facing' column between 'working' and 'turned_away'. If they
    differ consistently, head direction is a usable signal and we can wire it
    in. If they're the same, it isn't -- and we drop the idea rather than
    build a rule on noise.

  * 'in_bed' furniture overlap should be high, and clearly higher than the
    chair poses. If so, "lying in bed" is directly detectable and becomes the
    strongest lazy signal this camera angle offers.

  * 'away' should be 'away' every time. Any 'productive' there means
    something in the room is being mistaken for you.
""")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    save_every = max(1, int(SECONDS_PER_POSE / INTERVAL) // SAMPLE_FRAMES)

    print("Loading detector...")
    detector = LocalDetector()
    cam = Camera(0)
    print(f"Camera connected via {cam.backend_name}.\n")
    print(f"{len(POSES)} poses, {SECONDS_PER_POSE}s each. Hold each one steady.\n")

    csv_path = os.path.join(OUTDIR, "samples.csv")
    all_rows = []
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "pose", "verdict", "reason", "person", "head_found",
            "facing", "phone", "furniture_overlap",
        ])
        writer.writeheader()
        try:
            for name, instruction in POSES:
                print(f"\n=== {name} ===")
                print(f"  -> {instruction}")
                input("     Press Enter when you're in position (3s grace, then recording)...")
                for k in (3, 2, 1):
                    print(f"     {k}...")
                    time.sleep(1)
                print(f"     recording {SECONDS_PER_POSE}s")
                all_rows += capture_pose(cam, detector, name, writer, save_every)
        except KeyboardInterrupt:
            print("\n[*] Stopped early -- summarizing what was captured.")
        finally:
            cam.release()

    summarize(all_rows)
    print(f"Raw samples: {csv_path}")
    print(f"Sample frames: {OUTDIR}")


if __name__ == "__main__":
    main()
