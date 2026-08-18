"""
A torso baseline that measures itself, because the camera keeps moving.

The old design had `UPRIGHT_TORSO_ANGLE = -47.0` compiled in and a
`--calibrate` command to re-measure it. That is wrong for this rig, not just
inconvenient: the camera is a phone that gets picked up for unrelated reasons
several times a day, so an absolute baseline is stale within hours and there
is no moment at which it is reliably correct. Worse, a stale baseline fails
SILENTLY -- every posture reading is simply wrong, and nothing in the log says
so.

The fix is to stop storing an angle and start storing a habit. He is upright
the overwhelming majority of the time he is in frame (IMG_9874: 100% at_desk
across 24 minutes), so:

    the running median of observed torso angles IS his upright posture

Move the camera and the median follows on its own within an hour. There is no
calibration step because there is nothing to calibrate.

WHY A MEDIAN AND NOT A MEAN
A stretch of genuinely lying down should not drag the baseline. The median of
a window that is mostly upright ignores the tail entirely, where a mean would
be pulled toward it proportionally.

WHY THE BANDS ARE WIDE
Upright versus horizontal is close to a 90-degree difference. The old
UPRIGHT_MAX of 35 degrees was trying to resolve `reclined` as a third class in
between, which is what demanded precision -- and that class was actively
harmful, since leaning back in a desk chair scored as being in bed. Two
classes with a 55-degree gate is a decision no amount of camera drift can
confuse, which is the entire point.
"""
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "logs", "torso_baseline.json")

# How many recent angle observations define "normal". At the 15s production
# interval this is a few hours of desk time -- long enough that a genuine
# lying-down stretch cannot take over the median, short enough that the
# baseline follows a camera move within about an hour of use.
WINDOW = 400

# Everything beyond this many degrees from normal counts as lying down.
# Deliberately generous. `reclined` is gone as a class: it needed precision to
# separate, and it routed a desk-chair lean to watching_in_bed.
LYING_MIN = 55

# Until there are this many samples, report no opinion rather than a shaky
# one. `None` is handled everywhere as "unknown", never as a posture.
MIN_SAMPLES = 12

# How many observations between disk writes. Small on purpose: at the 15s
# production interval, 20 meant a five-minute window in which
# `torso_baseline.py` on the command line reported 0 samples while the running
# dashboard had plenty -- two sources of truth for one number -- and a
# dashboard killed before its first write lost everything it had learned.
# The file is a few KB; the write is not worth optimising.
SAVE_EVERY = 5


class TorsoBaseline:
    def __init__(self, path=STATE, window=WINDOW):
        self.path = path
        self.window = window
        self.angles = []
        self._since_save = 0
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.angles = [float(a) for a in data.get("angles", [])][-self.window:]
        except (OSError, ValueError, TypeError):
            self.angles = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"angles": self.angles[-self.window:],
                       "baseline": self.current(),
                       "samples": len(self.angles),
                       "updated": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
        os.replace(tmp, self.path)      # atomic: never a half-written baseline
        self._since_save = 0

    def observe(self, angle):
        """
        Feed one measured torso angle in.

        Everything is fed in, including angles that will be judged as lying.
        Filtering to "only frames that already look upright" would make the
        baseline confirm whatever it currently believes, which is the exact
        circularity that lets a wrong baseline persist forever.
        """
        if angle is None:
            return
        was_ready = len(self.angles) >= MIN_SAMPLES
        self.angles.append(float(angle))
        del self.angles[:-self.window]
        self._since_save += 1
        # Always persist the moment the baseline first becomes usable, so the
        # first real answer survives a crash even if SAVE_EVERY hasn't elapsed.
        if self._since_save >= SAVE_EVERY or (
                not was_ready and len(self.angles) >= MIN_SAMPLES):
            self.save()

    def current(self):
        """Median observed angle, or None while still learning."""
        if len(self.angles) < MIN_SAMPLES:
            return None
        s = sorted(self.angles)
        return round(s[len(s) // 2], 1)

    def deviation(self, angle):
        """Signed degrees from normal, wrapped to +/-180. None if not ready."""
        base = self.current()
        if base is None or angle is None:
            return None
        d = angle - base
        while d > 180:
            d -= 360
        while d < -180:
            d += 360
        return d

    def posture(self, angle):
        """
        'upright', 'lying', or 'unknown'.

        Unsigned deviation on purpose. The direction of the lean genuinely does
        not matter for this call: forward over the keyboard and back in the
        chair are both still at the desk, and neither is close to horizontal.
        The sign mattered when a narrow `reclined` band sat between them; with
        that class gone, it does not.
        """
        d = self.deviation(angle)
        if d is None:
            return "unknown"
        return "lying" if abs(d) > LYING_MIN else "upright"

    def report(self):
        base = self.current()
        out = {"samples": len(self.angles), "baseline": base,
               "ready": base is not None, "window": self.window,
               "lying_beyond_deg": LYING_MIN}
        if base is not None and self.angles:
            s = sorted(self.angles)
            out["spread_68pct"] = round(s[int(len(s) * .84)] - s[int(len(s) * .16)], 1)
            out["min"], out["max"] = round(s[0], 1), round(s[-1], 1)
        return out


if __name__ == "__main__":
    import sys
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    # Prefer the live process if one is up. The file lags it by up to
    # SAVE_EVERY samples, and reporting a stale 0 next to a running dashboard
    # that knows better is exactly the kind of quiet disagreement this project
    # keeps getting bitten by.
    live = None
    try:
        import json as _json
        import urllib.request as _u
        live = _json.load(_u.urlopen("http://127.0.0.1:8787/api/baseline",
                                     timeout=3))
    except Exception:
        live = None

    if live:
        r, source = live, "live dashboard"
    else:
        r, source = TorsoBaseline().report(), "logs/torso_baseline.json"
    print(f"\n  source   {source}")
    print(f"  samples  {r['samples']} (window {r['window']})")
    print(f"  baseline {r['baseline']}" if r["ready"]
          else f"  baseline still learning ({MIN_SAMPLES} needed)")
    if r.get("spread_68pct") is not None:
        print(f"  spread   {r['spread_68pct']} deg (68%)   "
              f"range {r['min']}..{r['max']}")
    print(f"  lying if more than {LYING_MIN} deg from normal\n")
