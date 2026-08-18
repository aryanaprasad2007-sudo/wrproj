"""
The tracker as a page you can open.

    py -3.12 src/dashboard.py          ->  http://127.0.0.1:8787

Local only, by construction. It binds to loopback, the camera never leaves the
process, and the only network calls are to two things already on this machine:
Ollama and Aria's own server.

WHY PYTHON OWNS THE CAMERA
A webcam has one owner. If this process holds it for detection, the browser
cannot also getUserMedia the same device -- so the page gets an MJPEG stream
from here instead. That is the better arrangement anyway: what you see in the
top pane is the exact frame the detector judged, not a second, parallel view
that could disagree with it.

WHAT EACH LAYER IS ALLOWED TO CLAIM
    pose detector   where he is, how he is sitting        (91% vs ground truth)
    window sensor   what is on screen
    profile.json    what Perfect Ari would be doing now
    Aria (qwen2.5)  one line about the gap -- FROM FACTS, never from an image
    moondream       a tile caption -- OFF by default, see VISION_CAPTIONS

STORED FRAMES
The rest of this project promises that no frames are stored. This module
breaks that promise on purpose, because a strip of moments is the thing that
was asked for -- so it breaks it as narrowly as possible: one thumbnail per
mode change (not per sample), capped at MAX_MOMENTS, oldest deleted, local
disk only, and wiped by `--reset`.
"""
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aria_link
import profile_plan
import psychowl_data
import torso_baseline
from camera_state import CameraState
from capture import DEFAULT_HEIGHT, DEFAULT_WIDTH, Camera
from mode_log import ModeLogger, load_config, resolve_mode
from pose_detector import PoseDetector, place
from window_sensor import WindowClassifier
from window_sensor import sample as screen_sample

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
MOMENTS = os.path.join(WEB, "moments")

PORT = int(os.environ.get("TRACKER_PORT", "8787"))
MAX_MOMENTS = 40

# ---- psychowl federation -------------------------------------------------
#
# This process is also the roof over the sibling projects. It has to be THIS
# process and not a new one, for one physical reason: the camera has exactly
# one owner, and the tracker loop is it. Everything else psychowl serves is
# either a static file, a disk read (psychowl_data), or a pass-through.
#
# Serving FocusFlow and Grimoire from here is not a convenience -- it is the
# fix for the two walls DATA-CONTRACT.md documents: localStorage is scoped
# per-origin (so a file:// FocusFlow can never share state with anything),
# and Google's iCal endpoint has no CORS header (so Grimoire needs a
# same-origin /ics proxy, which its config already points at).
GRIMOIRE_DIR = os.path.join(ROOT, "grimoire-calendar")
FOCUSFLOW_HTML = os.path.join(ROOT, "FocusFlow-and-Art", "focusflow.html")
SOLO_HTML = os.path.join(ROOT, "Solo-Leveling-System", "solo_leveling_live.html")
BRIEF_DIR = os.path.join(ROOT, "Morning-Brief")

MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript",
    ".json": "application/json", ".webmanifest": "application/manifest+json",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".md": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
}

# What grimoire's own serve.py returns when a feed can't be fetched: a valid,
# empty calendar. The client renders "no events" instead of an error state.
EMPTY_ICS = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
             "PRODID:-//Psychowl//empty//EN\r\nEND:VCALENDAR\r\n")

# One capture, three consumers, three different right answers. Measured on the
# 4060 at 3840x2160 (2026-08-12):
#
#   DETECT_W  1280  pose costs 20.7ms here vs 24.2ms at full 4K -- almost
#                   nothing, because YOLO resizes to 640 internally either way.
#                   It is pinned to 1280 anyway to MATCH analyze_session.py's
#                   MAX_WIDTH: the 91% score was measured at 1280, and a
#                   dashboard detecting at a different scale is not the thing
#                   that was scored. (The 523ms-at-4K disaster in the notes was
#                   Haar, which ran on the full-res person crop. Not YOLO.)
#
#   STREAM_W  1280  the only place 4K genuinely hurts: 462 KB/frame at q78
#                   versus 97 KB at 1280, so 5.5 MB/s versus 1.2 -- plus a 4x
#                   heavier decode in the browser tab, forever.
#
#   THUMB_W    320  taken from the FULL-RES frame, since a one-off resize is
#                   2.1ms and the strip is the one place detail is visible.
DETECT_W = 1280
STREAM_W = int(os.environ.get("TRACKER_STREAM_W", "1280"))
THUMB_W = 320


def fit(frame, width):
    """Downscale to `width` if wider. Never upscales -- that only costs time."""
    if frame is None or frame.shape[1] <= width:
        return frame
    scale = width / frame.shape[1]
    return cv2.resize(frame, (width, int(round(frame.shape[0] * scale))),
                      interpolation=cv2.INTER_AREA)

# Off because it was measured, not because it is unfinished. moondream on this
# rig described an empty chair as "a person sitting... focus and concentration"
# while he was standing across the room, and appended invented mental states to
# every answer. See CLAUDE.md. Flip to True to put its guesses back on the
# tiles -- they are always rendered as unverified.
VISION_CAPTIONS = False

# Aria is asked at most this often. Every call is a real qwen2.5 turn on the
# 4060, and a mode that flickers would otherwise queue up inference faster than
# it completes.
ARIA_MIN_SECONDS = 120

#  Aria's presence has two settings, and the difference is real rather than
#  cosmetic:
#
#    speaking   she is asked, and her line IS the owl's ledger.
#    observing  she is not asked at all. No turn, no inference, no words.
#               The ledger falls back to the facts template, labelled as such.
#
#  This is enforced HERE and not in the browser on purpose. The ask fires from
#  the tracker loop, so a checkbox in the page would still spend a qwen turn
#  every 120s and merely hide the result -- which is the opposite of "just
#  being there". Observing has to mean not asked.
#
#  Persisted so the choice survives a restart: which of the two she is in is
#  his decision, not something a crashed process gets to silently revert.
ARIA_MODES = ("speaking", "observing")
ARIA_STATE_FILE = os.path.join(ROOT, "data", "aria_mode.json")


def load_aria_mode(default="speaking"):
    try:
        with open(ARIA_STATE_FILE, "r", encoding="utf-8") as f:
            mode = json.load(f).get("mode")
        return mode if mode in ARIA_MODES else default
    except (OSError, ValueError):
        return default


def save_aria_mode(mode):
    os.makedirs(os.path.dirname(ARIA_STATE_FILE), exist_ok=True)
    with open(ARIA_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"mode": mode}, f)


class Tracker:
    """Owns the camera and the current picture of the day."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.frame = None                 # latest BGR, for the MJPEG stream
        self.state = {"ready": False}
        self.moments = []
        self.capture_size = None          # what the device actually gave us
        # Torso angles seen while he is actually at the desk. Calibrating from
        # real working posture beats a posed 30-second sit: the baseline should
        # describe how he sits when he forgets he is being measured.
        self.angles = []
        # Learns his normal posture continuously instead of being calibrated.
        # The camera is a phone that moves for unrelated reasons, so a fixed
        # baseline is stale within hours and fails silently when it is.
        self.baseline = torso_baseline.TorsoBaseline()
        self.aria = None
        self._aria_at = 0.0
        self._aria_busy = False
        self.aria_mode = load_aria_mode()
        # None = not asked yet this run, True/False = last attempt's outcome.
        # "She has not spoken yet" and "her server is down" both arrive at the
        # page as aria=None otherwise, and they need different words: one is a
        # wait, the other is a thing he can go fix.
        self.aria_reachable = None
        self.stop = threading.Event()

        os.makedirs(MOMENTS, exist_ok=True)
        self._load_moments()

    # -- moments ----------------------------------------------------------

    def _index_path(self):
        return os.path.join(MOMENTS, "index.json")

    def _load_moments(self):
        try:
            with open(self._index_path(), "r", encoding="utf-8") as f:
                self.moments = json.load(f)
        except (OSError, ValueError):
            self.moments = []

    def _save_moments(self):
        with open(self._index_path(), "w", encoding="utf-8") as f:
            json.dump(self.moments[-MAX_MOMENTS:], f, indent=1)

    def add_moment(self, frame, mode, block, spot, screen, now):
        """One thumbnail per mode change -- the only frames ever written."""
        name = f"{now:%Y%m%d-%H%M%S}.jpg"
        cv2.imwrite(os.path.join(MOMENTS, name), fit(frame, THUMB_W),
                    [cv2.IMWRITE_JPEG_QUALITY, 82])

        entry = {
            "file": name,
            "time": now.strftime("%H:%M"),
            "mode": mode,
            "place": spot,
            "screen": screen.get("category"),
            "app": screen.get("app") or "",
            "block": (block or {}).get("name"),
            "emoji": (block or {}).get("emoji", ""),
            "status": profile_plan.deviation(
                block, mode, 0, camera_ok=(spot != "camera_lost"))["status"],
            "caption": None,
        }
        if VISION_CAPTIONS:
            entry["caption"] = aria_link.caption(frame)

        with self.lock:
            self.moments.append(entry)
            while len(self.moments) > MAX_MOMENTS:
                old = self.moments.pop(0)
                try:
                    os.remove(os.path.join(MOMENTS, old["file"]))
                except OSError:
                    pass
            self._save_moments()

    # -- Aria -------------------------------------------------------------

    def maybe_ask_aria(self, facts):
        """
        Fire a background turn if enough time has passed.

        Non-blocking on purpose: a qwen2.5 turn takes seconds and the sample
        loop must not stall behind it, or the camera stream stutters every
        time she speaks.

        In `observing` this returns immediately without contacting her at all.
        """
        if self.aria_mode != "speaking":
            return
        if self._aria_busy or time.time() - self._aria_at < ARIA_MIN_SECONDS:
            return
        self._aria_busy = True

        def run():
            try:
                said = aria_link.ask_aria(facts)
                with self.lock:
                    self.aria_reachable = bool(said)
                if said:
                    said["at"] = datetime.now().strftime("%H:%M")
                    said["about"] = facts.get("deviation", {}).get("status")
                    with self.lock:
                        self.aria = said
                    self._aria_at = time.time()
                else:
                    # Back off on failure too. Without this a dead server is
                    # retried every sample tick instead of every 120s.
                    self._aria_at = time.time()
            finally:
                self._aria_busy = False

        threading.Thread(target=run, daemon=True).start()

    # -- main loop --------------------------------------------------------

    def run(self):
        print("[*] loading pose detector ...")
        # phone_model=None halves inference: the second YOLO pass only exists
        # to find a phone, and on this rig the phone IS the camera, so it can
        # never appear in frame (open item #3).
        detector = PoseDetector(phone_model=None)
        cam = Camera(0)
        cam_state = CameraState(cam, detector)
        screen_clf = WindowClassifier()
        logger = ModeLogger(self.cfg)
        interval = self.cfg["interval_seconds"]
        w, h = cam.size or (0, 0)
        raw_w, raw_h = cam.raw_size or (0, 0)
        with self.lock:
            self.capture_size = [w, h]
        print(f"[*] camera on {cam.backend_name} at {raw_w}x{raw_h}"
              + (f" -> cropped {w}x{h}" if cam.crop else "")
              + f" (detect {DETECT_W}, stream {STREAM_W}); every {interval}s")
        # Compare the RAW size: a request the device cannot honour is
        # downgraded silently, and a 4K dashboard quietly running at 640x480
        # looks identical to a working one until you wonder why it is soft.
        if (raw_w, raw_h) != (DEFAULT_WIDTH, DEFAULT_HEIGHT):
            print(f"[!] asked for {DEFAULT_WIDTH}x{DEFAULT_HEIGHT}, "
                  f"got {raw_w}x{raw_h}")

        last_sample = 0.0
        last_mode = None
        try:
            while not self.stop.is_set():
                frame = cam.grab()
                if frame is None:
                    cam.reconnect()
                    time.sleep(0.5)
                    continue
                with self.lock:
                    self.frame = frame

                if time.time() - last_sample < interval:
                    time.sleep(0.03)      # keep the stream fed between samples
                    continue
                last_sample = time.time()
                now = datetime.now()

                # Hand the detector the baseline measured so far, then feed it
                # what came back. Set BEFORE the burst, since the detector
                # classifies posture during observe().
                learned = self.baseline.current()
                if learned is not None:
                    detector.upright_angle = learned

                reading = CameraState.reduce(cam_state.raw_burst())
                self.baseline.observe(reading.get("torso_angle"))
                spot = place(reading, self.cfg.get("trust_phone_detection", False))
                screen = screen_sample(screen_clf)
                mode, why = resolve_mode(spot, screen, now, self.cfg)

                closed = logger.observe(mode, why, now)
                held = 0
                if logger.current:
                    held = (now - logger.current["start"]).total_seconds()

                # Collect calibration data whenever a person is genuinely in
                # frame. Filtered on `present`, not on place == at_desk:
                # place() depends on UPRIGHT_TORSO_ANGLE, so calibrating only
                # on frames it already likes would just confirm the current
                # value. That is the circularity that makes a baseline drift.
                if reading.get("torso_angle") is not None and reading["present"]:
                    with self.lock:
                        self.angles.append({
                            "t": now.strftime("%H:%M:%S"),
                            "angle": round(reading["torso_angle"], 1),
                            "posture": reading.get("posture"),
                            "place": spot,
                        })
                        del self.angles[:-500]

                block = profile_plan.plan_for_now(now)
                facts = profile_plan.facts(block, mode, why, round(held / 60),
                                           screen, spot, now, reading)

                if mode != last_mode:
                    self.add_moment(frame, mode, block, spot, screen, now)
                    last_mode = mode
                self.maybe_ask_aria(facts)

                with self.lock:
                    self.state = {
                        "ready": True, "facts": facts,
                        "camera_ok": spot != "camera_lost",
                        "closed_run": closed,
                    }
                print(f"\r  {now:%H:%M:%S}  {mode:<16} {spot:<14} "
                      f"{facts['deviation']['status']:<9} ", end="", flush=True)
        finally:
            logger.close(datetime.now())
            # Flush whatever the baseline learned since its last write, or a
            # Ctrl+C inside the save interval silently throws it away.
            try:
                self.baseline.save()
            except OSError:
                pass
            cam.release()
            print("\n[*] stopped.")


def make_handler(tracker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass                          # the sample line is the only output

        def _send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # The NightOwl hub is a file:// page, so its origin is the opaque
            # string "null" -- it is cross-origin to this server by definition
            # and cannot read a response without this. Safe here because the
            # socket is bound to 127.0.0.1: nothing off this machine can reach
            # it to take advantage of the wildcard.
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj):
            self._send(200, json.dumps(obj).encode("utf-8"),
                       "application/json", {"Cache-Control": "no-store"})

        def _file(self, full, fallback_ctype="application/octet-stream"):
            ext = os.path.splitext(full)[1].lower()
            try:
                with open(full, "rb") as f:
                    self._send(200, f.read(), MIME.get(ext, fallback_ctype))
            except OSError:
                self._send(404, b"missing: " + os.path.basename(full).encode(),
                           "text/plain")

        def do_POST(self):
            """The only writable surface on this server.

            POST rather than a query string on GET: every other page in this
            browser can trigger a cross-origin GET (an <img src> is enough),
            and this endpoint changes whether Aria is listening. A same-origin
            POST is the cheap way to keep a drive-by from flipping her on.
            """
            path = self.path.split("?")[0]

            if path == "/api/aria/mode":
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    want = json.loads(self.rfile.read(n) or b"{}").get("mode")
                except (ValueError, OSError):
                    want = None
                if want not in ARIA_MODES:
                    self._send(400, b'{"error":"mode must be speaking|observing"}',
                               "application/json")
                    return
                with tracker.lock:
                    tracker.aria_mode = want
                    tracker.aria_reachable = None   # unknown again until re-asked
                    # Drop her last line when she stops speaking. Leaving it on
                    # screen under an "observing" label would read as her still
                    # talking, which is the same misattribution the facts-only
                    # fallback exists to prevent.
                    if want != "speaking":
                        tracker.aria = None
                if want == "speaking":
                    tracker._aria_at = 0.0          # let her speak immediately
                save_aria_mode(want)
                self._json({"mode": want})
                return

            self._send(404, b"not found", "text/plain")

        def do_GET(self):
            path = self.path.split("?")[0]

            if path in ("/", "/index.html"):
                self._file(os.path.join(WEB, "psychowl.html"))
                return

            # The tracker's own full panel, unchanged -- it just moved off "/"
            # when psychowl took the front door.
            if path == "/tracker":
                self._file(os.path.join(WEB, "dashboard.html"))
                return

            # A one-view mode built for Quest 3 + Virtual Desktop: the whole
            # page becomes a giant centered mirror. See web/theater.html for
            # why this is a layout problem, not a new client -- Virtual
            # Desktop just mirrors this same Brave window into a big virtual
            # screen, so nothing here talks to the headset at all.
            if path == "/theater":
                self._file(os.path.join(WEB, "theater.html"))
                return

            if path == "/api/psychowl":
                self._json(psychowl_data.summary())
                return

            if path == "/focus":
                self._file(FOCUSFLOW_HTML)
                return

            if path == "/solo":
                self._file(SOLO_HTML)
                return

            if path in ("/brief", "/brief/latest"):
                b = psychowl_data.morning_brief()
                if not b:
                    self._send(404, b"no briefs", "text/plain")
                    return
                self._file(os.path.join(BRIEF_DIR, b["file"]))
                return

            if path.startswith("/brief/"):
                full = psychowl_data.brief_path(os.path.basename(path))
                if full:
                    self._file(full)
                else:
                    self._send(404, b"no such brief", "text/plain")
                return

            if path in ("/grimoire", "/grimoire/"):
                self._file(os.path.join(GRIMOIRE_DIR, "index.html"))
                return

            if path.startswith("/grimoire/"):
                # Static tree under grimoire-calendar/, traversal-proof: the
                # normalised result must stay inside the directory.
                rel = urllib.parse.unquote(path[len("/grimoire/"):])
                full = os.path.normpath(os.path.join(GRIMOIRE_DIR, rel))
                if full.startswith(GRIMOIRE_DIR + os.sep):
                    self._file(full)
                else:
                    self._send(404, b"no", "text/plain")
                return

            if path == "/ics":
                # Same contract as grimoire's own serve.py: ?cal=<index into
                # the config's feed list>. The index scheme means this proxy
                # can only ever fetch calendars named in grimoire's config --
                # it is not an open relay.
                q = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query)
                urls = psychowl_data.ics_urls()
                try:
                    url = urls[int(q.get("cal", ["-1"])[0])]
                except (ValueError, IndexError):
                    url = ""
                body = EMPTY_ICS.encode()
                if url.startswith("https://"):
                    try:
                        req = urllib.request.Request(
                            url, headers={"User-Agent": "psychowl/1.0"})
                        with urllib.request.urlopen(req, timeout=10) as r:
                            body = r.read()
                    except (urllib.error.URLError, OSError, ValueError):
                        body = EMPTY_ICS.encode()
                self._send(200, body, "text/calendar; charset=utf-8",
                           {"Cache-Control": "no-store"})
                return

            if path == "/api/state":
                with tracker.lock:
                    self._json({**tracker.state, "aria": tracker.aria,
                                "aria_mode": tracker.aria_mode,
                                "aria_reachable": tracker.aria_reachable,
                                "vision_captions": VISION_CAPTIONS,
                                "capture_size": tracker.capture_size,
                                "stream_width": STREAM_W,
                                "detect_width": DETECT_W})
                return

            if path == "/api/baseline":
                # A readout, not a calibration step -- there is nothing to
                # calibrate any more. It reports what the baseline has learned
                # so the number is inspectable rather than invisible.
                with tracker.lock:
                    report = tracker.baseline.report()
                    report["recent"] = tracker.angles[-12:]
                self._json(report)
                return

            if path == "/api/moments":
                with tracker.lock:
                    self._json(list(reversed(tracker.moments)))
                return

            if path.startswith("/moments/"):
                name = os.path.basename(path)
                full = os.path.join(MOMENTS, name)
                if not name.endswith(".jpg") or not os.path.exists(full):
                    self._send(404, b"no", "text/plain")
                    return
                with open(full, "rb") as f:
                    self._send(200, f.read(), "image/jpeg",
                               {"Cache-Control": "max-age=86400"})
                return

            if path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=f")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    while not tracker.stop.is_set():
                        with tracker.lock:
                            frame = tracker.frame
                        if frame is None:
                            time.sleep(0.1)
                            continue
                        ok, buf = cv2.imencode(
                            ".jpg", fit(frame, STREAM_W),
                            [cv2.IMWRITE_JPEG_QUALITY, 78])
                        if not ok:
                            continue
                        data = buf.tobytes()
                        self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\n"
                                         b"Content-Length: "
                                         + str(len(data)).encode()
                                         + b"\r\n\r\n" + data + b"\r\n")
                        time.sleep(0.08)          # ~12fps is plenty
                except (BrokenPipeError, ConnectionAbortedError, OSError):
                    pass                          # tab closed
                return

            self._send(404, b"no", "text/plain")

    return Handler


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    if "--reset" in sys.argv:
        shutil.rmtree(MOMENTS, ignore_errors=True)
        print(f"[*] cleared {MOMENTS}")

    cfg = load_config()
    tracker = Tracker(cfg)

    health = aria_link.aria_health()
    print(f"[*] aria    : {health['persona'] + ' / ' + health['model']
                          if health else 'offline (facts only)'}")
    print(f"[*] vision  : {'moondream' if VISION_CAPTIONS else 'off'}")

    worker = threading.Thread(target=tracker.run, daemon=True)
    worker.start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(tracker))
    print(f"[*] psychowl: http://127.0.0.1:{PORT}  "
          f"(/tracker /focus /grimoire/ /solo /brief)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tracker.stop.set()
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
