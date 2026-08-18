"""Stage D: frames -> clips -> the finished film.

Two jobs that are usually conflated and shouldn't be:

  encode_frames()  one shot's PNG sequence -> one mp4. Happens per shot, and
                   is where interpolation lands when the interpolator is the
                   ffmpeg filter kind.
  assemble()       many mp4s -> one film, with transitions and audio.

Everything downstream of generation is deterministic, so assembly is cheap to
re-run. That is the point: recut the film, change the music, adjust a
crossfade, all without touching the GPU.

The one genuinely fiddly part is mixing cuts and crossfades in a single
filter graph. `xfade` consumes time (a 0.5 s crossfade makes the film 0.5 s
shorter) while `concat` does not, so the running timeline offset has to be
tracked as the graph is built. Getting that wrong silently desynchronises the
music from the picture -- which looks like a music problem.
"""
from __future__ import annotations

import json
import logging
import pathlib
import subprocess

log = logging.getLogger(__name__)


class FfmpegError(RuntimeError):
    pass


def _run(cmd, what="ffmpeg"):
    log.debug("%s: %s", what, " ".join(str(c) for c in cmd))
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()[-12:]
        raise FfmpegError(f"{what} failed:\n" + "\n".join(tail))
    return p.stdout


def probe_duration(path, ffmpeg="ffmpeg") -> float:
    ffprobe = "ffprobe" if ffmpeg == "ffmpeg" else str(pathlib.Path(ffmpeg).with_name("ffprobe"))
    out = _run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(path)], "ffprobe")
    try:
        return float(json.loads(out)["format"]["duration"])
    except Exception as exc:
        raise FfmpegError(f"could not read duration of {path}: {exc}") from exc


def encode_frames(frames_dir, out_path, fps_in: int, *, fps_out=None,
                  extra_filter: str = "", ffmpeg="ffmpeg", crf=16) -> pathlib.Path:
    """Encode a PNG sequence to mp4.

    crf 16 rather than the usual 23 because this is an intermediate: the file
    gets re-encoded once more at assembly, and generation artefacts plus two
    lossy passes compound visibly on flat animation.
    """
    frames_dir, out_path = pathlib.Path(frames_dir), pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        raise FfmpegError(f"no PNG frames in {frames_dir}")

    filters = [f for f in (extra_filter,) if f]
    # yuv420p needs even dimensions; generated sizes are usually fine but an
    # upscale to an odd height would otherwise fail deep inside libx264.
    filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    cmd = [ffmpeg, "-y", "-framerate", fps_in,
           "-i", str(frames_dir / "%08d.png"),
           "-vf", ",".join(filters),
           "-c:v", "libx264", "-preset", "slow", "-crf", crf,
           "-pix_fmt", "yuv420p"]
    if fps_out:
        cmd += ["-r", fps_out]
    cmd.append(str(out_path))
    _run(cmd, "encode")
    log.info("encoded %s (%d frames @ %d fps)", out_path.name, len(frames), fps_in)
    return out_path


def save_frames(frames, frames_dir) -> pathlib.Path:
    """Write PIL frames as %08d.png -- the naming every later stage assumes."""
    frames_dir = pathlib.Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.png"):
        old.unlink()
    for i, im in enumerate(frames):
        im.save(frames_dir / f"{i:08d}.png")
    return frames_dir


def _audio_graph(audio: dict, video_label: str, total: float):
    """Build the audio half of the filter graph.

    Returns (inputs, filter_chunks, out_label). Music is ducked under SFX by
    simple gain rather than a sidechain compressor: a sidechain sounds better
    but needs tuning per track, and an untuned one pumps.
    """
    inputs, chunks, mix_labels = [], [], []
    idx_base = 0  # filled by caller offset

    music = audio.get("music")
    if music:
        inputs.append(str(music))
        gain = float(audio.get("music_gain", 0.6))
        fade = float(audio.get("music_fade", 2.0))
        chunks.append(
            f"[AIN0]volume={gain},afade=t=in:st=0:d={fade},"
            f"afade=t=out:st={max(0.0, total - fade):.3f}:d={fade}[amus]"
        )
        mix_labels.append("[amus]")

    for i, sfx in enumerate(audio.get("sfx", []) or []):
        inputs.append(str(sfx["path"]))
        at_ms = int(float(sfx.get("at", 0)) * 1000)
        g = float(sfx.get("gain", 1.0))
        chunks.append(f"[AIN{len(inputs)-1}]volume={g},adelay={at_ms}|{at_ms}[asfx{i}]")
        mix_labels.append(f"[asfx{i}]")

    if not mix_labels:
        return [], [], None
    if len(mix_labels) == 1:
        return inputs, chunks, mix_labels[0].strip("[]")

    # dropout_transition=0 stops amix from ramping the music back up every
    # time a short SFX ends, which is audible as breathing.
    chunks.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=0[amix]"
    )
    return inputs, chunks, "amix"


def assemble(clips, out_path, *, transitions=None, audio=None, fps=24,
             width=None, height=None, ffmpeg="ffmpeg", crf=18) -> pathlib.Path:
    """Concatenate clips into the final film.

    `transitions[i]` describes how clip i ENTERS, so transitions[0] is ignored
    (nothing to fade from). Each is {"type": "cut"|"crossfade", "seconds": f}.
    """
    clips = [pathlib.Path(c) for c in clips]
    if not clips:
        raise FfmpegError("nothing to assemble: no clips")
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    transitions = transitions or [{"type": "cut"}] * len(clips)
    audio = audio or {}

    durations = [probe_duration(c, ffmpeg) for c in clips]

    # Normalise every clip before joining. xfade and concat both require
    # identical width/height/fps/pixel format/SAR, and generated clips vary
    # (different backends, different presets, upscaled vs not). Skipping this
    # produces the classic "concat only played the first clip" bug.
    if width is None or height is None:
        width, height = 1920, 1080
    # settb=AVTB is not cosmetic. The concat filter emits timebase 1/1000000
    # while a freshly-scaled input carries 1/fps, and xfade hard-fails when its
    # two inputs disagree ("First input link main timebase ... do not match").
    # In a mixed cut/crossfade film that error appears only when a crossfade
    # follows a cut, so it survives any test that uses one transition type.
    scale = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
             f"format=yuv420p,settb=AVTB")

    parts = [f"[{i}:v]{scale}[v{i}]" for i in range(len(clips))]

    acc, acc_dur = "v0", durations[0]
    for i in range(1, len(clips)):
        t = transitions[i] if i < len(transitions) else {"type": "cut"}
        nxt = f"m{i}"
        if str(t.get("type", "cut")) == "crossfade":
            # Cap the crossfade: it cannot exceed either neighbouring clip, and
            # an over-long xfade offset silently outputs a frozen frame.
            d = min(float(t.get("seconds", 0.5)), durations[i] * 0.5, acc_dur * 0.5)
            if d <= 0.02:
                parts.append(f"[{acc}][v{i}]concat=n=2:v=1:a=0[{nxt}]")
                acc_dur += durations[i]
            else:
                offset = max(0.0, acc_dur - d)
                parts.append(
                    f"[{acc}][v{i}]xfade=transition=fade:duration={d:.3f}"
                    f":offset={offset:.3f}[{nxt}]"
                )
                acc_dur += durations[i] - d
        else:
            parts.append(f"[{acc}][v{i}]concat=n=2:v=1:a=0[{nxt}]")
            acc_dur += durations[i]
        acc = nxt

    cmd = [ffmpeg, "-y"]
    for c in clips:
        cmd += ["-i", str(c)]

    a_inputs, a_chunks, a_out = _audio_graph(audio, acc, acc_dur)
    for a in a_inputs:
        cmd += ["-i", a]
    # Audio inputs land after the video inputs, so their stream indices are
    # offset by the clip count. The placeholders keep _audio_graph independent
    # of that arithmetic.
    for j in range(len(a_inputs)):
        a_chunks = [c.replace(f"[AIN{j}]", f"[{len(clips)+j}:a]") for c in a_chunks]

    graph = ";".join(parts + a_chunks)
    cmd += ["-filter_complex", graph, "-map", f"[{acc}]"]
    if a_out:
        cmd += ["-map", f"[{a_out}]", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", crf,
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]

    log.info("assembling %d clips -> %s (%.1fs, %dx%d @ %dfps)",
             len(clips), out_path.name, acc_dur, width, height, fps)
    _run(cmd, "assemble")
    return out_path
