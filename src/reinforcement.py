"""
Negative reinforcement: an escalating translucent red overlay that flashes
across the screen. Uses tkinter (bundled with Python) -- no extra install.

A single hidden root is kept for the process lifetime and a fullscreen overlay
window is shown/hidden on demand, which is more reliable on Windows than
creating a new Tk() per flash.
"""
import time
import tkinter as tk


class Reinforcer:
    def __init__(self, flash_cfg):
        self.cfg = flash_cfg
        self.root = tk.Tk()
        self.root.withdraw()

        self.overlay = tk.Toplevel(self.root)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)       # no title bar / borders
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-fullscreen", True)
        self.overlay.configure(bg=flash_cfg.get("color", "#ff0000"))
        self.overlay.attributes("-alpha", 0.0)

    def flash(self, level):
        """
        Pulse the overlay. `level` (1, 2, 3, ...) scales how intense and how
        long the flash is -- the longer you stay lazy, the harder it nudges.
        """
        base = self.cfg.get("base_alpha", 0.35)
        cap = self.cfg.get("max_alpha", 0.85)
        peak = min(base + 0.18 * (level - 1), cap)
        duration = self.cfg.get("duration_seconds", 2.5) * min(level, 3)

        self.overlay.deiconify()
        self.overlay.lift()

        end = time.time() + duration
        # ~3 pulses per second using a sine-like up/down ramp.
        while time.time() < end:
            t = time.time()
            phase = (t * 3) % 1.0
            tri = 1.0 - abs(2.0 * phase - 1.0)   # 0 -> 1 -> 0 triangle wave
            self.overlay.attributes("-alpha", peak * tri)
            self.overlay.update()
            time.sleep(0.02)

        self.overlay.attributes("-alpha", 0.0)
        self.overlay.withdraw()
        self.root.update()

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass
