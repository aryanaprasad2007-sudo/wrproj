"""The orchestrator: shot list in, film out.

Layout on disk, one directory per shot, because the whole point is that any
single shot can be redone without rebuilding the film:

    projects/<film>/
      run.jsonl                  append-only production log (also drives --resume)
      <film>.mp4                 final assembly
      shots/<id>/
        keyframe.png             Stage A  <- judge character consistency HERE
        carry.png                the frame handed to the next shot
        frames/                  Stage B, raw generated PNGs
        frames_up/               Stage C1, upscaled
        frames_final/            Stage C2, interpolated (RIFE path only)
        clip.mp4                 the shot, finished
        meta.json                exactly what produced it

Model residency is the constraint that shapes the run order. Stage A and Stage
B cannot both hold weights on an 8 GB card, so the pipeline renders ALL
keyframes first, unloads SDXL, then animates all of them. That is one model
swap per run instead of one per shot -- on a 40-shot film it saves roughly
40 minutes of pure loading.
"""
from __future__ import annotations

import json
import logging
import pathlib

from . import assemble, characters, hardware, interpolate, keyframe, progress, upscale
from .video import registry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Continuity policy
# ---------------------------------------------------------------------------
def select_carry_frame(frames, shot):
    """Choose WHICH frame of a finished shot seeds the next one.

    <<< YOUR CALL -- see the note in the README, "Continuity policy" >>>

    This is a real trade-off, not boilerplate, and it changes how the film
    feels more than any single parameter here:

      * LAST frame (current default)
          Perfect temporal continuity -- shot N+1 starts exactly where shot N
          stopped. But small video models degrade *over* a clip: the last
          frame is usually the blurriest and the most drifted from your
          character design. Carrying it compounds that drift down the chain,
          so by shot 8 the character has quietly become someone else.

      * FIRST frame
          Sharpest and closest to the Stage A keyframe, so drift never
          accumulates. But it throws away the motion -- shot N+1 begins where
          shot N *began*, which reads as a jump cut backwards.

      * SHARPEST frame (variance of Laplacian)
          Picks the crispest frame regardless of position. Resists drift well;
          can pick a frame from the middle, so continuity is approximate.

      * Blend: e.g. 3 frames from the end, or sharpest within the last third
          The usual compromise -- near the end for continuity, but backed off
          from the very last frame where degradation is worst.

    Args:
        frames: list of PIL.Image, the finished shot in order.
        shot:   the Shot, if you want per-shot behaviour (e.g. shot.notes,
                or a fast camera move wanting the last frame regardless).

    Returns:
        one PIL.Image from `frames`.
    """
    # TODO(you): implement the policy you actually want.
    # A sharpness-aware version is roughly 6 lines:
    #     import numpy as np
    #     tail = frames[-max(1, len(frames)//3):]
    #     score = lambda im: np.asarray(im.convert("L"), float).var()
    #     return max(tail, key=score)
    # Conservative default: exact continuity, accepting drift.
    return frames[-1]


def resolve_carryover(shot, shot_dirs):
    """Find the image a carryover shot should start from.

    Returns (PIL.Image or None, strength). Strength is the img2img denoise:
    low keeps the previous look and ignores the new prompt, high does the
    opposite. 0.5-0.6 is the band where the scene stays recognisable while
    the prompt still lands.
    """
    if not shot.carry_from:
        return None, 0.0
    src = shot_dirs.get(shot.carry_from)
    if src is None:
        log.warning("shot '%s' carries from '%s' which was not rendered this run",
                    shot.id, shot.carry_from)
        return None, 0.0
    carry = pathlib.Path(src) / "carry.png"
    if not carry.exists():
        log.warning("shot '%s': no carry.png in %s (was it rendered?)", shot.id, src)
        return None, 0.0
    from PIL import Image
    return Image.open(carry).convert("RGB"), shot.carry_strength


# ---------------------------------------------------------------------------
class Pipeline:
    STAGES = ("keyframe", "video", "post", "assemble")

    def __init__(self, cfg, film: str, hw=None):
        self.cfg = cfg
        self.film = film
        self.hw = hw or hardware.detect()
        self.film_dir = cfg.work_root / film
        self.cast = characters.CastRegistry.load(cfg.root / "characters")
        self._kf = None
        self._vid = None

    # ------------------------------------------------------------ helpers
    def shot_dir(self, shot_id: str) -> pathlib.Path:
        d = self.film_dir / "shots" / shot_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _resolve_ref(self, shotlist, rel):
        if not rel:
            return None
        p = pathlib.Path(rel)
        return p if p.is_absolute() else (shotlist.source.parent / p)

    # ---------------------------------------------------------- stage A
    def render_keyframes(self, shots, shotlist, preset, tracker=None):
        """All keyframes, then unload. One model swap for the whole run."""
        if self._kf is None:
            self._kf = keyframe.KeyframeRenderer(self.cfg, self.hw)

        made = {}
        for shot in shots:
            d = self.shot_dir(shot.id)
            out = d / "keyframe.png"
            p = self.cfg.preset(shot.preset or preset.name)

            cast = self.cast.resolve(shot.characters)
            prompt, negative, loras, ip_images, ip_weight = characters.compose_conditioning(
                cast, shot, self.cfg.negative_default
            )

            init, strength = resolve_carryover(shot, {s.id: self.shot_dir(s.id) for s in shots})
            # An explicit ref_image on the shot overrides carryover: it is a
            # deliberate authored choice, carryover is an automatic one.
            ref = self._resolve_ref(shotlist, shot.ref_image)
            if ref and ref.exists():
                from PIL import Image
                init, strength = Image.open(ref).convert("RGB"), shot.carry_strength

            control = {k: str(self._resolve_ref(shotlist, v)) for k, v in shot.control.items()}

            self._kf.render(
                prompt=prompt, negative=negative,
                width=p.width, height=p.height,
                steps=p.keyframe_steps, cfg_scale=p.keyframe_cfg,
                seed=shot.resolved_seed(),
                loras=loras, ip_images=ip_images, ip_weight=ip_weight,
                control=control, control_scale=shot.control_scale,
                init_image=init, strength=strength,
                out_path=out,
            )
            made[shot.id] = out
            (d / "meta.json").write_text(json.dumps({
                "shot": shot.id, "prompt": prompt, "negative": negative,
                "seed": shot.resolved_seed(), "preset": p.name,
                "characters": shot.characters,
                "loras": [[str(a), b] for a, b in loras],
                "carried_from": shot.carry_from,
            }, indent=2), encoding="utf-8")
        return made

    def unload_keyframe(self):
        if self._kf:
            self._kf.unload()
            self._kf = None

    # ---------------------------------------------------------- stage B
    def _backend(self):
        if self._vid is None:
            self._vid = registry.build(self.cfg.video_backend, self.cfg, self.hw)
        return self._vid

    def animate(self, shot, preset, timer=None):
        """Keyframe -> frames/ -> carry.png."""
        from PIL import Image
        d = self.shot_dir(shot.id)
        kf_path = d / "keyframe.png"
        if not kf_path.exists():
            raise FileNotFoundError(
                f"shot '{shot.id}' has no keyframe -- run with --stage keyframe first"
            )

        be = self._backend()
        p = self.cfg.preset(shot.preset or preset.name)
        n_frames = be.quantise_frames(shot.duration, p.fps)
        w, h = be.quantise_dims(p.width, p.height)

        cast = self.cast.resolve(shot.characters)
        # Stage B gets a MOTION prompt, not an identity prompt: the identity is
        # already baked into the keyframe, and re-describing the character here
        # competes with the image conditioning instead of reinforcing it.
        motion_prompt = ", ".join(x for x in (shot.prompt, shot.camera) if x)
        _, negative, _, _, _ = characters.compose_conditioning(
            cast, shot, self.cfg.negative_default
        )

        frames = be.generate(
            image=Image.open(kf_path).convert("RGB"),
            prompt=motion_prompt, negative=negative,
            width=w, height=h, num_frames=n_frames,
            steps=p.video_steps, cfg_scale=p.video_cfg,
            seed=shot.resolved_seed(), fps=p.fps,
        )
        assemble.save_frames(frames, d / "frames")
        select_carry_frame(frames, shot).save(d / "carry.png")
        return d / "frames"

    def unload_video(self):
        if self._vid:
            self._vid.unload()
            self._vid = None

    # ---------------------------------------------------------- stage C/D
    def post(self, shot, preset) -> pathlib.Path:
        """Upscale + interpolate + encode one shot to clip.mp4."""
        d = self.shot_dir(shot.id)
        p = self.cfg.preset(shot.preset or preset.name)
        src = d / "frames"
        if not any(src.glob("*.png")):
            raise FileNotFoundError(f"shot '{shot.id}': no frames to post-process")

        if p.upscale:
            up = upscale.build(self.cfg, self.hw)
            src = up.scale_dir(src, d / "frames_up", p.upscale_to_height)
            up.unload()

        fps_in, extra_filter = p.fps, ""
        if p.interpolate and p.target_fps > p.fps:
            interp = interpolate.build(self.cfg, self.hw)
            if interp.mode == "frames":
                src = interp.interpolate_dir(src, d / "frames_final", p.fps, p.target_fps)
                # RIFE emitted the extra frames, so the encode just plays them
                # faster -- applying a filter as well would double-interpolate.
                fps_in = p.target_fps
            elif interp.mode == "encode_filter":
                extra_filter = interp.encode_filter(p.fps, p.target_fps)

        return assemble.encode_frames(
            src, d / "clip.mp4", fps_in,
            fps_out=p.target_fps if p.interpolate else p.fps,
            extra_filter=extra_filter, ffmpeg=self.cfg.ffmpeg,
        )

    def assemble_film(self, shots, shotlist, preset) -> pathlib.Path:
        clips, transitions = [], []
        missing = []
        for s in shots:
            c = self.shot_dir(s.id) / "clip.mp4"
            if not c.exists():
                missing.append(s.id)
                continue
            clips.append(c)
            transitions.append({"type": s.transition, "seconds": s.transition_seconds})
        if missing:
            # Assemble what exists rather than refusing: a rough cut with a
            # hole in it is far more useful than no rough cut.
            log.warning("assembling without %d unrendered shot(s): %s",
                        len(missing), ", ".join(missing))
        p = self.cfg.preset(preset.name)
        height = p.upscale_to_height if p.upscale else p.height
        width = int(round(height * p.width / p.height / 2)) * 2
        return assemble.assemble(
            clips, self.film_dir / f"{self.film}.mp4",
            transitions=transitions, audio=self._audio(shotlist),
            fps=p.target_fps if p.interpolate else p.fps,
            width=width, height=height, ffmpeg=self.cfg.ffmpeg,
        )

    def _audio(self, shotlist):
        a = dict(shotlist.audio or {})
        base = shotlist.source.parent
        if a.get("music"):
            a["music"] = str(base / a["music"]) if not pathlib.Path(a["music"]).is_absolute() else a["music"]
        out = []
        for s in a.get("sfx", []) or []:
            s = dict(s)
            if not pathlib.Path(s["path"]).is_absolute():
                s["path"] = str(base / s["path"])
            out.append(s)
        a["sfx"] = out
        return a

    # --------------------------------------------------------------- run
    def run(self, shotlist, preset, *, only=None, stages=None, resume=False,
            dry_run=False):
        stages = tuple(stages or self.STAGES)
        shots = shotlist.select(only)

        tracker = progress.RunTracker(self.film_dir, len(shots))
        if resume:
            done = tracker.completed_shots()
            before = len(shots)
            shots = [s for s in shots if s.id not in done]
            if before != len(shots):
                log.info("resume: skipping %d already-rendered shot(s)", before - len(shots))
            tracker.total = len(shots)

        if dry_run:
            return self._dry_run(shots, preset)

        log.info("%s", self.hw.describe())
        log.info("film '%s' | %d shot(s) | preset=%s | backend=%s",
                 self.film, len(shots), preset.name, self.cfg.video_backend)

        # --- Stage A, all shots, then drop SDXL entirely
        if "keyframe" in stages and shots:
            log.info("=== Stage A: keyframes ===")
            self.render_keyframes(shots, shotlist, preset)
            self.unload_keyframe()

        # --- Stage B + C, per shot
        if "video" in stages or "post" in stages:
            log.info("=== Stage B/C: animate + finish ===")
            for shot in shots:
                try:
                    with tracker.shot(shot.id) as t:
                        if "video" in stages:
                            t.stage("animate")
                            self.animate(shot, preset)
                        if "post" in stages:
                            t.stage("post")
                            self.post(shot, preset)
                except Exception as exc:
                    # One bad shot must not cost the other thirty-nine.
                    log.error("shot '%s' failed: %s", shot.id, exc, exc_info=log.isEnabledFor(logging.DEBUG))
            self.unload_video()

        if "assemble" in stages:
            log.info("=== Stage D: assembly ===")
            out = self.assemble_film(shotlist.select(only), shotlist, preset)
            log.info("film written: %s", out)

        log.info("\n%s", tracker.summary())
        return tracker

    def _dry_run(self, shots, preset):
        be = registry.build(self.cfg.video_backend, self.cfg, self.hw)
        total_frames = 0
        width = max([len(s.id) for s in shots] + [12]) + 2
        print(f"\n{self.hw.describe()}")
        print(f"film '{self.film}'  preset={preset.name}  backend={be.name}\n")
        rule = "-" * (width + 62)
        print(f"{'shot':<{width}}{'chars':<20}{'frames':>7}{'secs':>7}"
              f"{'size':>12}{'seed':>13}")
        print(rule)

        weak = {}
        for s in shots:
            p = self.cfg.preset(s.preset or preset.name)
            plan = be.plan(s.duration, p.fps, p.width, p.height)
            total_frames += plan["frames"]
            size = f"{plan['width']}x{plan['height']}"
            print(f"{s.id:<{width}}{','.join(s.characters)[:18]:<20}"
                  f"{plan['frames']:>7}{plan['actual_seconds']:>7.2f}"
                  f"{size:>12}{s.resolved_seed():>13}")
            # Collect rather than print per shot: the same character appearing
            # in nine shots is one problem, not nine.
            for c in self.cast.resolve(s.characters):
                if not c.lora_path and not c.ref_images:
                    weak[c.name] = weak.get(c.name, 0) + 1

        # ~1.6 s/frame at 768x512 on the 4060 for LTX at 30 steps, measured on
        # a warm model; the load is amortised across the run.
        est = total_frames * 1.6
        print(rule)
        print(f"{len(shots)} shots, {total_frames} frames, "
              f"~{progress._fmt(est)} of generation (excludes model load, upscale, interp)")
        if weak:
            print("\nconsistency warnings:")
            for name, n in sorted(weak.items()):
                print(f"  ! '{name}' has neither a LoRA nor reference images "
                      f"({n} shot{'s' if n > 1 else ''}) -- identity will rest on "
                      "the prompt alone and will drift")
        return None
