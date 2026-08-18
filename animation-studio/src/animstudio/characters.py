"""Character identity: the thing that has to survive across separate renders.

A character is three cooperating mechanisms, and they fail in different ways,
which is why all three exist rather than just the strongest one:

  1. a TRIGGER TOKEN + description  -- costs nothing, survives every backend,
                                       but drifts (the model re-interprets
                                       "silver-haired" each render)
  2. a LoRA                         -- strongest identity lock; needs training
                                       on your turnarounds, ~20 min one-off
  3. IP-Adapter reference images    -- no training, locks face/palette at
                                       generation time; weaker on pose, and
                                       it fights ControlNet if over-weighted

The failure mode this design guards against is subtle: a LoRA trained on six
turnaround images will happily reproduce the *turnaround pose* in every shot.
So `prompt_fragment` deliberately keeps the trigger token terse and leaves
staging entirely to the shot prompt, and the recommended IP-Adapter weight is
below the point where it starts importing composition along with identity.

A "POV character" (hands and arms only, never a face) is a first-class kind
here, because its consistency problem is different: no face to lock, so the
useful signal is skin tone, sleeve, and any worn props. It gets a different
default weight and a different negative.
"""
from __future__ import annotations

import dataclasses
import logging
import pathlib

from .config import ConfigError, _load_yaml

log = logging.getLogger(__name__)

_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# Above ~0.75 IP-Adapter stops contributing identity and starts contributing
# composition -- you get the reference image's framing back regardless of what
# the shot prompt asked for. 0.55-0.65 is the usable band for a face lock.
_IPA_SAFE_MAX = 0.75


@dataclasses.dataclass
class Character:
    """One cast member, loaded from characters/<name>/character.yaml."""
    name: str
    root: pathlib.Path
    trigger: str = ""                     # e.g. "sksmira" or "mira_the_fox"
    description: str = ""                 # stable visual traits, always injected
    negative: str = ""                    # traits to actively suppress
    kind: str = "full"                    # full | pov  (pov = hands/arms only)
    lora_path: str | None = None
    lora_weight: float = 0.85
    ipadapter_weight: float = 0.6
    ref_images: list = dataclasses.field(default_factory=list)
    palette: list = dataclasses.field(default_factory=list)   # documentation only

    # ---------------------------------------------------------------- load
    @classmethod
    def load(cls, directory) -> "Character":
        directory = pathlib.Path(directory)
        cfg_path = directory / "character.yaml"
        if not cfg_path.exists():
            raise ConfigError(f"no character.yaml in {directory}")
        d = _load_yaml(cfg_path)

        known = {f.name for f in dataclasses.fields(cls)} - {"root", "ref_images"}
        unknown = set(d) - known - {"ref_images"}
        if unknown:
            raise ConfigError(f"{cfg_path}: unknown keys {sorted(unknown)}")

        name = str(d.get("name") or directory.name)
        kind = str(d.get("kind", "full")).lower()
        if kind not in ("full", "pov"):
            raise ConfigError(f"{cfg_path}: kind must be 'full' or 'pov', got '{kind}'")

        # Reference images: explicit list wins, otherwise scan refs/.
        refs = []
        if d.get("ref_images"):
            for r in d["ref_images"]:
                p = (directory / r) if not pathlib.Path(r).is_absolute() else pathlib.Path(r)
                if not p.exists():
                    raise ConfigError(f"{cfg_path}: ref_image not found: {p}")
                refs.append(p)
        else:
            refdir = directory / "refs"
            if refdir.is_dir():
                refs = sorted(p for p in refdir.iterdir() if p.suffix.lower() in _IMG_EXT)

        lora = d.get("lora_path")
        if lora:
            lp = (directory / lora) if not pathlib.Path(lora).is_absolute() else pathlib.Path(lora)
            lora = str(lp)
            if not lp.exists():
                # Warn rather than raise: you often write the character file
                # before training, and text-only mode is a valid way to work.
                log.warning("character '%s': lora_path does not exist yet: %s", name, lp)
                lora = None

        c = cls(
            name=name,
            root=directory,
            trigger=str(d.get("trigger", "")),
            description=str(d.get("description", "")),
            negative=str(d.get("negative", "")),
            kind=kind,
            lora_path=lora,
            lora_weight=float(d.get("lora_weight", 0.85)),
            ipadapter_weight=float(d.get("ipadapter_weight", 0.45 if kind == "pov" else 0.6)),
            ref_images=refs,
            palette=list(d.get("palette", []) or []),
        )

        if c.ipadapter_weight > _IPA_SAFE_MAX:
            log.warning(
                "character '%s': ipadapter_weight %.2f is above %.2f -- at this "
                "strength IP-Adapter starts copying the reference image's "
                "composition, not just its identity.",
                c.name, c.ipadapter_weight, _IPA_SAFE_MAX,
            )
        if not c.trigger and not c.lora_path and not c.ref_images:
            raise ConfigError(
                f"{cfg_path}: character '{name}' has no trigger, no LoRA and no "
                "reference images -- nothing would make it consistent."
            )
        return c

    # ------------------------------------------------------------- prompts
    def prompt_fragment(self) -> str:
        """Text injected ahead of the shot prompt.

        Order is deliberate: trigger token first (LoRA-bound tokens bind
        hardest at the start of the prompt, where CLIP weighting is highest),
        then the stable description. No staging or camera words -- those come
        from the shot, and duplicating them here is how a character starts
        dragging its turnaround pose into every scene.
        """
        parts = [p for p in (self.trigger, self.description) if p]
        return ", ".join(parts)

    def negative_fragment(self) -> str:
        if self.kind == "pov" and not self.negative:
            # A POV character is defined by what must NOT appear: the moment a
            # face or full body shows up, the shot has stopped being POV.
            return "face, head, portrait, full body, mirror reflection, selfie"
        return self.negative


class CastRegistry:
    """All characters available to a shot list, keyed by name.

    Loaded once per run. A shot naming an unknown character fails immediately
    rather than silently rendering a generic person.
    """

    def __init__(self, characters: dict):
        self._by_name = characters

    @classmethod
    def load(cls, characters_root) -> "CastRegistry":
        root = pathlib.Path(characters_root)
        found = {}
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if d.is_dir() and (d / "character.yaml").exists():
                    c = Character.load(d)
                    found[c.name.lower()] = c
        log.info("cast: %d character(s) loaded (%s)",
                 len(found), ", ".join(sorted(found)) or "none")
        return cls(found)

    def get(self, name: str) -> Character:
        c = self._by_name.get(str(name).lower())
        if c is None:
            raise ConfigError(
                f"unknown character '{name}' (have: {sorted(self._by_name) or 'none'})"
            )
        return c

    def resolve(self, names):
        return [self.get(n) for n in (names or [])]

    def __len__(self):
        return len(self._by_name)

    def __iter__(self):
        return iter(self._by_name.values())


def compose_conditioning(characters, shot, project_negative: str = ""):
    """Merge cast + shot into the exact strings and weights the sampler needs.

    Returns (prompt, negative, loras, ip_images, ip_weight).

    Two-character shots are where consistency breaks worst: the model blends
    them into one averaged design. Mitigations applied here, in order of how
    much they help:
      - each character's fragment stays contiguous (never interleaved)
      - LoRA weights are scaled down when stacked, because two character LoRAs
        at 0.85 each will fight and produce a hybrid
      - IP-Adapter takes the mean of both weights, and both image sets are
        passed so the adapter sees both identities
    """
    frags, negs, loras, ip_images, ip_weights = [], [], [], [], []

    for c in characters:
        if f := c.prompt_fragment():
            frags.append(f)
        if n := c.negative_fragment():
            negs.append(n)
        if c.lora_path:
            loras.append((c.lora_path, c.lora_weight))
        if c.ref_images:
            ip_images.extend(c.ref_images)
            ip_weights.append(c.ipadapter_weight)

    # Stacked character LoRAs interfere. Scaling by 1/sqrt(n) keeps total
    # applied strength roughly constant instead of doubling it, which is what
    # produces the "both characters look like a third character" failure.
    if len(loras) > 1:
        scale = len(loras) ** -0.5
        loras = [(p, w * scale) for p, w in loras]
        log.debug("scaled %d stacked character LoRAs by %.2f", len(loras), scale)

    prompt = shot.full_prompt(", ".join(frags))
    negative = ", ".join([x for x in ([shot.negative, project_negative] + negs) if x])
    ip_weight = sum(ip_weights) / len(ip_weights) if ip_weights else 0.0

    return prompt, negative, loras, ip_images, ip_weight
