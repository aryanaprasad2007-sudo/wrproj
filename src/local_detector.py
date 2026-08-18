"""
Local, offline first-pass classifier.

Returns a verdict using only on-device models (no network):
  - "productive"  : confident you're working
  - "lazy"        : confident you're slacking (e.g. phone in hand)
  - "away"        : no person detected
  - "unsure"      : ambiguous -> caller should ask Claude

Tuned for a SIDE / three-quarter camera angle (camera off to one side at
seated head height), which is what this rig actually uses. Two consequences:

  * The frontal-face cascade is the wrong tool. From the side it does not
    find you -- but it happily matches photographs on the wall. Faces are
    therefore searched with the PROFILE cascade, and only INSIDE the person
    box YOLO reports. A face outside the person is not a face, it's decor.

  * Head orientation is the engagement signal. The profile cascade only
    detects one facing direction, so we run it on the frame and on the
    mirror; which one hits tells us roughly which way you're turned. That
    mapping is recorded but NOT yet trusted -- see `facing` in the result.
"""
import os

import cv2

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PERSON_CLASS_ID = 0   # "person" in COCO
PHONE_CLASS_ID = 67   # "cell phone" in COCO


def weights_path(name):
    """
    Resolve a model file against the project root.

    Ultralytics resolves a bare filename against the CURRENT WORKING
    DIRECTORY, so `YOLO("yolov8n.pt")` finds the cached weights only when you
    happen to be standing in the project root -- and silently re-downloads
    them when you aren't. Anchoring to the repo makes it work from anywhere.

    Falls back to the bare name if the file isn't there yet, because that is
    the form ultralytics knows how to download.
    """
    local = os.path.join(ROOT, name)
    return local if os.path.exists(local) else name

# Pad the person box slightly -- YOLO sometimes clips the top of the head.
BOX_PAD = 0.08


class LocalDetector:
    def __init__(self):
        base = cv2.data.haarcascades
        self.profile = cv2.CascadeClassifier(base + "haarcascade_profileface.xml")
        self.frontal = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
        self.cascades_ok = not (self.profile.empty() or self.frontal.empty())

        self.yolo = None
        if YOLO is not None:
            # yolov8n is tiny (~6MB) and downloads automatically on first run.
            self.yolo = YOLO(weights_path("yolov8n.pt"))

    def observe(self, frame_bgr):
        """
        Return FACTS about this frame, not a judgment.

        `present` and `head_up` are separate keys on purpose. Collapsing them
        (as classify() does) throws away information: "person there, head not
        found" is near-total confidence about WHERE you are and mere doubt
        about POSTURE, but it came out as a single flat "unsure". Presence
        comes from YOLO and is steady; head_up comes from a Haar cascade and
        flickers. Reported apart, the steady signal stops being dragged down
        by the noisy one.

        Read `head_up=False` as "no head found", NOT "no head". The cascade
        has high precision and poor recall inside a person box -- a hit is
        strong evidence, a miss is weak evidence. CameraState leans on that
        asymmetry when it votes.
        """
        person_box, person_conf, phone, phone_conf = self._yolo_scan(frame_bgr)

        if person_box is None:
            return {
                "present": False, "person_conf": 0.0,
                "head_up": False, "facing": None,
                "phone": phone, "phone_conf": round(phone_conf, 2),
                "person_box": None,
            }

        head_up, facing = self._find_head(frame_bgr, person_box)
        return {
            "present": True, "person_conf": round(person_conf, 2),
            "head_up": head_up, "facing": facing,
            "phone": phone, "phone_conf": round(phone_conf, 2),
            "person_box": person_box,
        }

    def classify(self, frame_bgr):
        """
        Return (verdict, confidence, reason).

        Legacy shape, kept for the old main.py loop. New code should call
        observe() -- this collapses facts into a judgment too early, and the
        judgment vocabulary ("productive"/"lazy") predates the shift to
        lifestyle tracking.
        """
        o = self.observe(frame_bgr)

        if o["phone"]:
            return "lazy", o["phone_conf"], "phone detected in frame"
        if not o["present"]:
            return "away", 0.9, "no person detected"
        if o["head_up"]:
            return "productive", 0.75, f"head up at desk (facing={o['facing']})"
        return "unsure", 0.4, "person present but head not located"

    def _yolo_scan(self, frame_bgr):
        """Return (person_box | None, person_conf, phone_present, phone_conf)."""
        if self.yolo is None:
            return None, 0.0, False, 0.0

        best_person = None
        best_person_conf = 0.0
        phone = False
        phone_conf = 0.0

        for r in self.yolo.predict(frame_bgr, verbose=False, conf=0.35):
            for box in r.boxes:
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                if cls == PERSON_CLASS_ID and conf > best_person_conf:
                    best_person_conf = conf
                    best_person = tuple(int(v) for v in box.xyxy[0])
                elif cls == PHONE_CLASS_ID:
                    phone = True
                    phone_conf = max(phone_conf, conf)

        return best_person, best_person_conf, phone, phone_conf

    def _find_head(self, frame_bgr, person_box):
        """
        Look for a head inside the person box only.

        Returns (head_found, facing) where facing is "left" | "right" |
        "toward" | None. Faces outside the person box are ignored -- that is
        what stops wall photographs from being scored as a person at the desk.
        """
        if not self.cascades_ok:
            return False, None

        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = person_box
        pad_x = int((x2 - x1) * BOX_PAD)
        pad_y = int((y2 - y1) * BOX_PAD)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)
        if x2 <= x1 or y2 <= y1:
            return False, None

        roi = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        params = dict(scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))

        # The profile cascade is single-handed: run it both ways round.
        if len(self.profile.detectMultiScale(roi, **params)):
            return True, "right"
        if len(self.profile.detectMultiScale(cv2.flip(roi, 1), **params)):
            return True, "left"
        # Turned to look straight at the camera (e.g. glancing at the room).
        if len(self.frontal.detectMultiScale(roi, **params)):
            return True, "toward"

        return False, None
