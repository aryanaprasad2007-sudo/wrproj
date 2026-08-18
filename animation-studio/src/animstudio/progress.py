"""Per-shot progress, ETA, and the run manifest.

A short film is dozens of sequential generations over several hours, so "how
long is this going to take" is a real operational question, not a nicety.

The ETA deliberately uses a trailing median of completed shots rather than a
running mean. Shot times here are bimodal -- the first shot of a run pays
model load (60-90 s), a shot with ControlNet pays another load, and everything
after that is fast. A mean lets those one-off loads poison the estimate for
the entire run; a median of the last few shots tracks the steady state.

Every completed shot is appended to `run.jsonl` in the film directory. That
file is what makes `--resume` possible and is also a genuine production log:
which seed, which backend, how long, what it cost.
"""
from __future__ import annotations

import json
import logging
import pathlib
import statistics
import sys
import time

log = logging.getLogger(__name__)


def _fmt(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


class RunTracker:
    """Times shots, estimates the finish, and writes the run log."""

    #: How many recent shots the median is taken over. Small enough to react
    #: to a preset change mid-run, large enough not to swing on one outlier.
    WINDOW = 5

    def __init__(self, film_dir, total_shots: int, clock=time.time):
        self.film_dir = pathlib.Path(film_dir)
        self.film_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.film_dir / "run.jsonl"
        self.total = total_shots
        self.clock = clock          # injectable so tests can move time
        self.started = clock()
        self.durations = []
        self.done = 0
        self.failed = []

    # ------------------------------------------------------------- context
    def shot(self, shot_id: str):
        return _ShotTimer(self, shot_id)

    # -------------------------------------------------------------- report
    def _eta(self):
        if not self.durations:
            return None
        recent = self.durations[-self.WINDOW:]
        per_shot = statistics.median(recent)
        return per_shot * (self.total - self.done)

    def record(self, shot_id: str, seconds: float, stages: dict, ok=True, error=""):
        self.done += 1
        if ok:
            self.durations.append(seconds)
        else:
            self.failed.append(shot_id)

        entry = {
            "shot": shot_id,
            "ok": ok,
            "seconds": round(seconds, 2),
            "stages": {k: round(v, 2) for k, v in stages.items()},
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if error:
            entry["error"] = error[:500]
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

        eta = self._eta()
        stage_str = " ".join(f"{k}={_fmt(v)}" for k, v in stages.items() if v > 0.5)
        log.info(
            "[%d/%d] %s %s in %s  (%s)%s",
            self.done, self.total, "OK  " if ok else "FAIL", shot_id,
            _fmt(seconds), stage_str or "-",
            f"  ETA {_fmt(eta)}" if eta else "",
        )

    def summary(self) -> str:
        elapsed = self.clock() - self.started
        ok = self.done - len(self.failed)
        lines = [
            f"{ok}/{self.total} shots rendered in {_fmt(elapsed)}",
        ]
        if self.durations:
            lines.append(
                f"  per shot: median {_fmt(statistics.median(self.durations))}, "
                f"min {_fmt(min(self.durations))}, max {_fmt(max(self.durations))}"
            )
        if self.failed:
            lines.append(f"  FAILED: {', '.join(self.failed)}")
            lines.append(f"  retry with: --only {','.join(self.failed)}")
        lines.append(f"  log: {self.log_path}")
        return "\n".join(lines)

    # ------------------------------------------------------------- resume
    def completed_shots(self) -> set:
        """Shot ids that already succeeded, read back from run.jsonl."""
        done = set()
        if not self.log_path.exists():
            return done
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("ok"):
                done.add(e["shot"])
            else:
                # A shot that later failed must not stay "done" -- otherwise a
                # resume skips exactly the shot that needs redoing.
                done.discard(e["shot"])
        return done


class _ShotTimer:
    """Times one shot and its individual stages."""

    def __init__(self, tracker: RunTracker, shot_id: str):
        self.tracker = tracker
        self.shot_id = shot_id
        self.stages = {}
        self._t0 = None
        self._stage_t0 = None
        self._stage = None

    def __enter__(self):
        self._t0 = self.tracker.clock()
        log.info("[%d/%d] --- %s ---", self.tracker.done + 1, self.tracker.total, self.shot_id)
        return self

    def stage(self, name: str):
        now = self.tracker.clock()
        if self._stage:
            self.stages[self._stage] = self.stages.get(self._stage, 0) + (now - self._stage_t0)
        self._stage, self._stage_t0 = name, now

    def __exit__(self, exc_type, exc, tb):
        now = self.tracker.clock()
        if self._stage:
            self.stages[self._stage] = self.stages.get(self._stage, 0) + (now - self._stage_t0)
        self.tracker.record(
            self.shot_id, now - self._t0, self.stages,
            ok=exc_type is None,
            error="" if exc is None else f"{exc_type.__name__}: {exc}",
        )
        return False    # never swallow; the caller decides whether to continue


def setup_logging(verbose=False, log_file=None):
    """Console + optional file logging.

    stdout is reconfigured to UTF-8 because this box's console is cp1252 and
    model names, prompts and character names routinely contain non-ASCII --
    a UnicodeEncodeError in the logging path would kill an otherwise good run.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        pathlib.Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )
    # These libraries log a wall of per-step noise at INFO.
    for noisy in ("diffusers", "transformers", "huggingface_hub", "accelerate", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
