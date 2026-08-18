"""
What's on the screen.

The camera answers *where you are and how you're sitting*. It cannot answer
*what you're doing*, because "writing code" and "watching anime" are the same
image. That answer lives in the foreground window, and the OS hands it over in
under a millisecond for free.

Three signals:
    title    -- foreground window text (for a browser, this is the page title)
    process  -- the owning executable
    idle     -- seconds since your last keyboard/mouse input

Idle earns its place: it separates *consuming* from *doing*. Watching a lecture
and watching anime are both "browser, fullscreen, no input" -- but working is
almost never input-free for two minutes straight.

Standalone check:
    python src/window_sensor.py          # print the current window once
    python src/window_sensor.py watch    # print it every 2s until Ctrl+C
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time

try:
    import psutil
except Exception:
    psutil = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def get_idle_seconds():
    """Seconds since the last keyboard or mouse input, system-wide."""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    # GetTickCount wraps every ~49 days; mask to stay positive across the wrap.
    elapsed_ms = (kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def get_active_window():
    """Return (title, process_name). Either may be '' if it can't be read."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""

    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value or ""

    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    proc = ""
    if psutil is not None and pid.value:
        try:
            proc = psutil.Process(pid.value).name()
        except Exception:
            proc = ""
    return title, proc


class WindowClassifier:
    def __init__(self, rules_path=None):
        path = rules_path or os.path.join(ROOT, "apps.json")
        with open(path, "r", encoding="utf-8") as f:
            self.rules = json.load(f)
        self.idle_threshold = self.rules.get("idle_seconds_for_idle", 120)
        self.browsers = [b.lower() for b in self.rules.get("browser_processes", [])]
        self.passive = set(self.rules.get("passive_categories", []))

    def classify(self, title, process, idle_seconds):
        """
        Return a dict of FACTS, not a judgment.

        Deliberately does NOT collapse idle into the category. No input for
        five minutes means opposite things depending on what's open: while a
        video plays it's the activity working correctly, while VS Code is open
        it means you're probably not working. This sensor can't tell those
        apart -- only the camera knows whether you're still in the chair. So
        it reports both facts and lets the resolver combine them.

        Keys:
            category    what is on screen (content-derived)
            idle        no input for longer than the threshold
            passive     category is consume-only, so idle is expected there
        """
        t = (title or "").lower()
        p = (process or "").lower()
        idle = idle_seconds >= self.idle_threshold

        if not p:
            return self._result("unknown", 0.2, "no foreground window", idle, idle_seconds)

        if p == "lockapp.exe" or not t:
            return self._result("locked", 0.9, "screen locked", idle, idle_seconds)

        cat, conf, detail = self._by_content(t, p)
        return self._result(cat, conf, detail, idle, idle_seconds)

    def _result(self, category, confidence, detail, idle, idle_seconds):
        return {
            "category": category,
            "confidence": confidence,
            "detail": detail,
            "idle": idle,
            "idle_seconds": round(idle_seconds, 1),
            "passive": category in self.passive,
        }

    def _by_content(self, t, p):
        if p in self.browsers:
            for cat, needles in self.rules.get("browser_rules", {}).items():
                for n in needles:
                    if n.lower() in t:
                        return cat, 0.85, f"browser/{n}"
            return "browsing", 0.4, "browser, unrecognised page"

        for cat, needles in self.rules.get("process_rules", {}).items():
            for n in needles:
                if n.lower() in p:
                    return cat, 0.9, f"process/{n}"

        return "unknown", 0.2, f"unmapped: {p}"


def sample(classifier):
    """One reading: everything the screen sensor knows right now."""
    title, process = get_active_window()
    idle = get_idle_seconds()
    result = classifier.classify(title, process, idle)
    result["title"] = title
    result["process"] = process
    return result


def main():
    if psutil is None:
        print("[!] psutil not available -- process names will be blank.")
    clf = WindowClassifier()
    watch = len(sys.argv) > 1 and sys.argv[1] == "watch"

    while True:
        s = sample(clf)
        flags = []
        if s["idle"]:
            flags.append("IDLE")
        if s["passive"]:
            flags.append("passive")
        print(f"{s['category']:<12} idle={s['idle_seconds']:>6.1f}s  "
              f"{s['process']:<22} {s['detail']:<30} {' '.join(flags)}")
        print(f"             {s['title'][:100]}")
        if not watch:
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
