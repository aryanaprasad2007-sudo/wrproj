"""
The camera, de-flickered.

A single frame from a Haar cascade is a noisy measurement. Run the detector on
two consecutive frames of a person sitting perfectly still and it will
routinely find a head in one and not the other. Acting on single frames means
acting on noise.

The obvious fix -- a rolling window over the production samples -- is a trap
here. Production samples every 15 seconds, so a 5-sample window would lag by
over a minute. That is far too slow for a signal meant to catch you drifting.

Burst sampling avoids the trade entirely. The flicker is frame-to-frame noise,
so it averages out over ~1 second just as well as over 5 minutes. Every
production tick grabs N frames back-to-back, votes across them, and reports a
stable answer with no added latency. Cost is N YOLO inferences instead of one,
which on this machine is still far under the 15s budget.

    from camera_state import CameraState
    cam_state = CameraState(camera, detector)
    state = cam_state.sample()      # one burst -> one stable reading
"""
import time

import cv2

# How many frames per burst, and how long the burst is allowed to take.
BURST_FRAMES = 5
BURST_MAX_SECONDS = 2.0

# Every detector in this project sees frames at this width, and that is the
# point: analyze_session.py scores at MAX_WIDTH = 1280, so anything inferring
# at a different scale is not the thing that was measured. Since the camera now
# captures 4K (capture.py DEFAULT_WIDTH), the downscale has to happen HERE
# rather than in each caller -- otherwise mode_log.py and the dashboard quietly
# drift onto different scales and the 91% stops describing either of them.
#
# Cheap insurance: 2.1ms per 4K frame, against pose costing only 3.5ms more at
# full resolution. This is about comparability, not speed.
DETECT_WIDTH = 1280

# Vote thresholds, as a fraction of frames in the burst.
#
# These are deliberately NOT all 0.5. Each axis inherits the error profile of
# the detector behind it:
#
#   present  -- YOLO person detection is accurate and stable in both
#               directions, so a plain majority is right.
#   head_up  -- the Haar cascade has high precision and poor recall inside a
#               person box: a hit is strong evidence, a miss is weak. Requiring
#               a majority would throw away real detections, so one hit in
#               three counts. This asymmetry is the actual fix for the
#               "46% unsure" flicker.
#   phone    -- also precision-favoured, but this one can trigger an
#               intervention, so it is held to a higher bar than head_up.
PRESENT_RATIO = 0.5
HEAD_UP_RATIO = 0.34
PHONE_RATIO = 0.4


def vote(frames, key, ratio):
    """Fraction of readings where `key` was true, against a threshold."""
    if not frames:
        return False, 0.0
    hits = sum(1 for f in frames if f.get(key))
    frac = hits / len(frames)
    return frac >= ratio, frac


class CameraState:
    def __init__(self, camera, detector, burst=BURST_FRAMES):
        self.camera = camera
        self.detector = detector
        self.burst = burst

    def raw_burst(self, n=None):
        """
        Grab n frames back-to-back and run the detector on each.

        Returns the list of raw observations. Kept separate from the vote so
        validation can record raw bursts once and replay every burst size
        against them offline.
        """
        n = n or self.burst
        out = []
        deadline = time.time() + BURST_MAX_SECONDS
        while len(out) < n and time.time() < deadline:
            frame = self.camera.grab()
            if frame is None:
                continue
            if frame.shape[1] > DETECT_WIDTH:
                scale = DETECT_WIDTH / frame.shape[1]
                frame = cv2.resize(
                    frame, (DETECT_WIDTH, int(round(frame.shape[0] * scale))),
                    interpolation=cv2.INTER_AREA)
            obs = self.detector.observe(frame)
            # A stalled feed poisons the vote in the worst possible way: five
            # copies of one synthetic frame agree unanimously, so the burst
            # reports maximum confidence in an answer drawn from no evidence.
            # Stamping it on every observation keeps reduce() static and lets
            # recorded bursts replay without a camera attached.
            obs["camera_stalled"] = getattr(self.camera, "stalled", False)
            out.append(obs)
        return out

    def sample(self, n=None):
        """One burst, voted down to a stable reading."""
        frames = self.raw_burst(n)
        return self.reduce(frames)

    @staticmethod
    def reduce(frames):
        """
        Vote a burst of raw observations into one reading.

        Static and pure, so validation can call it on recorded bursts without
        a camera attached.
        """
        if not frames:
            return {
                "present": False, "head_up": False, "phone": False,
                "frames": 0, "present_frac": 0.0, "head_frac": 0.0,
                "phone_frac": 0.0, "agreement": 0.0, "facing": None,
                "camera_stalled": False,
                "posture": "unknown", "torso_angle": None,
            }

        stalled = any(f.get("camera_stalled") for f in frames)

        present, present_frac = vote(frames, "present", PRESENT_RATIO)
        phone, phone_frac = vote(frames, "phone", PHONE_RATIO)

        # Only frames that saw a person get a say in posture. A frame with no
        # person has no opinion about head position; letting it vote "no head"
        # would make an empty chair look like a slumped one.
        seen = [f for f in frames if f.get("present")]
        head_up, head_frac = vote(seen, "head_up", HEAD_UP_RATIO)
        if not present:
            head_up, head_frac = False, 0.0

        facings = [f.get("facing") for f in seen if f.get("facing")]
        facing = max(set(facings), key=facings.count) if facings else None

        # Posture has to be carried HERE, not by each caller.
        #
        # It used to live only in analyze_session.reduce_burst(), so the replay
        # pipeline saw posture and the live pipeline did not -- and since
        # pose_detector.place() reads state["posture"], `reclined` and
        # `lying_down` were unreachable in mode_log.py and the dashboard. The
        # whole bed-at-night branch of resolve_mode() was dead at runtime while
        # looking perfectly alive in the code and in the scored replays.
        #
        # Only frames that saw a person vote: an empty frame has no opinion
        # about posture, and a burst that voted "nobody here" must not report
        # one, or the CSV reads present=False alongside posture=lying.
        postures = [f.get("posture") for f in seen]
        postures = [p for p in postures if p and p != "unknown"]
        posture = max(set(postures), key=postures.count) if postures else "unknown"

        # Median, not mean: one frame with a badly-placed hip keypoint swings a
        # mean hard, and the median simply ignores it.
        angles = sorted(f["torso_angle"] for f in seen
                        if f.get("torso_angle") is not None)
        torso_angle = angles[len(angles) // 2] if angles else None

        if not present:
            posture, torso_angle = "unknown", None

        # How unanimous the burst was, on the axis we actually acted on.
        # Low agreement is the signal to escalate to Claude, replacing the old
        # "unsure" verdict with something measured rather than categorical.
        agreement = max(present_frac, 1.0 - present_frac)

        return {
            "present": present, "head_up": head_up, "phone": phone,
            "facing": facing, "frames": len(frames),
            "present_frac": round(present_frac, 2),
            "head_frac": round(head_frac, 2),
            "phone_frac": round(phone_frac, 2),
            "agreement": round(agreement, 2),
            "camera_stalled": stalled,
            "posture": posture,
            "torso_angle": torso_angle,
        }


def place(state, trust_phone=True):
    """
    Collapse a camera reading into a coarse place/posture label.

    This is all the camera is allowed to say. It deliberately carries no
    judgment -- "at_desk" is not "productive", because the camera cannot see
    the screen. The resolver combines this with the window sensor.

    trust_phone=False drops the phone branch. On a rig where the phone IS the
    camera (Iriun), phone-in-hand cannot be observed by construction -- but
    the detector can still fire on someone else's phone or a dark rectangular
    object. Since that branch overrides everything, a false positive there is
    expensive and a true positive is impossible. See trust_phone_detection in
    modes.json. `phone` stays in the reading either way, so analysis can still
    measure how often it would have misfired.
    """
    # Before anything else: does the camera still work? A dead Iriun feed
    # produces a placeholder image with no person in it, which is a perfectly
    # convincing "absent". `absent` is a claim about HIM; `camera_lost` is a
    # claim about the RIG, and the log is worthless if it cannot tell them
    # apart -- an hour of dropout would read as an hour of him being out.
    if state.get("camera_stalled"):
        return "camera_lost"
    if not state["present"]:
        return "absent"
    if trust_phone and state["phone"]:
        return "on_phone"
    if state["head_up"]:
        return "at_desk"
    return "present_unclear"
