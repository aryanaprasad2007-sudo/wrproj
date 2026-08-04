from pathlib import Path

import pytest

from assistant.memory import MemoryStore


def test_add_and_list(tmp_path: Path) -> None:
    m = MemoryStore(tmp_path / "m.json")
    fact = m.add("Allergic to shellfish")
    assert fact["id"] == 1
    assert [f["text"] for f in m.all()] == ["Allergic to shellfish"]


def test_survives_restart_and_keeps_counting_ids(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    MemoryStore(path).add("first")
    reopened = MemoryStore(path)
    assert reopened.add("second")["id"] == 2, "ids must not restart and collide"


def test_remembering_the_same_thing_twice_does_not_duplicate(tmp_path: Path) -> None:
    """She has no way to know what she already wrote down."""
    m = MemoryStore(tmp_path / "m.json")
    first = m.add("Works nights")
    again = m.add("  works   NIGHTS  ")
    assert len(m.all()) == 1
    assert again["id"] == first["id"]


def test_whitespace_is_normalised(tmp_path: Path) -> None:
    m = MemoryStore(tmp_path / "m.json")
    assert m.add("  spread   over\n  lines ")["text"] == "spread over lines"


def test_empty_text_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        MemoryStore(tmp_path / "m.json").add("   ")


def test_long_facts_are_truncated(tmp_path: Path) -> None:
    m = MemoryStore(tmp_path / "m.json")
    assert len(m.add("x" * 5000)["text"]) == 500


def test_remove(tmp_path: Path) -> None:
    m = MemoryStore(tmp_path / "m.json")
    m.add("one")
    second = m.add("two")
    assert m.remove(second["id"])["text"] == "two"
    assert [f["text"] for f in m.all()] == ["one"]
    assert m.remove(999) is None


def test_removal_persists(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    m = MemoryStore(path)
    m.add("one")
    m.remove(1)
    assert MemoryStore(path).all() == []


def test_oldest_facts_fall_off_the_end(tmp_path: Path) -> None:
    """Bounds the prompt. Anything still true tends to get restated."""
    m = MemoryStore(tmp_path / "m.json", max_facts=3)
    for i in range(6):
        m.add(f"fact {i}")
    assert [f["text"] for f in m.all()] == ["fact 3", "fact 4", "fact 5"]


def test_search_is_case_insensitive(tmp_path: Path) -> None:
    m = MemoryStore(tmp_path / "m.json")
    m.add("Allergic to shellfish")
    m.add("Sister is called Maya")
    assert len(m.search("SHELLFISH")) == 1
    assert len(m.search("")) == 2


def test_prompt_rendering_includes_ids(tmp_path: Path) -> None:
    """She needs the ids to be able to call forget."""
    m = MemoryStore(tmp_path / "m.json")
    m.add("Allergic to shellfish")
    rendered = m.as_prompt()
    assert "[1]" in rendered and "shellfish" in rendered


def test_empty_memory_renders_to_nothing(tmp_path: Path) -> None:
    """No empty heading in the prompt when there's nothing to say."""
    assert MemoryStore(tmp_path / "m.json").as_prompt() == ""


def test_clear(tmp_path: Path) -> None:
    m = MemoryStore(tmp_path / "m.json")
    m.add("one")
    m.clear()
    assert m.all() == []


def test_corrupt_file_does_not_block_startup(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text("{ not json", encoding="utf-8")
    m = MemoryStore(path)
    assert m.all() == []
    m.add("recovered")
    assert MemoryStore(path).all()[0]["text"] == "recovered"


def test_works_without_a_file(tmp_path: Path) -> None:
    m = MemoryStore(None)
    m.add("in memory only")
    assert len(m.all()) == 1
