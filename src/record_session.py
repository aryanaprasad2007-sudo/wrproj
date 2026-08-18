"""
Record a real working session for offline analysis.

This deliberately does NOT run the detector while recording. Recording stays
dumb and reliable; analysis happens afterwards against the saved file, which
means every future detector change can be re-tested on the exact same footage
instead of needing a fresh sitting.

    python src/record_session.py            # 30 minutes
    python src/record_session.py 45         # 45 minutes

Ctrl+C stops early and still writes a valid file.

Video only -- no audio is captured at any point. Output stays on this machine
in sessions/ ; nothing is uploaded.
"""
import json
import os
import sys
import time
from datetime import datetime

import cv2

from capture import Camera

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "sessions")

FPS = 5              # production samples every 15s; 5fps leaves plenty of slack
DEFAULT_MINUTES = 30


def main():
    minutes = DEFAULT_MINUTES
    if len(sys.argv) > 1:
        try:
            minutes = float(sys.argv[1])
        except ValueError:
            print(f"Usage: python src/record_session.py [minutes]")
            return 1

    os.makedirs(OUTDIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = os.path.join(OUTDIR, f"{stamp}.mp4")
    meta_path = os.path.join(OUTDIR, f"{stamp}.json")

    cam = Camera(0)
    frame = cam.grab()
    if frame is None:
        print("[!] Could not read a first frame; is the Iriun phone app connected?")
        cam.release()
        return 1
    h, w = frame.shape[:2]
    print(f"[*] Camera on {cam.backend_name}, {w}x{h}")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(video_path, fourcc, FPS, (w, h))
    if not writer.isOpened():
        print(f"[!] Could not open video writer for {video_path}")
        cam.release()
        return 1

    total = minutes * 60
    period = 1.0 / FPS
    started = datetime.now()
    t0 = time.time()
    written = 0
    dropped = 0

    print(f"[*] Recording {minutes:g} min to {video_path}")
    print("[*] Just do your class normally. Ctrl+C to stop early.\n")

    try:
        while True:
            elapsed = time.time() - t0
            if elapsed >= total:
                break

            target = t0 + written * period
            sleep = target - time.time()
            if sleep > 0:
                time.sleep(sleep)

            frame = cam.grab()
            if frame is None:
                dropped += 1
                if dropped % 10 == 1:
                    print(f"\n[!] dropped {dropped} frames (wifi hiccup?)")
                continue

            writer.write(frame)
            written += 1

            if written % FPS == 0:  # once a second
                remain = total - elapsed
                print(f"\r  {int(elapsed)//60:02d}:{int(elapsed)%60:02d} elapsed  "
                      f"/  {int(remain)//60:02d}:{int(remain)%60:02d} left  "
                      f"({written} frames, {dropped} dropped)", end="", flush=True)

    except KeyboardInterrupt:
        print("\n[*] Stopped early.")
    finally:
        writer.release()
        cam.release()

    duration = time.time() - t0
    meta = {
        "video": os.path.basename(video_path),
        "started_at": started.isoformat(timespec="seconds"),
        "duration_seconds": round(duration, 1),
        "fps": FPS,
        "width": w,
        "height": h,
        "frames_written": written,
        "frames_dropped": dropped,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"\n\n[*] Wrote {written} frames ({duration/60:.1f} min, {size_mb:.0f} MB)")
    print(f"    {video_path}")
    if dropped:
        print(f"[!] {dropped} frames dropped -- the phone's wifi link stuttered.")
    print(f"\nNext: python src/analyze_session.py {os.path.basename(video_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
