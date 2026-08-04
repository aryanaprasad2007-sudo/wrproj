import pytest

from assistant.emotions import split_emotion
from assistant.persona import load
from conftest import PERSONA


@pytest.fixture(scope="module")
def persona():
    return load(PERSONA)


def test_model_config(persona) -> None:
    assert persona.model == "claude-opus-5"
    # Disabling thinking on Opus 5 leaks tool calls into visible text and
    # <thinking> tags into output; low effort is the right latency lever.
    assert persona.thinking_param == {"type": "adaptive"}
    assert persona.effort in {"low", "medium", "high", "xhigh", "max"}
    assert persona.max_tokens >= 1024


def test_system_prompt_has_every_section(persona) -> None:
    for section in [
        "Who you are",
        "How you speak",
        "When to drop the act",
        "Response format",
        "Emotion tags",
    ]:
        assert section in persona.system, section


def test_declared_emotions_appear_in_the_prompt(persona) -> None:
    for emotion in persona.emotions:
        assert f"[{emotion}]" in persona.system


def test_few_shot_alternates_and_starts_on_user(persona) -> None:
    roles = [m["role"] for m in persona.few_shot]
    assert roles, "the persona has no examples — they carry the register"
    assert roles[0] == "user"
    assert roles[-1] == "assistant"
    assert all(a != b for a, b in zip(roles, roles[1:])), roles


def test_every_example_uses_a_declared_tag(persona) -> None:
    for msg in persona.few_shot:
        if msg["role"] != "assistant":
            continue
        tag, body = split_emotion(msg["content"])
        assert tag in persona.emotions, f"undeclared tag {tag!r}"
        assert body and not body.startswith("["), body[:40]


def test_examples_obey_the_format_rules(persona) -> None:
    """No markdown — the text is spoken aloud in phase 2."""
    for msg in persona.few_shot:
        if msg["role"] != "assistant":
            continue
        _, body = split_emotion(msg["content"])
        assert "**" not in body and "* " not in body
        assert not body.lstrip().startswith(("-", "#", "1."))


def test_sincerity_switch_is_present(persona) -> None:
    """The one failure that actually matters — she must drop the bit when it counts."""
    lowered = persona.system.lower()
    assert "drop the act" in lowered
    assert any(w in lowered for w in ("distress", "medical", "safety"))


def test_empty_user_block_is_omitted(persona) -> None:
    """Placeholder guidance must not leak into the prompt as if it were context."""
    assert "person you work for" not in persona.system.lower()


def test_incomplete_examples_are_skipped(tmp_path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text(
        "name: X\nemotions: [neutral]\n"
        "examples:\n"
        "  - user: hi\n"
        "    assistant: '[neutral] hello'\n"
        "  - user: orphan\n",  # no assistant reply — would break alternation
        encoding="utf-8",
    )
    assert len(load(path).few_shot) == 2


def test_user_block_is_included_when_filled(tmp_path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text(
        "name: X\nemotions: [neutral]\nuser:\n  name: Sam\n  notes: Works nights.\n",
        encoding="utf-8",
    )
    system = load(path).system
    assert "Sam" in system and "Works nights." in system
