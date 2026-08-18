"""
Webcam frame capture.

Works with both physical webcams and virtual ones (Iriun, OBS, DroidCam).
Virtual cameras are the reason this is more than two lines:

  * Backends disagree. Iriun's driver doesn't always fill in the DirectShow
    format header, so CAP_DSHOW can throw while CAP_MSMF works fine. We try
    backends in order and keep the first that actually yields a frame.
  * "Opened" != "ready". A virtual cam streams over WiFi, so the first frames
    are often black while the phone negotiates. We discard a few on startup.
  * The phone can wander off. If WiFi drops, reads start failing, so callers
    can ask us to reconnect rather than dying.
"""
import time

import numpy as np
import cv2

# Ordered by how well they cope with virtual cameras on Windows.
BACKENDS = [
    ("MSMF", cv2.CAP_MSMF),
    ("DSHOW", cv2.CAP_DSHOW),
    ("ANY", cv2.CAP_ANY),
]

WARMUP_FRAMES = 5

# Resolution has to be ASKED FOR. cv2.VideoCapture takes the driver's default
# regardless of what the device can do -- which on this rig is 640x480, so the
# whole project ran at 640x480 for weeks while Iriun was capable of 4K the
# entire time. Nothing was broken; nothing had ever requested anything.
#
# Measured 2026-08-12, both MSMF and DSHOW, all at ~30fps:
#   3840x2160  2560x1440  1920x1080  1280x720  640x480
# So the ceiling is the phone, not the capture path.
#
# Note this changes the FRAMING, not just the pixel count: 640x480 is 4:3 and
# 4K is 16:9, which on a phone sensor is a different crop. Any change here
# invalidates UPRIGHT_TORSO_ANGLE -- recalibrate (analyze_session --calibrate).
DEFAULT_WIDTH = 3840
DEFAULT_HEIGHT = 2160

# Iriun pads every 16:9 mode. Measured across the whole ladder (2026-08-12),
# the real image is always exactly 75% of the requested width AND height,
# centred, with black on all four sides -- so 43% of a 4K frame is nothing:
#
#   asked 3840x2160 -> content 2880x1624   56.4% used
#   asked 2560x1440 -> content 1920x1082   56.4%
#   asked 1920x1080 -> content 1440x812    56.4%
#   asked 1600x900  -> got 1280x960, content 1280x722   75.2%   (4:3, no pad)
#
# 4:3 modes are NOT padded -- they fill the width and letterbox top/bottom,
# which is just 16:9 content in a 4:3 frame. So the padding is a quirk of
# Iriun's 16:9 modes, not a limit of the phone.
#
# 4K still carries the most real detail (2880x1624 beats every other mode), so
# the answer is to keep 4K and cut the border off. That turns the 1280px
# detection input from 960px of content into a full 1280 -- a free 1.33x.
#
# Auto-detected rather than hardcoded at 12.5%: the border is a property of
# whatever Iriun is doing today, and a wrong constant would silently crop off
# part of the room.
AUTOCROP = True
CROP_DARK = 8            # a pad pixel is *black*, not merely dim
CROP_MIN_AREA = 0.35     # refuse a crop that throws away most of the frame
CROP_PROBE_FRAMES = 6

# A dead virtual camera does NOT fail cleanly, which is the whole reason this
# check exists. When the phone drops off WiFi, Iriun keeps the device open and
# streams a placeholder card ("Looking for the phone", a cartoon cat on black).
# Every read succeeds, so `frame is None` never fires, reconnect() never runs,
# and YOLO faithfully reports no person -> place()="absent" -> mode="away".
# The log then says he left the room, and nothing distinguishes that from
# actually leaving. Measured live on 2026-08-12.
#
# The test needs no threshold. A real sensor cannot produce two byte-identical
# frames -- shot and thermal noise put ~0.5 mean absolute difference between
# consecutive reads even of a perfectly still scene (measured on this rig).
# Exact equality therefore means the image is synthetic, full stop.
STALL_FRAMES = 3        # identical reads in a row before declaring the feed dead

#  ...and it must ALSO have been frozen this long. See Camera.stalled.
#
#  The streak alone is not evidence. "A real sensor cannot emit two identical
#  frames" is true, but grab() compares two READS, not two exposures -- and the
#  tracker polls every ~30ms to keep the MJPEG stream fed. Measured on this rig
#  2026-08-17, at the 4K the capture now asks for:
#
#      polled 33/s  ->  4.6 fps actually delivered by Iriun
#                       68% of reads byte-identical to the previous one
#                       longest run 7, so STALL_FRAMES=3 tripped in 1.7s
#                       ON A CAMERA THAT WAS WORKING FINE
#
#  Reading one exposure several times is what polling faster than the sensor
#  looks like; it says nothing about the feed being synthetic. Raising the
#  resolution to 4K cut the delivered frame rate enough to make that constant,
#  so a documented improvement silently broke this detector.
#
#  Wall-clock is the poll-rate-independent version of the same question: a live
#  feed cannot show a byte-identical image for seconds on end, no matter how
#  fast or slow anything reads it. 3s is ~14 missed frames at the measured
#  4.6fps, and a dropped Iriun serves its placeholder card indefinitely.
STALL_SECONDS = 3.0


class Camera:
    def __init__(self, index=0, warmup=WARMUP_FRAMES,
                 width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
        self.index = index
        self.warmup = warmup
        self.width = width
        self.height = height
        self.backend_name = None
        self.raw_size = None          # what the device handed over, padding included
        self.size = None              # what callers actually receive, post-crop
        self.cap = None
        self._last = None
        self.identical_streak = 0
        self._last_change_at = None   # clock reading at the last CHANGED frame
        # Injectable so test_stall.py can exercise the time gate without
        # sleeping through it -- the stall rule is now about elapsed seconds,
        # and a test that cannot move the clock cannot test it.
        self.clock = time.monotonic
        self.crop = None              # (x0, y0, x1, y1) of real image content
        self._open()

    def _find_content_box(self, cap):
        """
        Locate the real image inside whatever padding the driver added.

        Uses the per-pixel MAXIMUM across several frames, not one frame: a
        genuinely dark corner of the room could read as padding in a single
        exposure, but real pixels flicker with sensor noise while padding is
        identically black every time. Taking the max lets any frame vote a
        pixel "real".

        Returns None -- meaning don't crop -- whenever the answer is not
        obviously a clean border, because cropping away part of the room by
        mistake is far worse than leaving 43% of the frame black.
        """
        stack = None
        for _ in range(CROP_PROBE_FRAMES):
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            g = frame.max(axis=2)
            stack = g if stack is None else np.maximum(stack, g)
        if stack is None:
            return None

        h, w = stack.shape
        rows = np.nonzero(stack.max(axis=1) > CROP_DARK)[0]
        cols = np.nonzero(stack.max(axis=0) > CROP_DARK)[0]
        if len(rows) == 0 or len(cols) == 0:
            return None

        y0, y1 = int(rows[0]), int(rows[-1]) + 1
        x0, x1 = int(cols[0]), int(cols[-1]) + 1
        if (x1 - x0) * (y1 - y0) < CROP_MIN_AREA * w * h:
            return None
        if (x1 - x0, y1 - y0) == (w, h):
            return None                       # nothing to crop
        return (x0, y0, x1, y1)

    def _open(self):
        """Try each backend until one opens AND delivers a real frame."""
        errors = []
        for name, backend in BACKENDS:
            cap = cv2.VideoCapture(self.index, backend)
            if not cap.isOpened():
                cap.release()
                errors.append(f"{name}: would not open")
                continue

            # Ask before reading. Setting these after the first read is
            # ignored by some backends, and a request the device cannot honour
            # is silently downgraded rather than failing -- which is why
            # `self.size` records what actually arrived instead of trusting
            # what was asked for.
            if self.width and self.height:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

            # Opening can succeed while reading fails -- verify with a real read.
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release()
                errors.append(f"{name}: opened but no frame")
                continue
            self.raw_size = self.size = (frame.shape[1], frame.shape[0])

            # Drain startup frames (often black on a virtual camera).
            for _ in range(self.warmup):
                cap.read()

            self.cap = cap
            self.backend_name = name
            if AUTOCROP:
                self.crop = self._find_content_box(cap)
                if self.crop:
                    x0, y0, x1, y1 = self.crop
                    self.size = (x1 - x0, y1 - y0)
            return

        raise RuntimeError(
            f"Could not capture from camera index {self.index}.\n"
            + "\n".join(f"  - {e}" for e in errors)
            + "\nIf you're using Iriun: make sure the phone app is connected and "
            "the Iriun client is running on the PC. Otherwise try a different "
            "camera_index in config.json."
        )

    def grab(self):
        """
        Return a single BGR frame, or None if the read failed.

        Also tracks how many consecutive reads were byte-identical, which is
        how a stalled virtual camera is caught -- see STALL_FRAMES. The count
        is maintained here rather than by callers because "the previous frame"
        is state that belongs to the stream, and every caller would otherwise
        have to keep its own copy.
        """
        if self.cap is None:
            return None
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None

        if self.crop:
            x0, y0, x1, y1 = self.crop
            frame = frame[y0:y1, x0:x1]

        now = self.clock()
        if self._last is not None and np.array_equal(frame, self._last):
            self.identical_streak += 1
        else:
            self.identical_streak = 0
            self._last_change_at = now
        if self._last_change_at is None:       # first ever read
            self._last_change_at = now
        self._last = frame
        return frame

    @property
    def stalled(self):
        """
        True when the feed is serving a frozen or synthetic image.

        Deliberately NOT folded into grab() returning None. A caller that sees
        None assumes a transient read failure and retries; a caller that sees
        `stalled` knows the camera is lying to it and must refuse to state
        anything about the room at all.

        Both conditions are required, and the clock is the one that matters:
        the streak alone fires on any working camera that is polled faster than
        it delivers, which at 4K is all of them. See STALL_SECONDS.
        """
        if self.identical_streak < STALL_FRAMES:
            return False
        if self._last_change_at is None:
            return False
        return (self.clock() - self._last_change_at) >= STALL_SECONDS

    def reconnect(self):
        """Tear down and re-open -- used when the stream drops mid-session."""
        self.release()
        self._last = None
        self.identical_streak = 0
        self._last_change_at = None
        self.crop = None              # re-measured: Iriun may come back different
        self._open()

    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
