"""
Regression test for the Iriun placeholder bug.

On 2026-08-12 the phone dropped off WiFi mid-session. Iriun did not fail the
read -- it streamed a placeholder card (a cartoon cat on black, "Looking for
the phone"). Every layer downstream behaved exactly as designed and produced a
completely false answer:

    grab()          valid frame, ok=True     -> reconnect() never fires
    YOLO            no person in the card    -> present=False
    place()         "absent"
    resolve_mode()  "away"

A whole-life tracker that cannot distinguish "he left" from "the camera died"
is not recording his life, and nothing in the log marks which one happened.

This test cannot wait for WiFi to drop, so it fakes the stall the same way the
camera does: by handing back the identical frame every read. That is also the
detection rule -- a real sensor cannot emit two byte-identical frames, because
shot and thermal noise put ~0.5 mean absolute difference between consecutive
reads even of a motionless scene (measured on this rig).

    py -3.12 src/test_stall.py
"""
import os
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from camera_state import CameraState                      # noqa: E402
from camera_state import place as haar_place              # noqa: E402
from capture import STALL_FRAMES, Camera                   # noqa: E402
from mode_log import load_config, resolve_mode             # noqa: E402
from pose_detector import place as pose_place              # noqa: E402


class FrozenCap:
    """Stands in for cv2.VideoCapture on a camera serving a placeholder."""

    def __init__(self, frame):
        self.frame = frame

    def read(self):
        return True, self.frame.copy()      # copy: equal in value, not identity

    def release(self):
        pass


class SlowCap:
    """
    A working camera read faster than it produces exposures.

    Hands back the SAME exposure `repeat` times before advancing to a new one,
    which is exactly what cv2.read() does when you poll at 33/s a feed that
    delivers 4.6fps. Byte-identical here is a fact about the polling rate, not
    about the camera -- the distinction the stall detector missed until
    2026-08-17.
    """

    def __init__(self, frame, rng, repeat=7):
        self.frame = frame
        self.rng = rng
        self.repeat = repeat
        self.n = 0
        self.cur = None

    def read(self):
        if self.cur is None or self.n % self.repeat == 0:
            noise = self.rng.integers(-2, 3, self.frame.shape, dtype=np.int16)
            self.cur = np.clip(self.frame.astype(np.int16) + noise,
                               0, 255).astype(np.uint8)
        self.n += 1
        return True, self.cur.copy()

    def release(self):
        pass


class LiveCap:
    """A working camera: same scene, but never two identical frames."""

    def __init__(self, frame, rng):
        self.frame = frame
        self.rng = rng

    def read(self):
        noise = self.rng.integers(-2, 3, self.frame.shape, dtype=np.int16)
        return True, np.clip(self.frame.astype(np.int16) + noise,
                             0, 255).astype(np.uint8)

    def release(self):
        pass


class StubDetector:
    """
    Reports what YOLO reports on the placeholder card: nobody there.

    Hard-coded rather than run for real, because the point of the test is what
    the pipeline DOES with "no person", not whether YOLO can find one in a
    picture of a cat.
    """

    def __init__(self, present):
        self.present = present

    def observe(self, _frame):
        return {"present": self.present, "head_up": self.present,
                "phone": False, "facing": "toward" if self.present else None,
                "posture": "upright" if self.present else "unknown",
                "torso_angle": -12.0 if self.present else None}


def camera_with(cap, clock=None):
    """
    A Camera around a fake cv2 capture, with no hardware and no _open().

    Bypassing __init__ means every attribute grab() touches has to be set by
    hand here -- so adding state to Camera breaks this function until it is
    listed below. That is working as intended: the alternative is a test that
    silently drifts out of sync with the class it is testing. (It caught
    `crop` on 2026-08-12.)
    """
    cam = Camera.__new__(Camera)
    cam.index, cam.warmup, cam.backend_name = 0, 0, "STUB"
    cam.width = cam.height = None
    cam.cap, cam._last, cam.identical_streak = cap, None, 0
    cam.crop = None                     # no padding on a synthetic frame
    cam.raw_size = cam.size = (640, 480)
    cam._last_change_at = None
    # Frozen unless a test hands over its own clock. Real elapsed time in a
    # tight loop is ~0, which would make every time-gated assertion vacuous.
    cam.clock = clock or (lambda: 0.0)
    return cam


class FakeClock:
    """A clock the test drives by hand. Seconds, monotonic by construction."""

    def __init__(self, step=0.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t

    def advance(self, seconds):
        self.t += seconds


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: {got!r}"
          + ("" if ok else f"  (expected {want!r})"))
    return ok


def main():
    cfg = load_config()
    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    placeholder[180:220, 280:360] = (0, 140, 255)      # the cat, near enough
    rng = np.random.default_rng(0)
    results = []

    print("\n[1] frozen feed is detected")
    # 1s per read: STALL_FRAMES reads also clears STALL_SECONDS.
    cam = camera_with(FrozenCap(placeholder), clock=FakeClock(step=1.0))
    for _ in range(STALL_FRAMES + 1):
        cam.grab()
    results.append(check("identical_streak", cam.identical_streak, STALL_FRAMES + 1 - 1))
    results.append(check("stalled", cam.stalled, True))

    print("\n[1b] a WORKING camera polled faster than it delivers is not a stall")
    # The 2026-08-17 false positive, reproduced to the measured numbers: Iriun
    # delivering 4.6fps at 4K while the tracker polls every 30ms, so ~7 reads
    # land on each exposure. Pre-fix this tripped in 1.7s of real use.
    slow = camera_with(SlowCap(placeholder, rng, repeat=7),
                       clock=FakeClock(step=0.03))
    tripped = False
    for _ in range(200):                       # ~6s of polling
        slow.grab()
        if slow.stalled:
            tripped = True
            break
    results.append(check("streak does climb past the frame threshold",
                         slow.identical_streak >= STALL_FRAMES or tripped, True))
    results.append(check("but never reports stalled", tripped, False))

    print("\n[2] live feed is NOT mistaken for a stall")
    live = camera_with(LiveCap(placeholder, rng))
    for _ in range(10):
        live.grab()
    results.append(check("identical_streak", live.identical_streak, 0))
    results.append(check("stalled", live.stalled, False))

    print("\n[3] a stalled burst reaches place() as camera_lost, not absent")
    cam = camera_with(FrozenCap(placeholder), clock=FakeClock(step=1.0))
    state = CameraState(cam, StubDetector(present=False)).sample()
    results.append(check("camera_stalled", state["camera_stalled"], True))
    results.append(check("pose place", pose_place(state, False), "camera_lost"))
    results.append(check("haar place", haar_place(state, False), "camera_lost"))

    print("\n[4] resolve_mode never turns camera_lost into away or deep_work")
    noon = datetime.now().replace(hour=14, minute=0)
    cases = [
        ({"category": "school", "idle": False, "passive": False,
          "idle_seconds": 0}, "deep_work"),
        ({"category": "anime", "idle": True, "passive": True,
          "idle_seconds": 600}, "camera_lost"),
        ({"category": "locked", "idle": True, "passive": False,
          "idle_seconds": 900}, "camera_lost"),
    ]
    for screen, want in cases:
        mode, why = resolve_mode("camera_lost", screen, noon, cfg)
        results.append(check(f"screen={screen['category']}", mode, want))
        if mode != "camera_lost":
            results.append(check("  reason names the outage",
                                 "CAMERA DOWN" in why, True))

    print("\n[5] the bug itself: absent still means absent when the feed is fine")
    live = camera_with(LiveCap(placeholder, rng))
    state = CameraState(live, StubDetector(present=False)).sample()
    results.append(check("place", pose_place(state, False), "absent"))
    mode, _ = resolve_mode("absent", {"category": "locked", "idle": True,
                                      "passive": False, "idle_seconds": 900},
                           noon, cfg)
    results.append(check("mode", mode, "away"))

    passed = sum(results)
    print(f"\n  {passed}/{len(results)} checks passed\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
