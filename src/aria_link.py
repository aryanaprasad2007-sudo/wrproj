"""
Two local models, with a hard wall between them.

    qwen2.5:7b (via Aria's server)  writes the deviation line
    moondream  (via Ollama direct)  captions the thumbnail

The wall is the point. Aria is handed a block of RECORDED FACTS and nothing
else -- no image, no camera access -- so she physically cannot assert what the
room looked like. Moondream does see the frame, and everything it says is
therefore a guess; its output is confined to the tile and labelled as such.

That split exists because of two things already in this repo:

  * `mode_log.py`'s house rule: every claim in an intervention must come from
    recorded data. One invented observation and it reads as a gimmick forever.
  * `persona/aria.yaml` carries scar tissue from qwen2.5 inventing file
    contents it had never read, and inventing reminders it never set. A 7B
    model given room to speculate will speculate.

So: nouns in the deviation line have to appear in the facts dict first, and
anything from the vision model is marked unverified in the UI.

Aria is not rebuilt here. `server.py` says "one brain, many thin clients" --
this is another thin client, and if her server is down the dashboard degrades
to facts-only rather than putting words in her mouth.
"""
import base64
import json
import os
import urllib.error
import urllib.request

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARIA_DIR = os.path.join(ROOT, "aria-assistant")

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
VISION_MODEL = "moondream"

# Her own session, so tracker chatter never lands in the conversation he
# actually has with her. data/conversations.json is keyed by session_id.
SESSION = "lifestyle-tracker"

VISION_PROMPT = (
    "Describe what the person is doing in one short phrase, 8 words maximum. "
    "Only describe what is visibly happening. Do not guess mood, feelings, "
    "energy level, or whether they are focused. If no person is visible, "
    "answer exactly: no person visible."
)

# Words that mean the vision model stopped reporting and started diagnosing.
# It is asked not to, and mostly complies, but "looks tired" surviving into
# the UI is exactly the failure that discredits the whole panel -- so it is
# filtered rather than trusted.
BANNED = ("tired", "focused", "distracted", "bored", "sad", "happy", "stressed",
          "relaxed", "unproductive", "productive", "lazy", "engaged", "anxious")


def _env(name):
    """Read one key out of aria-assistant/.env without importing dotenv."""
    if os.environ.get(name):
        return os.environ[name].strip()
    path = os.path.join(ARIA_DIR, ".env")
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{name}=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _post(url, payload, timeout, headers=None):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------
# vision: the tile caption
# --------------------------------------------------------------------------

def caption(frame_bgr, timeout=25):
    """
    One short phrase describing the visible act, or None.

    Returns None rather than a placeholder when the model is unavailable or
    editorialises, because a tile with no caption is honest and a tile with a
    made-up one is not.
    """
    small = frame_bgr
    if small.shape[1] > 640:
        scale = 640 / small.shape[1]
        small = cv2.resize(small, (640, int(small.shape[0] * scale)))
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return None

    try:
        data = _post(f"{OLLAMA}/api/generate", {
            "model": VISION_MODEL,
            "prompt": VISION_PROMPT,
            "images": [base64.b64encode(buf.tobytes()).decode()],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 40},
        }, timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None

    text = (data.get("response") or "").strip().strip('"').rstrip(".")
    if not text:
        return None
    low = text.lower()
    if any(w in low for w in BANNED):
        return None
    if "no person visible" in low:
        return "no person visible"
    return " ".join(text.split()[:10])


# --------------------------------------------------------------------------
# Aria: the deviation line
# --------------------------------------------------------------------------

def aria_health(timeout=3):
    try:
        with urllib.request.urlopen(
                f"{_env('ASSISTANT_URL') or 'http://127.0.0.1:8000'}/health",
                timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _prompt(facts):
    """
    The facts, plus an explicit ban on adding any.

    Written as an observation report rather than a question, because asking a
    small model "how is he doing?" invites narrative. Handing it a table and
    asking for one line about the gap keeps it anchored.
    """
    dev = facts.get("deviation", {})
    lines = [
        "This is an automated status ping from Ari's lifestyle tracker, not "
        "Ari talking to you. Everything below was measured by the camera and "
        "the window sensor in the last few minutes.",
        "",
        "OBSERVED RIGHT NOW:",
    ]
    for key in ("clock", "block_name", "block_window", "minutes_into_block",
                "minutes_left_in_block", "observed_mode", "minutes_in_this_mode",
                "camera_sees", "screen_app", "screen_category",
                "screen_idle_seconds", "block_expects",
                "being_away_is_fine_here"):
        if key in facts and facts[key] not in (None, ""):
            lines.append(f"  {key}: {facts[key]}")

    lines += [
        "",
        f"VERDICT FROM THE TRACKER: {dev.get('status')} -- {dev.get('reason')}",
        "",
        "Say ONE short line to Ari about this. Two sentences maximum.",
        "",
        "Hard rules:",
        "  - Use only the facts above. Do not invent anything you were not "
        "told -- not what the room looks like, not how he seems, not what he "
        "did earlier today.",
        "  - You cannot see him. You were given a table, not a picture.",
        "  - If the verdict is on_plan, a short acknowledgement is enough. Do "
        "not manufacture a problem.",
        "  - If the verdict is unknown, say the tracker cannot tell right now. "
        "Do not guess what he is doing.",
    ]
    if facts.get("register") == "study":
        lines.append("  - He is mid-work. Keep it to one line and skip the bit "
                     "-- every joke costs him re-entry.")
    return "\n".join(lines)


def ask_aria(facts, timeout=90):
    """
    Aria's line for this moment, or None if she is not reachable.

    None is not an error state to paper over: the dashboard shows the facts
    without her rather than substituting a generic message, because a line
    attributed to her that she did not say is worse than no line.
    """
    token = _env("ASSISTANT_TOKEN")
    base = _env("ASSISTANT_URL") or "http://127.0.0.1:8000"
    if not token:
        return None
    try:
        data = _post(f"{base}/chat", {
            "session_id": SESSION,
            "message": _prompt(facts),
        }, timeout, {"Authorization": f"Bearer {token}"})
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None

    text = data.get("text") or data.get("message") or data.get("reply") or ""
    if isinstance(text, list):
        text = " ".join(str(t) for t in text)
    text = str(text).strip()
    if not text:
        return None

    # Her persona has her open every reply with one [emotion] tag, but the
    # engine already strips it and hands it back as `tag` -- so read that
    # first. The bracket-parsing branch below is only a fallback for a raw
    # reply that still carries the tag inline.
    emotion = (data.get("tag") or "").strip().lower() or None
    if emotion is None and text.startswith("["):
        end = text.find("]")
        if 0 < end < 20:
            emotion = text[1:end].strip().lower()
            text = text[end + 1:].strip()
    return {"text": text, "emotion": emotion,
            "model": data.get("model") or "qwen2.5:7b"}


if __name__ == "__main__":
    import sys
    from datetime import datetime
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    h = aria_health()
    print(f"\n  aria server : {h if h else 'NOT RUNNING (run_server.py)'}")
    print(f"  token set   : {'yes' if _env('ASSISTANT_TOKEN') else 'NO'}")

    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=4) as r:
            tags = [m["name"] for m in json.loads(r.read())["models"]]
        print(f"  ollama      : {tags}")
    except Exception as e:
        print(f"  ollama      : unreachable ({e})")

    if "--vision" in sys.argv:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from capture import Camera
        cam = Camera(0)
        frame = cam.grab()
        cam.release()
        print(f"\n  caption     : {caption(frame)!r}")

    if "--aria" in sys.argv:
        import profile_plan
        now = datetime.now()
        block = profile_plan.plan_for_now(now)
        f = profile_plan.facts(block, "leisure", "at desk, anime, watching", 23,
                               {"category": "anime", "idle": True,
                                "idle_seconds": 400, "app": "Crunchyroll"},
                               "at_desk", now)
        print("\n--- prompt ---")
        print(_prompt(f))
        print("\n--- reply ---")
        print(ask_aria(f))
    print()
