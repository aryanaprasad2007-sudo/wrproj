"""Config schema: the project file, the quality presets, and the shot list.

Two files drive everything:

  config/project.yaml   paths, base checkpoint, backends, presets   (rarely edited)
  <your>/shots.yaml     one entry per shot                          (edited constantly)

The split matters because the shot list is the creative document -- it gets
rewritten dozens of times a day -- while the project file is infrastructure.
Keeping render settings out of the shot list means a preset change re-renders
the whole short without touching a single shot entry.

Validation is strict and happens at load, before any model is touched. A typo
in shot 34 should fail in the first second, not forty minutes into a batch.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import pathlib
import re
from typing import Any

log = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Latent-space models work in multiples of 8; the temporal-compression video
# backends additionally want frame counts of 8k+1. Enforced in `Shot.resolve`.
_PX_MULTIPLE = 8


class ConfigError(ValueError):
    """Raised for any malformed config. Message names the offending key."""


def _load_yaml(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
        data = yaml.safe_load(text)
    except ImportError:
        # JSON is a subset of YAML, so a .json shot list still loads with no
        # PyYAML present. Useful when generating shot lists from a script.
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"{path.name}: PyYAML is not installed and this is not valid JSON ({exc})"
            ) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: top level must be a mapping, got {type(data).__name__}")
    return data


def _require(d: dict, key: str, where: str):
    if key not in d or d[key] in (None, ""):
        raise ConfigError(f"{where}: missing required key '{key}'")
    return d[key]


def _snap(n: int, multiple: int = _PX_MULTIPLE) -> int:
    return max(multiple, int(round(n / multiple)) * multiple)


# --------------------------------------------------------------------------
# Quality presets
# --------------------------------------------------------------------------
@dataclasses.dataclass
class Preset:
    """A render quality level.

    `draft` exists so shot composition can be judged in ~1 minute instead of
    ~8. Critically it keeps the *same seed and same prompt path* as `high`, so
    a draft is a genuine preview of the final rather than a different image --
    only step count, resolution and the post stages change.
    """
    name: str
    width: int = 512
    height: int = 512
    keyframe_steps: int = 22
    keyframe_cfg: float = 6.0
    video_steps: int = 20
    video_cfg: float = 5.0
    fps: int = 12                 # generated fps, before interpolation
    upscale: bool = False
    interpolate: bool = False
    target_fps: int = 24          # after RIFE; ignored when interpolate=False
    upscale_to_height: int = 1080

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "Preset":
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ConfigError(f"preset '{name}': unknown keys {sorted(unknown)}")
        kw = {k: v for k, v in d.items() if k != "name"}
        p = cls(name=name, **kw)
        p.width, p.height = _snap(p.width), _snap(p.height)
        return p


DEFAULT_PRESETS = {
    # Fast enough to iterate on staging and camera. Deliberately 512px and
    # no post stages -- upscale+interp roughly double per-shot wall time and
    # tell you nothing about whether the shot works.
    "draft": Preset("draft", width=512, height=512, keyframe_steps=18,
                    video_steps=14, fps=12, upscale=False, interpolate=False),
    # What actually goes in the film.
    "high": Preset("high", width=768, height=768, keyframe_steps=32,
                   video_steps=30, fps=12, upscale=True, interpolate=True,
                   target_fps=24, upscale_to_height=1080),
}


# --------------------------------------------------------------------------
# Shots
# --------------------------------------------------------------------------
@dataclasses.dataclass
class Shot:
    """One generated clip.

    `carry_from` is the consistency mechanism between shots: it names an
    earlier shot whose final frame seeds this one. See pipeline.resolve_carryover.
    """
    id: str
    prompt: str
    order: int = 0
    negative: str = ""
    characters: list = dataclasses.field(default_factory=list)
    camera: str = ""                      # free text, appended to the prompt
    duration: float = 3.0                 # seconds of finished clip
    seed: int | None = None               # None -> derived from id, stable
    ref_image: str | None = None          # path, relative to the shot list
    control: dict = dataclasses.field(default_factory=dict)  # {pose|depth|canny: path}
    control_scale: float = 0.65
    carry_from: str | None = None
    carry_strength: float = 0.55          # img2img denoise on the carried frame
    transition: str = "cut"               # how this shot enters: cut | crossfade
    transition_seconds: float = 0.5
    preset: str | None = None             # per-shot override of the global preset
    notes: str = ""                       # ignored by the renderer, for you

    @classmethod
    def from_dict(cls, d: dict, order: int, where: str) -> "Shot":
        if not isinstance(d, dict):
            raise ConfigError(f"{where}: each shot must be a mapping")
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ConfigError(f"{where}: unknown shot keys {sorted(unknown)} (known: {sorted(known)})")

        sid = str(_require(d, "id", where))
        if not _ID_RE.match(sid):
            raise ConfigError(
                f"{where}: shot id '{sid}' must be alphanumeric/underscore/dash "
                "(it becomes a folder name)"
            )
        kw = dict(d)
        kw["id"] = sid
        kw["prompt"] = str(_require(d, "prompt", where))
        kw.setdefault("order", order)

        shot = cls(**kw)

        if shot.duration <= 0:
            raise ConfigError(f"{where}: duration must be positive, got {shot.duration}")
        if shot.duration > 12:
            # Not a hard limit, a warning: small video models lose coherence
            # badly past a few seconds, and every backend here is trained on
            # sub-5-second windows.
            log.warning(
                "shot '%s': duration %.1fs is long for a local video model; "
                "expect drift. Consider splitting into two shots.", sid, shot.duration
            )
        if shot.transition not in ("cut", "crossfade"):
            raise ConfigError(
                f"{where}: transition must be 'cut' or 'crossfade', got '{shot.transition}'"
            )
        if not 0.0 <= shot.carry_strength <= 1.0:
            raise ConfigError(f"{where}: carry_strength must be 0..1")
        for kind in shot.control:
            if kind not in ("pose", "depth", "canny"):
                raise ConfigError(
                    f"{where}: control type '{kind}' not supported (pose|depth|canny)"
                )
        return shot

    def resolved_seed(self) -> int:
        """A stable seed even when the shot list does not name one.

        Deriving from the id rather than a counter means inserting a shot at
        position 3 does not re-roll every shot after it -- the single most
        annoying way to lose a take you liked.
        """
        if self.seed is not None:
            return int(self.seed)
        h = hashlib.sha256(self.id.encode("utf-8")).digest()
        return int.from_bytes(h[:4], "big")

    def full_prompt(self, character_fragment: str = "") -> str:
        parts = [p.strip() for p in (character_fragment, self.prompt, self.camera) if p and p.strip()]
        return ", ".join(parts)


@dataclasses.dataclass
class ShotList:
    shots: list
    source: pathlib.Path
    audio: dict = dataclasses.field(default_factory=dict)
    title: str = "untitled"

    @classmethod
    def load(cls, path) -> "ShotList":
        path = pathlib.Path(path)
        if not path.exists():
            raise ConfigError(f"shot list not found: {path}")
        data = _load_yaml(path)
        raw = data.get("shots")
        if not isinstance(raw, list) or not raw:
            raise ConfigError(f"{path.name}: 'shots' must be a non-empty list")

        shots = [Shot.from_dict(s, i, f"{path.name} shot[{i}]") for i, s in enumerate(raw)]

        ids = [s.id for s in shots]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ConfigError(f"{path.name}: duplicate shot ids {sorted(dupes)}")

        # carry_from must name a shot that renders *earlier*, or the pipeline
        # would need a frame that does not exist yet. Catching it here turns a
        # confusing mid-batch failure into a config error.
        index = {s.id: s.order for s in shots}
        for s in shots:
            if s.carry_from is None:
                continue
            if s.carry_from not in index:
                raise ConfigError(
                    f"{path.name}: shot '{s.id}' carries from unknown shot '{s.carry_from}'"
                )
            if index[s.carry_from] >= s.order:
                raise ConfigError(
                    f"{path.name}: shot '{s.id}' carries from '{s.carry_from}', "
                    "which is not earlier in the list"
                )

        return cls(
            shots=sorted(shots, key=lambda s: s.order),
            source=path,
            audio=data.get("audio", {}) or {},
            title=str(data.get("title", path.stem)),
        )

    def select(self, only=None):
        """Filter to a subset of shot ids, preserving order. Empty -> all."""
        if not only:
            return list(self.shots)
        want = set(only)
        missing = want - {s.id for s in self.shots}
        if missing:
            raise ConfigError(f"no such shot(s): {sorted(missing)}")
        return [s for s in self.shots if s.id in want]


# --------------------------------------------------------------------------
# Project
# --------------------------------------------------------------------------
@dataclasses.dataclass
class ProjectConfig:
    root: pathlib.Path
    work_root: pathlib.Path
    models_root: pathlib.Path
    base_checkpoint: str = ""
    base_kind: str = "sdxl"               # sdxl | sd15
    vae: str | None = None
    video_backend: str = "ltx"            # see video/registry.py
    video_model: str = ""
    upscaler: str = "realesrgan"
    upscale_model: str = "RealESRGAN_x4plus_anime_6B"
    interpolator: str = "rife"
    presets: dict = dataclasses.field(default_factory=lambda: dict(DEFAULT_PRESETS))
    default_preset: str = "draft"
    negative_default: str = ""
    ffmpeg: str = "ffmpeg"
    raw: dict = dataclasses.field(default_factory=dict)

    @classmethod
    def load(cls, path) -> "ProjectConfig":
        path = pathlib.Path(path)
        if not path.exists():
            raise ConfigError(
                f"project config not found: {path}\n"
                "Copy config/project.example.yaml to config/project.yaml first."
            )
        d = _load_yaml(path)
        root = path.parent.parent

        paths = d.get("paths", {}) or {}
        models = d.get("models", {}) or {}
        stages = d.get("stages", {}) or {}

        presets = dict(DEFAULT_PRESETS)
        for name, pd in (d.get("presets", {}) or {}).items():
            presets[name] = Preset.from_dict(name, pd or {})

        cfg = cls(
            root=root,
            work_root=pathlib.Path(paths.get("work_root", root / "projects")).expanduser(),
            models_root=pathlib.Path(paths.get("models_root", root / "models")).expanduser(),
            base_checkpoint=str(models.get("base_checkpoint", "")),
            base_kind=str(models.get("base_kind", "sdxl")).lower(),
            vae=models.get("vae"),
            video_backend=str(stages.get("video_backend", "ltx")).lower(),
            video_model=str(stages.get("video_model", "")),
            upscaler=str(stages.get("upscaler", "realesrgan")).lower(),
            upscale_model=str(stages.get("upscale_model", "RealESRGAN_x4plus_anime_6B")),
            interpolator=str(stages.get("interpolator", "rife")).lower(),
            presets=presets,
            default_preset=str(d.get("default_preset", "draft")),
            negative_default=str(d.get("negative_default", "")),
            ffmpeg=str(paths.get("ffmpeg", "ffmpeg")),
            raw=d,
        )
        if cfg.base_kind not in ("sdxl", "sd15"):
            raise ConfigError(f"models.base_kind must be 'sdxl' or 'sd15', got '{cfg.base_kind}'")
        if cfg.default_preset not in cfg.presets:
            raise ConfigError(
                f"default_preset '{cfg.default_preset}' is not defined "
                f"(have: {sorted(cfg.presets)})"
            )
        return cfg

    def preset(self, name: str | None) -> Preset:
        key = name or self.default_preset
        if key not in self.presets:
            raise ConfigError(f"unknown preset '{key}' (have: {sorted(self.presets)})")
        p = self.presets[key]
        return p

    def shot_dir(self, film: str, shot_id: str) -> pathlib.Path:
        return self.work_root / film / "shots" / shot_id
