"""Regression tests that need no GPU, no models, and no downloads.

    py -3.12 tests/test_pipeline.py

Deliberately runs on the plain system interpreter, not the CUDA venv, because
the things most likely to break are config parsing, the ffmpeg filter graph and
the resume bookkeeping -- none of which touch torch. A test suite that needs
the 8 GB venv to be healthy cannot tell you the venv is unhealthy.

Covers, in order of how expensive the bug would be to find in a real run:
  1. shot list validation      -- a typo must fail in second 1, not minute 40
  2. ffmpeg assembly           -- mixed cut/crossfade, the timebase trap
  3. audio mixing              -- music + positioned SFX
  4. character conditioning    -- LoRA stacking, POV negatives, prompt order
  5. resume bookkeeping        -- a shot that fails after succeeding
  6. backend frame quantisation-- 8k+1 and friends

Needs only: pyyaml, pillow, ffmpeg.
"""
from __future__ import annotations

import colorsys
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_FAILS = []
_RUN = [0]


def check(label, cond, extra=""):
    _RUN[0] += 1
    print(f"  {'ok  ' if cond else 'FAIL'}  {label:<36}{extra}")
    if not cond:
        _FAILS.append(label)


def section(name):
    print(f"\n--- {name} " + "-" * max(0, 58 - len(name)))


# ---------------------------------------------------------------- 1. config
def test_validation():
    from animstudio.config import ShotList, ConfigError
    section("shot list validation")

    cases = {
        "duplicate ids": "shots:\n - {id: a, prompt: x}\n - {id: a, prompt: y}\n",
        "carry from later": "shots:\n - {id: a, prompt: x, carry_from: b}\n - {id: b, prompt: y}\n",
        "carry from unknown": "shots:\n - {id: a, prompt: x}\n - {id: b, prompt: y, carry_from: zz}\n",
        "carry from self": "shots:\n - {id: a, prompt: x, carry_from: a}\n",
        "bad transition": "shots:\n - {id: a, prompt: x, transition: wipe}\n",
        "unknown key": "shots:\n - {id: a, prompt: x, protagonist: mira}\n",
        # shot ids become directory names, so path traversal must be rejected
        "path traversal in id": "shots:\n - {id: 'a/../b', prompt: x}\n",
        "missing prompt": "shots:\n - {id: a}\n",
        "negative duration": "shots:\n - {id: a, prompt: x, duration: -2}\n",
        "carry_strength out of range": "shots:\n - {id: a, prompt: x, carry_strength: 1.8}\n",
        "bad control type": "shots:\n - {id: a, prompt: x, control: {normalmap: p.png}}\n",
        "empty shot list": "shots: []\n",
    }
    tmp = pathlib.Path(tempfile.mkdtemp())
    for name, body in cases.items():
        p = tmp / "s.yaml"
        p.write_text(body, encoding="utf-8")
        try:
            ShotList.load(p)
            check(name, False, "loaded without error")
        except ConfigError:
            check(name, True)
        except Exception as exc:
            check(name, False, f"wrong exception {type(exc).__name__}")

    p = tmp / "v.yaml"
    p.write_text("shots:\n - {id: a, prompt: x}\n - {id: b, prompt: y, carry_from: a}\n",
                 encoding="utf-8")
    sl = ShotList.load(p)
    check("valid list loads", len(sl.shots) == 2)

    # Seeds must be stable across runs AND independent of position, so that
    # inserting a shot does not re-roll every shot after it.
    s = sl.shots[0]
    check("seed is stable for an id", s.resolved_seed() == sl.shots[0].resolved_seed())
    check("seed differs between ids", sl.shots[0].resolved_seed() != sl.shots[1].resolved_seed())


# ------------------------------------------------------------- 2/3. ffmpeg
def _fake_clips(work, n=3, frames=12, fps=12):
    from PIL import Image, ImageDraw
    from animstudio import assemble
    clips = []
    for i in range(n):
        fd = work / f"s{i}" / "frames"
        fd.mkdir(parents=True, exist_ok=True)
        r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(i / n, 0.6, 0.9)]
        for f in range(frames):
            im = Image.new("RGB", (512, 288), (r, g, b))
            ImageDraw.Draw(im).rectangle([f * 30, 100, f * 30 + 60, 180], fill=(255, 255, 255))
            im.save(fd / f"{f:08d}.png")
        clips.append(assemble.encode_frames(fd, work / f"s{i}" / "clip.mp4", fps))
    return clips


def test_assembly(work):
    from animstudio import assemble
    section("ffmpeg assembly")

    clips = _fake_clips(work / "asm")
    durs = [assemble.probe_duration(c) for c in clips]
    check("clips encode to 1.0s", all(abs(d - 1.0) < 0.05 for d in durs),
          f"{[round(d,3) for d in durs]}")

    # The interesting case: a crossfade FOLLOWING a cut. concat emits timebase
    # 1/1000000, a freshly scaled input carries 1/fps, and xfade hard-fails on
    # the mismatch -- invisible to any test that uses one transition type.
    out = assemble.assemble(
        clips, work / "asm" / "film.mp4",
        transitions=[{"type": "cut"}, {"type": "cut"},
                     {"type": "crossfade", "seconds": 0.4}],
        fps=24, width=960, height=540,
    )
    dur = assemble.probe_duration(out)
    check("cut + crossfade mix", abs(dur - 2.6) < 0.15, f"{dur:.3f}s (expected 2.60)")

    # An over-long crossfade must be clamped, not produce a frozen frame.
    out2 = assemble.assemble(
        clips[:2], work / "asm" / "clamp.mp4",
        transitions=[{"type": "cut"}, {"type": "crossfade", "seconds": 30.0}],
        fps=24, width=960, height=540,
    )
    d2 = assemble.probe_duration(out2)
    check("over-long crossfade clamped", 1.0 < d2 < 2.1, f"{d2:.3f}s")


def test_audio(work):
    from animstudio import assemble
    section("audio mixing")

    for name, args in (("music.mp3", "sine=frequency=220:duration=6"),
                       ("ding.wav", "sine=frequency=880:duration=0.4")):
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", args, str(work / name)],
                       capture_output=True)

    clips = sorted((work / "asm").glob("s*/clip.mp4"))
    out = assemble.assemble(
        clips, work / "asm" / "film_audio.mp4",
        transitions=[{"type": "cut"}, {"type": "crossfade", "seconds": 0.3}, {"type": "cut"}],
        audio={"music": str(work / "music.mp3"), "music_gain": 0.5, "music_fade": 0.5,
               "sfx": [{"path": str(work / "ding.wav"), "at": 0.5, "gain": 0.9},
                       {"path": str(work / "ding.wav"), "at": 2.0, "gain": 0.6}]},
        fps=24, width=960, height=540,
    )
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
        capture_output=True, text=True).stdout)
    kinds = {s["codec_type"] for s in info["streams"]}
    check("music + sfx produce an audio stream", "audio" in kinds, str(sorted(kinds)))
    check("video survives the audio graph", "video" in kinds)


# ------------------------------------------------------------ 4. characters
def test_characters():
    from animstudio.characters import CastRegistry, compose_conditioning
    from animstudio.config import ShotList
    section("character conditioning")

    cast = CastRegistry.load(ROOT / "characters")
    sl = ShotList.load(ROOT / "shots" / "example.yaml")
    by = {s.id: s for s in sl.shots}

    pov = cast.get("pov")
    check("pov injects a face negative", "face" in pov.negative_fragment())
    check("pov uses a lower ip weight", pov.ipadapter_weight < 0.5, f"{pov.ipadapter_weight}")

    mira = cast.get("mira")
    check("trigger leads the fragment", mira.prompt_fragment().startswith("mirafx"))

    p, n, _, _, _ = compose_conditioning([mira], by["s03_mira_enters"], "lowres")
    check("character precedes shot prompt", p.startswith("mirafx"))
    check("camera note appended", "medium shot" in p)
    check("project negative merged", "lowres" in n)

    # Two character LoRAs at full strength blend into a third character.
    mira.lora_path, mira.lora_weight = "a.safetensors", 0.85
    kettle = cast.get("kettle")
    kettle.lora_path, kettle.lora_weight = "b.safetensors", 0.85
    _, _, loras, _, _ = compose_conditioning([mira, kettle], by["s06_both_react"], "")
    check("stacked LoRAs are scaled down", len(loras) == 2 and all(w < 0.85 for _, w in loras),
          f"{[round(w,3) for _, w in loras]}")

    try:
        cast.get("nobody")
        check("unknown character raises", False)
    except Exception:
        check("unknown character raises", True)


# ---------------------------------------------------------------- 5. resume
def test_resume(work):
    from animstudio import progress
    section("resume bookkeeping")

    t = progress.RunTracker(work / "run", 3)
    t.record("s1", 10, {}, ok=True)
    t.record("s2", 10, {}, ok=False, error="boom")
    t.record("s3", 10, {}, ok=True)
    check("completed set excludes failures", t.completed_shots() == {"s1", "s3"})
    # Re-rendering s1 and having it fail must drop it from the completed set,
    # or a --resume would skip exactly the shot that needs redoing.
    t.record("s1", 10, {}, ok=False, error="regression")
    check("a later failure clears done", "s1" not in t.completed_shots())


# --------------------------------------------------------------- 6. backend
def test_backends():
    from animstudio import config, hardware
    from animstudio.video import registry
    section("backend quantisation")

    cfg = config.ProjectConfig.load(ROOT / "config" / "project.example.yaml")
    hw = hardware.detect()

    for name, rule in (("ltx", lambda n: n % 8 == 1),
                       ("wan", lambda n: n % 4 == 1),
                       ("svd", lambda n: 14 <= n <= 25),
                       ("animatediff", lambda n: 8 <= n <= 32)):
        be = registry.build(name, cfg, hw)
        counts = [be.quantise_frames(d, 12) for d in (1.0, 2.5, 3.0, 4.0, 8.0)]
        check(f"{name}: legal frame counts", all(rule(n) for n in counts), str(counts))
        w, h = be.quantise_dims(770, 515)
        check(f"{name}: dims snap to {be.dim_multiple}",
              w % be.dim_multiple == 0 and h % be.dim_multiple == 0, f"{w}x{h}")


def main():
    print("=" * 66)
    print(" animation-studio tests (no GPU, no models)")
    print("=" * 66)
    work = pathlib.Path(tempfile.mkdtemp(prefix="animstudio-test-"))
    test_validation()
    test_characters()
    test_backends()
    test_resume(work)
    test_assembly(work)
    test_audio(work)

    print("\n" + "=" * 66)
    if _FAILS:
        print(f" {len(_FAILS)} of {_RUN[0]} FAILED:")
        for f in _FAILS:
            print(f"   - {f}")
    else:
        print(f" all {_RUN[0]} checks passed")
    print("=" * 66)
    return 1 if _FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
