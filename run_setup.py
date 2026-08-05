#!/usr/bin/env python3
"""Get a fresh clone to the point where you can talk to her.

    python run_setup.py

Safe to re-run: every step checks before it acts, so this doubles as the
"something's broken, what is it" command. It only ever touches `.env`, the
`voices/` directory, and the one `engine:` line in the persona file — and it
tells you before each.

    --voice NAME     which Piper voice to fetch (default en_US-lessac-medium)
    --no-voice       skip the download; she'll bleep instead of speaking
    --whisper        pre-fetch the speech recogniser too (~150MB), so your
                     first sentence isn't answered by a long silence
    --check          report only, change nothing
"""

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # checked properly below
    load_dotenv = None

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
PERSONA = ROOT / "persona" / "rei.yaml"
DEFAULT_VOICE = "en_US-lessac-medium"

_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def step(text: str) -> None:
    print(_c("1", f"\n  {text}"))


def did(text: str) -> None:
    print(f"    {_c('32', '+')} {text}")


def skip(text: str) -> None:
    print(f"    {_c('2', '·')} {_c('2', text)}")


def warn(text: str) -> None:
    print(f"    {_c('33', '!')} {text}")


# --------------------------------------------------------------------- .env


def ensure_env() -> None:
    step(".env")
    if not ENV.exists():
        ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        did(f"created {ENV.name} from {EXAMPLE.name}")
    else:
        skip(f"{ENV.name} already exists — leaving it alone")

    lines = ENV.read_text(encoding="utf-8").splitlines()
    changed = False

    if not _value(lines, "ASSISTANT_TOKEN"):
        lines = _set(lines, "ASSISTANT_TOKEN", secrets.token_urlsafe(32))
        changed = True
        did("generated ASSISTANT_TOKEN")
    else:
        skip("ASSISTANT_TOKEN already set")

    if not _value(lines, "ANTHROPIC_API_KEY", placeholder="sk-ant-..."):
        key = _ask_for_key()
        if key:
            lines = _set(lines, "ANTHROPIC_API_KEY", key)
            changed = True
            did("saved ANTHROPIC_API_KEY")
        else:
            warn(f"ANTHROPIC_API_KEY still unset — add it to {ENV.name} before running")
    else:
        skip("ANTHROPIC_API_KEY already set")

    if changed:
        ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if load_dotenv:
            load_dotenv(ENV, override=True)


def _value(lines: list[str], key: str, placeholder: str | None = None) -> str:
    for line in lines:
        if line.startswith(f"{key}="):
            value = line.split("=", 1)[1].strip()
            return "" if value == placeholder else value
    return ""


def _set(lines: list[str], key: str, value: str) -> list[str]:
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            return lines
    return lines + [f"{key}={value}"]


def _ask_for_key() -> str:
    if not sys.stdin.isatty():
        return ""
    print(
        _c("2", "    Paste your Anthropic API key (console.anthropic.com), ")
        + _c("2", "or press enter to skip:")
    )
    try:
        return input("    key> ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


# -------------------------------------------------------------------- voice


def ensure_voice(name: str) -> None:
    step("voice")
    directory = ROOT / "voices"
    model = directory / f"{name}.onnx"
    if model.exists():
        skip(f"{name} already downloaded")
    else:
        if not _installed("piper"):
            warn("piper-tts is not installed — pip install -r requirements.txt")
            return
        print(f"    downloading {name} (~60MB, once)…")
        directory.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, "-m", "piper.download_voices", name,
             "--download-dir", str(directory)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not model.exists():
            warn(f"download failed: {_why(result.stderr or result.stdout)}")
            warn("she'll bleep instead of speaking until this works — "
                 "everything else runs fine meanwhile")
            return
        did(f"downloaded {name}")

    _use_piper()


def _why(output: str) -> str:
    """The one useful line out of a subprocess traceback.

    Python puts the actual cause on the last line and forty lines of stack
    above it; printing the tail shows the stack and hides the cause.
    """
    lines = [line.strip() for line in (output or "").strip().splitlines() if line.strip()]
    if not lines:
        return "no output"
    last = lines[-1]
    if "urlopen error" in last or "URLError" in last or "SSL" in last:
        return f"{last}  (network, proxy or firewall)"
    return last


def _use_piper() -> None:
    """Point the persona's `voice:` block at Piper.

    Edited by line rather than rewritten through a YAML dump: that file is more
    comment than config, and round-tripping it would throw all of that away.
    """
    lines = PERSONA.read_text(encoding="utf-8").splitlines()
    inside = False
    for i, line in enumerate(lines):
        if line.startswith("voice:"):
            inside = True
            continue
        if inside:
            if line and not line.startswith((" ", "\t")):
                break
            if line.strip().startswith("engine:"):
                if "piper" in line:
                    skip("persona already uses piper")
                    return
                lines[i] = line.replace("tone", "piper", 1)
                PERSONA.write_text("\n".join(lines) + "\n", encoding="utf-8")
                did(f"switched {PERSONA.name} to the piper engine")
                return
    warn(f"couldn't find `voice: engine:` in {PERSONA} — set it to piper by hand")


def ensure_whisper() -> None:
    step("speech recognition")
    if not _installed("faster_whisper"):
        warn("faster-whisper is not installed — pip install -r requirements.txt")
        return
    print("    fetching the recogniser (~150MB, once)…")
    try:
        from faster_whisper import WhisperModel

        WhisperModel("base.en", device="cpu", compute_type="int8")
        did("whisper base.en ready")
    except Exception as exc:
        warn(f"download failed: {exc}")


def _installed(module: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# ------------------------------------------------------------------- finish


def next_steps() -> None:
    token = os.environ.get("ASSISTANT_TOKEN", "").strip()
    print(_c("1", "\n  Ready. In one terminal:\n"))
    print(f"    {_c('36', 'python run_all.py')}          talk to her, with her face on screen")
    print(_c("2", "\n  or drive the pieces yourself:\n"))
    print(f"    {_c('36', 'python run_server.py')}       the brain")
    print(f"    {_c('36', 'python run_listen.py')}       talk out loud   (needs a mic)")
    print(f"    {_c('36', 'python run_voice.py')}        type, hear her answer")
    print(f"    {_c('36', 'python run_chat.py')}         the tuning terminal")
    print(f"    {_c('36', 'python run_telegram.py')}     the phone client")
    if token:
        print(_c("2", "\n  Her face, once the server is up:\n"))
        print(f"    {_c('36', f'http://127.0.0.1:8000/avatar#token={token}')}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--no-voice", action="store_true")
    parser.add_argument("--whisper", action="store_true")
    parser.add_argument("--check", action="store_true", help="report only")
    args = parser.parse_args()

    if load_dotenv is None:
        print("python-dotenv is missing. Start with:\n    pip install -r requirements.txt")
        return 1

    if not args.check:
        ensure_env()
    load_dotenv(ENV, override=True)
    if not args.check:
        if not args.no_voice:
            ensure_voice(args.voice)
        if args.whisper:
            ensure_whisper()

    step("checks")
    from assistant.preflight import checks, report

    blocking = report(checks())
    if blocking:
        return 1

    next_steps()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
