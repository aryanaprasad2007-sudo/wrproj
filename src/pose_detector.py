"""
Body tracking via pose keypoints.

The Haar cascade this replaces could only ever answer "is there a face-shaped
patch inside the person box?". That is a bad fit for the question the tracker
actually asks, for two reasons:

  * It flickers. Two consecutive frames of someone sitting perfectly still
    routinely disagree.
  * It says nothing about POSTURE. Sitting at a desk and lying in bed are the
    same answer -- "no face found" -- because in both cases the head is turned
    away or occluded.

Pose estimation answers both. YOLOv8-pose returns 17 COCO keypoints, and the
shoulder-to-hip vector gives torso angle directly: upright is upright and lying
down is lying down, regardless of where the furniture is.

That last point matters here specifically. The earlier plan was to detect bed
by overlapping the person box with a bed box, but measurement killed it --
person/bed overlap was 0.25 while sitting AT THE DESK, so no threshold could
separate the two without constant misfires. Torso angle doesn't care where the
bed is.

Same interface as LocalDetector.observe(), so the two are swappable and can be
scored against each other on identical recorded footage.

Model note: yolov8n-pose.pt (~6.5 MB) downloads from the ultralytics release
on first use, same as yolov8n.pt already does.
"""
import math

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

from local_detector import weights_path

PHONE_CLASS_ID = 67

# COCO keypoint indices.
NOSE = 0
L_EYE, R_EYE = 1, 2
L_EAR, R_EAR = 3, 4
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12

KP_CONF = 0.5          # a keypoint below this is treated as not seen

# What "sitting upright" measures as on THIS camera, in signed degrees.
#
# Not zero, and that is not a bug. This rig's camera is mounted high and
# oblique, looking down across the desk. Viewed from above-and-to-the-side, a
# seated person's hips project sideways rather than directly below the
# shoulders, so the torso axis reads about -47deg while the person is
# perfectly upright. Measured over 40 frames of real footage: median -47,
# stdev 15, with 21 of 40 samples inside a single 10deg bin.
#
# It is emphatically NOT camera roll. Roll would rotate the head too, and the
# Haar face cascade -- which only fires on upright faces -- performs BEST on
# the unrotated frame (12/16 vs 2/16 at +47deg). De-rotating the image would
# fix this number and break face detection instead.
#
# Recalibrate with:  python src/analyze_session.py <video> --calibrate
UPRIGHT_TORSO_ANGLE = -47.0

# Deviation from baseline, in degrees, beyond which he is lying down.
#
# Deliberately broad. The old UPRIGHT_MAX=35 / RECLINED_MAX=65 pair existed to
# carve out a `reclined` class in between, and that class was the problem: it
# demanded a precise baseline to place its edges, and it sent a desk-chair
# lean to watching_in_bed. Two classes ~90 degrees apart need no precision.
#
# Kept importable under the old names so nothing that referenced them breaks.
LYING_MIN = 55
UPRIGHT_MAX = LYING_MIN
RECLINED_MAX = LYING_MIN


def _pt(kps, i):
    """Return (x, y) for a keypoint, or None if it wasn't confidently seen."""
    x, y, c = kps[i]
    return (float(x), float(y)) if c >= KP_CONF else None


def _mid(a, b):
    if a and b:
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return a or b


def torso_angle(kps):
    """
    SIGNED angle of the shoulder-to-hip axis against the image vertical.

    Signed, not absolute. An earlier version returned atan2(|dx|, |dy|), which
    threw the sign away -- and the sign is exactly what is needed to subtract a
    per-camera baseline. With it discarded, a camera whose upright reads -47
    was indistinguishable from one reading +47, and no calibration was possible.

    Returns None when a shoulder or hip pair is not visible, which is common
    (sitting close to the camera crops the hips), so callers must handle it
    rather than defaulting to 0.
    """
    sh = _mid(_pt(kps, L_SHOULDER), _pt(kps, R_SHOULDER))
    hip = _mid(_pt(kps, L_HIP), _pt(kps, R_HIP))
    if not sh or not hip:
        return None
    dx = hip[0] - sh[0]
    dy = hip[1] - sh[1]
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(dx, dy))


def posture_from_angle(angle, upright=None):
    """
    Posture from how far the torso deviates from this camera's upright.

    `upright` is now supplied by torso_baseline.TorsoBaseline, which measures
    it continuously instead of storing a constant -- the camera on this rig is
    a phone that moves for unrelated reasons several times a day, so any fixed
    baseline is stale within hours AND fails silently when it is. Passing None
    falls back to the last hardcoded value only so old recordings replay the
    way they were scored.

    Two classes, wide gate. `reclined` is gone: it was the class that demanded
    precision (a narrow band between upright and lying), and it routed a
    desk-chair lean to watching_in_bed. Upright vs horizontal is ~90 degrees
    apart -- a 55-degree gate cannot be confused by camera drift.
    """
    if angle is None:
        return "unknown"
    if upright is None:
        upright = UPRIGHT_TORSO_ANGLE
    dev = abs(angle - upright)
    if dev > 180:
        dev = 360 - dev
    return "lying" if dev > LYING_MIN else "upright"


def facing_from_head(kps):
    """
    Rough head orientation from which facial keypoints survive.

    Far more robust than running a profile cascade twice: the ears are on
    opposite sides of the skull, so which one is visible *is* the direction.
    Both ears plus a nose means the face is toward the camera.
    """
    nose = _pt(kps, NOSE)
    le, re = _pt(kps, L_EAR), _pt(kps, R_EAR)
    eyes = [p for p in (_pt(kps, L_EYE), _pt(kps, R_EYE)) if p]

    if not nose and not le and not re:
        return None, False
    if le and re:
        return "toward", True
    if le and not re:
        return "left", True
    if re and not le:
        return "right", True
    # Nose or eyes but no ear at all -- head is there, angle indeterminate.
    return ("toward" if len(eyes) >= 2 else "unclear"), True


class PoseDetector:
    """Drop-in alternative to LocalDetector: same observe() contract."""

    def __init__(self, model="yolov8n-pose.pt", phone_model="yolov8n.pt",
                 upright_angle=UPRIGHT_TORSO_ANGLE):
        self.upright_angle = upright_angle
        self.yolo = YOLO(weights_path(model)) if YOLO is not None else None
        # Pose models only detect people, so phone detection needs the plain
        # model. Pass phone_model=None to skip it and halve the inference cost.
        self.phone_yolo = YOLO(weights_path(phone_model)) \
            if (phone_model and YOLO is not None) else None
        self.cascades_ok = self.yolo is not None

    def observe(self, frame_bgr):
        """
        Facts about this frame. Mirrors LocalDetector.observe() and adds:

            posture       upright | reclined | lying | unknown
            torso_angle   degrees from vertical, or None
            keypoints     how many of the 17 were confidently seen

        `head_up` here means "the head was located", the same meaning it has
        in LocalDetector -- so the two are directly comparable on the same
        footage.
        """
        blank = {
            "present": False, "person_conf": 0.0, "head_up": False,
            "facing": None, "phone": False, "phone_conf": 0.0,
            "person_box": None, "posture": "unknown", "torso_angle": None,
            "keypoints": 0,
        }
        if self.yolo is None:
            return blank

        best = None
        best_conf = 0.0
        for r in self.yolo.predict(frame_bgr, verbose=False, conf=0.35):
            if r.keypoints is None:
                continue
            for box, kp in zip(r.boxes, r.keypoints.data):
                conf = float(box.conf[0])
                if conf > best_conf:
                    best_conf = conf
                    best = (tuple(int(v) for v in box.xyxy[0]), kp.tolist())

        phone, phone_conf = self._scan_phone(frame_bgr)
        if best is None:
            blank["phone"], blank["phone_conf"] = phone, round(phone_conf, 2)
            return blank

        box, kps = best
        angle = torso_angle(kps)
        facing, head_up = facing_from_head(kps)

        return {
            "present": True,
            "person_conf": round(best_conf, 2),
            "head_up": head_up,
            "facing": facing,
            "phone": phone,
            "phone_conf": round(phone_conf, 2),
            "person_box": box,
            "posture": posture_from_angle(angle, self.upright_angle),
            "torso_angle": round(angle, 1) if angle is not None else None,
            "keypoints": sum(1 for k in kps if k[2] >= KP_CONF),
        }

    def _scan_phone(self, frame_bgr):
        if self.phone_yolo is None:
            return False, 0.0
        conf = 0.0
        for r in self.phone_yolo.predict(frame_bgr, verbose=False, conf=0.35):
            for box in r.boxes:
                if int(box.cls[0]) == PHONE_CLASS_ID:
                    conf = max(conf, float(box.conf[0]))
        return conf > 0, conf


def place(state, trust_phone=True):
    """
    Coarse place/posture label, pose-aware.

    Supersedes camera_state.place() when a PoseDetector is in use: it can
    distinguish lying down from at_desk, which the box-overlap approach could
    not do at any threshold.

    See camera_state.place() for what trust_phone=False is for.
    """
    # Camera health outranks everything, including presence -- see
    # camera_state.place(). A dead Iriun feed is a person-free image, so
    # without this the pose model confidently reports an empty room.
    if state.get("camera_stalled"):
        return "camera_lost"
    if not state["present"]:
        return "absent"
    if trust_phone and state["phone"]:
        return "on_phone"
    posture = state.get("posture", "unknown")
    if posture == "lying":
        return "lying_down"
    if posture == "reclined":
        return "reclined"
    if state["head_up"]:
        return "at_desk"
    return "present_unclear"
