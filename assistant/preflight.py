"""Is this machine actually ready to run her?

Most of what can go wrong here goes wrong outside Python: a missing PortAudio,
a voice model that was never downloaded, an API key with a typo. Those surface
as stack traces from deep inside a library, three layers from the cause. This
checks each one directly and says what to type to fix it.

Nothing here mutates anything — `run_setup.py` does the fixing, this does the
looking, and both print the same report.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Iterator

from .persona import DEFAULT_PERSONA, load

ROOT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 10)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    #  A failed optional check costs you a feature, not the program.
    needed_for: str = ""

    @property
    def required(self) -> bool:
        return not self.needed_for


def _package(name: str, *, needed_for: str = "", pip: str | None = None) -> Check:
    found = find_spec(name) is not None
    return Check(
        name=f"{name} installed",
        ok=found,
        detail="" if found else "not importable",
        fix=f"pip install {pip or name}",
        needed_for=needed_for,
    )


def _python() -> Check:
    ok = sys.version_info >= MIN_PYTHON
    return Check(
        name="python version",
        ok=ok,
        detail=".".join(str(n) for n in sys.version_info[:3]),
        fix=f"needs {'.'.join(str(n) for n in MIN_PYTHON)} or newer",
    )


def _env(name: str, hint: str, *, needed_for: str = "", minimum: int = 1) -> Check:
    value = os.environ.get(name, "").strip()
    # `.env.example` ships placeholders ending in `...`, and copying the file
    # loads them into the environment looking for all the world like real
    # values. They have to count as unset or this check waves through a clone
    # that cannot make a single request.
    placeholder = value.endswith("...")
    ok = not placeholder and len(value) >= minimum
    if placeholder:
        detail = "still the placeholder from .env.example"
    elif not value:
        detail = "missing"
    elif len(value) < minimum:
        detail = f"only {len(value)} characters — truncated?"
    else:
        detail = "set"
    return Check(name=name, ok=ok, detail=detail, fix=hint, needed_for=needed_for)


def _persona(path: Path) -> Check:
    try:
        persona = load(path)
    except Exception as exc:
        return Check("persona loads", False, str(exc), f"check the YAML in {path}")
    return Check(
        "persona loads", True, f"{persona.name}, {len(persona.few_shot) // 2} examples"
    )


def _knows_you(path: Path) -> Check:
    """Not a fault, a nudge: the `user:` block is the cheapest quality win here
    and it's the one thing a fresh clone can't fill in for you."""
    named = False
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        named = bool((raw.get("user") or {}).get("name"))
    except Exception:
        pass
    return Check(
        "she knows who you are",
        named,
        "yes" if named else "the `user:` block in the persona is still empty",
        f"fill in `user: name:` in {path}",
        needed_for="her talking to you rather than at a stranger",
    )


def _voice(path: Path) -> Iterator[Check]:
    """Whether she can actually speak, and with what."""
    try:
        config = load(path).voice or {}
    except Exception:
        return
    engine = (config.get("engine") or "tone").strip().lower()

    if engine == "tone":
        # Not an error — it's the deliberate default, and the pipeline runs on
        # it. But nobody testing this wants bleeps, so it reads as a warning.
        yield Check(
            "voice engine",
            False,
            "tone — placeholder bleeps, not speech",
            "python run_setup.py  (downloads a real voice)",
            needed_for="hearing actual words rather than tones",
        )
        return

    if engine == "piper":
        yield _package("piper", needed_for="speech", pip="piper-tts")
        name = config.get("model") or "en_US-lessac-medium"
        directory = ROOT / (config.get("model_dir") or "voices")
        model = directory / f"{name}.onnx"
        yield Check(
            "voice model",
            model.exists(),
            f"{name}" + ("" if model.exists() else f" missing from {directory}/"),
            f"python -m piper.download_voices {name} --download-dir {directory}",
        )
        return

    yield Check("voice engine", True, engine)


def _whisper_cached() -> Check:
    """Whisper downloads ~150MB on first use, which is a long silent pause the
    first time you speak. Worth knowing before you're stood there waiting."""
    hub = Path(
        os.environ.get("HF_HOME")
        or os.environ.get("HUGGINGFACE_HUB_CACHE")
        or Path.home() / ".cache" / "huggingface"
    )
    for candidate in (hub, hub / "hub"):
        if candidate.is_dir() and any(candidate.glob("models--*faster-whisper*")):
            return Check("whisper model", True, "cached")
    return Check(
        "whisper model",
        False,
        "not downloaded yet — first utterance will stall while it fetches",
        "python run_setup.py --whisper",
        needed_for="talking out loud",
    )


def _speakers() -> Check:
    from .voice_client import SoundDevicePlayer

    ok = SoundDevicePlayer.available()
    return Check(
        "audio output",
        ok,
        "found" if ok else "none — audio will be written to audio/*.wav instead",
        "install PortAudio (macOS: brew install portaudio, "
        "Debian/Ubuntu: apt install libportaudio2)",
        needed_for="hearing her at all",
    )


def _microphone() -> Check:
    try:
        from .audio import Microphone

        ok = Microphone.available()
    except Exception:
        ok = False
    return Check(
        "microphone",
        ok,
        "found" if ok else "none",
        "same PortAudio install as above",
        needed_for="talking to her out loud",
    )


def checks(persona_path: Path | str | None = None) -> list[Check]:
    path = Path(persona_path or os.environ.get("PERSONA_PATH") or DEFAULT_PERSONA)
    found: list[Check] = [
        _python(),
        _package("anthropic"),
        _package("yaml", pip="PyYAML"),
        _package("fastapi"),
        _package("uvicorn"),
        _package("httpx"),
        _package("websockets", needed_for="the avatar page"),
        _env(
            "ANTHROPIC_API_KEY",
            "python run_setup.py, or paste it into .env by hand",
            minimum=20,
        ),
        _env(
            "ASSISTANT_TOKEN",
            "python run_setup.py  (generates one)",
            minimum=16,
        ),
        _persona(path),
        _knows_you(path),
    ]
    found += list(_voice(path))
    found += [
        _package("sounddevice", needed_for="speakers and microphone"),
        _speakers(),
        _package("webrtcvad", needed_for="knowing when you've stopped talking"),
        _package("faster_whisper", needed_for="talking out loud", pip="faster-whisper"),
        _whisper_cached(),
        _microphone(),
    ]
    return found


# ------------------------------------------------------------------ reporting

_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def report(found: list[Check]) -> int:
    """Print the report. Returns the number of *required* checks that failed."""
    blocking = [c for c in found if not c.ok and c.required]
    degraded = [c for c in found if not c.ok and not c.required]

    for check in found:
        if check.ok:
            mark, name = _c("32", "  ok  "), check.name
        elif check.required:
            mark, name = _c("31", " fail "), _c("1", check.name)
        else:
            mark, name = _c("33", " warn "), check.name
        line = f"{mark} {name}"
        if check.detail:
            line += _c("2", f"  ·  {check.detail}")
        print(line)

    print()
    if blocking:
        count = "one thing" if len(blocking) == 1 else f"{len(blocking)} things"
        print(_c("31", f"  {count} to fix before she'll run:"))
        for check in blocking:
            print(f"    {check.name}: {_c('36', check.fix)}")
        print()
    if degraded:
        print(_c("33", "  works without these, but you'll be missing:"))
        for check in degraded:
            print(f"    {check.needed_for} — {_c('36', check.fix)}")
        print()
    return len(blocking)
