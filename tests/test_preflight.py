"""Setup and preflight: the bits that decide whether a fresh clone works."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from assistant.preflight import Check, checks, report

ROOT = Path(__file__).resolve().parent.parent
PERSONA = ROOT / "persona" / "rei.yaml"


def setup_module() -> None:
    """`run_setup.py` lives at the repo root, not in the package."""
    spec = importlib.util.spec_from_file_location("run_setup", ROOT / "run_setup.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules["run_setup"] = module


def named(found: list[Check], name: str) -> Check:
    return next(c for c in found if c.name == name)


# ---------------------------------------------------------------- the report


def test_a_missing_key_blocks_and_a_missing_mic_does_not(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    found = checks(PERSONA)

    assert named(found, "ANTHROPIC_API_KEY").required
    assert not named(found, "ANTHROPIC_API_KEY").ok
    # You can still type at her without a microphone.
    assert not named(found, "microphone").required


def test_every_failure_says_what_to_type(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ASSISTANT_TOKEN", raising=False)
    for check in checks(PERSONA):
        if not check.ok:
            assert check.fix, f"{check.name} fails with no way out"


def test_a_short_token_is_treated_as_unset(monkeypatch) -> None:
    """A truncated paste is worse than nothing — it fails at the first request."""
    monkeypatch.setenv("ASSISTANT_TOKEN", "abc")
    assert not named(checks(PERSONA), "ASSISTANT_TOKEN").ok


def test_the_example_placeholder_does_not_pass_as_a_key(monkeypatch) -> None:
    """Copying .env.example loads `sk-ant-...` into the environment, where it
    looks set. Waving it through means the first request is the error report."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-...")
    key = named(checks(PERSONA), "ANTHROPIC_API_KEY")

    assert not key.ok
    assert "placeholder" in key.detail


def test_a_real_looking_key_passes(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-" + "x" * 90)
    assert named(checks(PERSONA), "ANTHROPIC_API_KEY").ok


def test_the_placeholder_voice_reads_as_a_warning(monkeypatch) -> None:
    """It works, but nobody sitting down to test this wants bleeps."""
    voice = named(checks(PERSONA), "voice engine")
    assert not voice.ok and not voice.required
    assert "tone" in voice.detail


def test_a_broken_persona_is_reported_not_raised(tmp_path) -> None:
    broken = tmp_path / "bad.yaml"
    broken.write_text("name: [unclosed\n", encoding="utf-8")
    persona = named(checks(broken), "persona loads")
    assert not persona.ok and persona.required


def test_report_counts_only_blocking_failures(capsys) -> None:
    found = [
        Check("fine", True),
        Check("broken", False, fix="do the thing"),
        Check("optional", False, fix="or don't", needed_for="a nice-to-have"),
    ]
    assert report(found) == 1
    out = capsys.readouterr().out
    assert "do the thing" in out
    assert "a nice-to-have" in out


# ------------------------------------------------------------------- .env


def test_a_generated_token_is_long_enough_to_matter() -> None:
    """It guards the API spend, so it has to be a real secret."""
    import run_setup

    lines = run_setup._set([], "ASSISTANT_TOKEN", "x" * 43)
    assert run_setup._value(lines, "ASSISTANT_TOKEN") == "x" * 43


def test_setting_a_key_replaces_it_in_place() -> None:
    import run_setup

    lines = ["# comment", "ANTHROPIC_API_KEY=sk-ant-...", "ASSISTANT_PORT=8000"]
    updated = run_setup._set(lines, "ANTHROPIC_API_KEY", "sk-ant-real")

    assert updated[0] == "# comment", "comments survive"
    assert updated[1] == "ANTHROPIC_API_KEY=sk-ant-real"
    assert len(updated) == 3, "no duplicate line"


def test_the_example_placeholder_counts_as_unset() -> None:
    """Copying .env.example leaves `sk-ant-...` sitting there looking set."""
    import run_setup

    lines = ["ANTHROPIC_API_KEY=sk-ant-..."]
    assert run_setup._value(lines, "ANTHROPIC_API_KEY", placeholder="sk-ant-...") == ""


def test_a_failed_download_reports_the_cause_not_the_stack() -> None:
    """Python puts the cause on the last line and the stack above it, so
    printing the tail of a traceback shows the stack and hides the cause."""
    import run_setup

    traceback = (
        "Traceback (most recent call last):\n"
        '  File "urllib/request.py", line 1351, in do_open\n'
        "    raise URLError(err)\n"
        "urllib.error.URLError: <urlopen error Tunnel connection failed: 403>"
    )
    why = run_setup._why(traceback)

    assert why.startswith("urllib.error.URLError")
    assert "proxy" in why, "a 403 on CONNECT is a proxy, and saying so saves an hour"
    assert "Traceback" not in why


def test_a_silent_failure_still_says_something() -> None:
    import run_setup

    assert run_setup._why("") == "no output"


# ------------------------------------------------------------------- voice


@pytest.fixture
def persona_copy(tmp_path, monkeypatch):
    import run_setup

    copy = tmp_path / "rei.yaml"
    copy.write_text(PERSONA.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(run_setup, "PERSONA", copy)
    return copy


def test_switching_to_piper_keeps_the_comments(persona_copy, capsys) -> None:
    """That file is more comment than config; a YAML round-trip would eat it."""
    import run_setup

    before = persona_copy.read_text(encoding="utf-8")
    run_setup._use_piper()
    after = persona_copy.read_text(encoding="utf-8")

    assert "engine: piper" in after
    assert "engine: tone" not in after
    # Everything else is untouched, comments included.
    assert after.replace("engine: piper", "engine: tone") == before.rstrip("\n") + "\n"


def test_switching_twice_is_a_no_op(persona_copy, capsys) -> None:
    import run_setup

    run_setup._use_piper()
    once = persona_copy.read_text(encoding="utf-8")
    run_setup._use_piper()

    assert persona_copy.read_text(encoding="utf-8") == once
    assert "already uses piper" in capsys.readouterr().out


def test_only_the_voice_block_is_touched(persona_copy) -> None:
    """`stt:` has an `engine:` line too, and it must not be rewritten."""
    import run_setup

    run_setup._use_piper()
    text = persona_copy.read_text(encoding="utf-8")
    assert "engine: whisper" in text
