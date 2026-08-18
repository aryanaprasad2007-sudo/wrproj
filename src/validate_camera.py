"""
Measure how wrong the camera actually is.

The detector's error rate was never measured -- an early 36-second look showed
the head cascade finding a head in only ~54% of frames while barely anything
moved, but nobody knows how much of that is real posture change and how much
is noise. This settles it with ground truth, which is obtained for free by
constraining the trial:

    present   sit at your desk and work; do not leave the room
    absent    leave the room entirely

For the length of the trial the truth is CONSTANT, so every reading that
disagrees is by construction an error. No frame labelling needed.

Each tick records a burst of MAX_BURST raw frames. Burst sizes are then
replayed offline against that same recording, so one sitting scores every
candidate size on identical data.

    python src/validate_camera.py present 3     # 3 min at the desk
    python src/validate_camera.py absent 1      # 1 min out of the room
    python src/validate_camera.py report <file> # re-score a saved run

Frames are never written to disk -- only the detector's numeric output.
"""
import json
import os
import sys
import time
from datetime import datetime

from camera_state import CameraState
from capture import Camera
from local_detector import LocalDetector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "validation")

MAX_BURST = 9          # record this many; replay every smaller size from it
BURST_SIZES = [1, 3, 5, 7, 9]
TICK_SECONDS = 4.0     # gap between bursts during the trial

TRUTHS = {
    "present": {
        "present": True,
        "brief": "Sit at your desk and work normally. Do NOT leave the room.",
    },
    "absent": {
        "present": False,
        "brief": "Leave the room. Come back when the timer is up.",
    },
}


def record(truth, minutes):
    os.makedirs(OUTDIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTDIR, f"{stamp}_{truth}.json")

    print(f"[*] Loading detector ...")
    detector = LocalDetector()
    if not detector.cascades_ok:
        print("[!] Haar cascades failed to load -- head detection will always be False.")
    cam = Camera(0)
    state = CameraState(cam, detector, burst=MAX_BURST)

    print(f"[*] Camera on {cam.backend_name}")
    print(f"\n    TRIAL: {truth}")
    print(f"    {TRUTHS[truth]['brief']}")
    print(f"    {minutes:g} minutes. Starting in 8 seconds -- get into position.\n")
    time.sleep(8)

    ticks = []
    total = minutes * 60
    t0 = time.time()
    try:
        while True:
            elapsed = time.time() - t0
            if elapsed >= total:
                break
            frames = state.raw_burst(MAX_BURST)
            ticks.append({"t": round(elapsed, 1), "frames": frames})

            r = CameraState.reduce(frames)
            remain = int(total - elapsed)
            print(f"\r  {int(elapsed)//60:02d}:{int(elapsed)%60:02d}  "
                  f"present={str(r['present']):<5} head={str(r['head_up']):<5} "
                  f"({r['frames']} frames)  {remain//60:02d}:{remain%60:02d} left   ",
                  end="", flush=True)
            time.sleep(max(0.0, TICK_SECONDS - (time.time() - t0 - elapsed)))
    except KeyboardInterrupt:
        print("\n[*] Stopped early.")
    finally:
        cam.release()

    run = {
        "truth": truth,
        "expected_present": TRUTHS[truth]["present"],
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "max_burst": MAX_BURST,
        "tick_seconds": TICK_SECONDS,
        "ticks": ticks,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(run, f)
    print(f"\n\n[*] {len(ticks)} bursts -> {path}")
    return path


def flips(values):
    """How many times the value changed between consecutive ticks."""
    return sum(1 for a, b in zip(values, values[1:]) if a != b)


def score(run):
    expected = run["expected_present"]
    ticks = run["ticks"]
    if not ticks:
        print("[!] No bursts recorded.")
        return

    print(f"\n  trial: {run['truth']}   truth: present={expected}   "
          f"{len(ticks)} bursts over {ticks[-1]['t']/60:.1f} min\n")
    print(f"  {'burst':>5}  {'present err':>11}  {'flips':>6}  "
          f"{'head found':>10}  {'head flips':>10}")
    print("  " + "-" * 52)

    rows = []
    for n in BURST_SIZES:
        if n > run["max_burst"]:
            continue
        # Production would take the first n frames of the burst, so do that.
        reduced = [CameraState.reduce(t["frames"][:n]) for t in ticks]
        pres = [r["present"] for r in reduced]
        head = [r["head_up"] for r in reduced]

        err = sum(1 for p in pres if p != expected) / len(pres)
        head_rate = sum(1 for h in head if h) / len(head)
        rows.append((n, err, flips(pres), head_rate, flips(head)))
        print(f"  {n:>5}  {err*100:>10.1f}%  {flips(pres):>6}  "
              f"{head_rate*100:>9.1f}%  {flips(head):>10}")

    print()
    # Rank on presence error first (that is correctness), then on TOTAL flicker
    # across both axes. Ranking on presence error alone would pick a burst size
    # that is accurate about the chair while still strobing on posture -- which
    # is the exact failure this whole exercise exists to fix.
    def cost(r):
        return (r[1], r[2] + r[4], r[0])

    best = min(rows, key=cost)
    single = rows[0]
    single_flicker = single[2] + single[4]
    best_flicker = best[2] + best[4]

    print(f"  Single frame: {single[1]*100:.1f}% wrong on presence, "
          f"{single_flicker} flips total.")
    if best[0] == 1:
        print("  Bursting did not help -- this error is not frame-to-frame noise.")
        print("  Look at the detector itself (angle, lighting, thresholds), not smoothing.")
    else:
        print(f"  Best burst: {best[0]} frames -> {best[1]*100:.1f}% wrong, "
              f"{best_flicker} flips total.")
        print(f"  Removed {single_flicker - best_flicker} of {single_flicker} flips, "
              f"costing ~{best[0]*0.2:.1f}s per sample out of a {15}s budget.")
        print(f"\n  -> set BURST_FRAMES = {best[0]} in src/camera_state.py")

    if run["truth"] == "present":
        print("\n  Note: 'head found' is a measurement, not an error rate -- you do")
        print("  genuinely turn away sometimes. The flip count is the noise signal.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == "report":
        if len(sys.argv) < 3:
            runs = sorted(f for f in os.listdir(OUTDIR)) if os.path.isdir(OUTDIR) else []
            if not runs:
                print("[!] No saved runs in validation/.")
                return 1
            path = os.path.join(OUTDIR, runs[-1])
        else:
            path = sys.argv[2]
            if not os.path.isabs(path):
                path = os.path.join(OUTDIR, path)
        with open(path, "r", encoding="utf-8") as f:
            score(json.load(f))
        return 0

    if cmd not in TRUTHS:
        print(f"[!] Unknown trial '{cmd}'. Use: {', '.join(TRUTHS)} or report")
        return 1

    minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    path = record(cmd, minutes)
    with open(path, "r", encoding="utf-8") as f:
        score(json.load(f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
