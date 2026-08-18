"""
Webcam productivity coach.

Loop:
  capture frame -> local detector -> (ask Claude if unsure) -> track lazy streak
  -> flash the screen when the streak crosses the threshold.

Run from the project root:   python src/main.py
Stop with Ctrl+C.
"""
import csv
import json
import os
import time
from datetime import datetime

from capture import Camera
from local_detector import LocalDetector
from claude_judge import ClaudeJudge
from reinforcement import Reinforcer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    with open(os.path.join(ROOT, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def update_lazy_streak(streak, verdict, cfg):
    """
    Decide how one verdict moves the lazy streak.

    The streak is what drives the punishment: once it reaches
    cfg["lazy_streak_to_flash"], the screen flashes, and it keeps escalating
    the higher the streak climbs.

    Args:
        streak:  int, the current streak going into this check
        verdict: one of "productive", "lazy", "away"
        cfg:     the parsed config.json dict

    Returns:
        int, the new streak (never negative)

    TODO(ari): implement the streak policy you want to live under.

    The core question is what a "productive" frame should do to a streak
    you've already built up:

      Instant reset (streak = 0)
        Forgiving, and the simplest to reason about. But it's gameable --
        scroll your phone for two minutes, glance up for one frame, and the
        counter wipes clean. In practice you learn to look up periodically
        instead of actually refocusing.

      Decay (streak -= 1)
        You have to put in real productive time to work off a lazy stretch.
        Much harder to game, but it can keep nagging after you've genuinely
        gotten back to work, which trains you to resent the tool.

      Something in between
        e.g. reset only after N consecutive productive frames, or decay fast
        at low streaks and slowly at high ones.

    Also decide what "away" means for you. cfg["away_counts_as_lazy"] exists,
    but you may want a third behavior: leaving your desk is neither productive
    nor lazy, so the streak should freeze rather than climb or reset -- that
    way a bathroom break doesn't punish you, but it doesn't launder a lazy
    streak either.
    """
    raise NotImplementedError("implement update_lazy_streak")


def main():
    cfg = load_config()

    cam = Camera(cfg.get("camera_index", 0))
    local = LocalDetector()
    judge = ClaudeJudge(cfg["claude_model"], cfg["productive_definition"])
    reinforcer = Reinforcer(cfg["flash"])

    print(f"[*] Camera connected via {cam.backend_name}.")
    if cfg.get("use_claude_when_unsure") and not judge.available:
        print("[!] Claude tie-breaker is ON but no ANTHROPIC_API_KEY found — "
              "unsure frames will be treated as 'lazy'. Set the key to enable it.")

    log_path = os.path.join(ROOT, cfg.get("log_file", "activity_log.csv"))
    new_log = not os.path.exists(log_path)
    log = open(log_path, "a", newline="", encoding="utf-8")
    writer = csv.writer(log)
    if new_log:
        writer.writerow(["timestamp", "verdict", "source", "reason", "lazy_streak"])

    interval = cfg.get("interval_seconds", 15)
    threshold = cfg.get("lazy_streak_to_flash", 3)

    lazy_streak = 0
    consecutive_failures = 0
    print(f"[*] Watching every {interval}s. Flash after {threshold} lazy checks. Ctrl+C to stop.")

    try:
        while True:
            frame = cam.grab()
            if frame is None:
                # Iriun streams over WiFi -- a few dropped frames are normal,
                # a sustained run of them means the phone actually went away.
                consecutive_failures += 1
                print(f"[!] Dropped frame ({consecutive_failures}).")
                if consecutive_failures >= 3:
                    print("[*] Reconnecting to camera...")
                    try:
                        cam.reconnect()
                        consecutive_failures = 0
                    except RuntimeError as e:
                        print(f"[!] Reconnect failed: {e}")
                        time.sleep(10)
                time.sleep(2)
                continue
            consecutive_failures = 0

            verdict, conf, reason = local.classify(frame)
            source = "local"

            if verdict == "unsure":
                if cfg.get("use_claude_when_unsure") and judge.available:
                    verdict = judge.judge(frame)
                    source = "claude"
                    reason = "local unsure -> claude decided"
                else:
                    verdict = "lazy"  # fail toward nudging when we can't ask

            lazy_streak = update_lazy_streak(lazy_streak, verdict, cfg)

            ts = datetime.now().isoformat(timespec="seconds")
            print(f"{ts}  {verdict:<10} [{source}] streak={lazy_streak}  ({reason})")
            writer.writerow([ts, verdict, source, reason, lazy_streak])
            log.flush()

            if lazy_streak >= threshold:
                level = lazy_streak - threshold + 1   # escalate the longer it persists
                reinforcer.flash(level)

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[*] Stopping.")
    finally:
        cam.release()
        reinforcer.close()
        log.close()


if __name__ == "__main__":
    main()
