from pathlib import Path

from assistant.store import ConversationStore

U = {"role": "user", "content": "u"}
A = {"role": "assistant", "content": "a"}


def test_roundtrip_and_isolation(tmp_path: Path) -> None:
    s = ConversationStore(tmp_path / "c.json")
    s.set("one", [U, A])
    s.set("two", [U])

    assert s.get("one") == [U, A]
    assert s.get("two") == [U]
    assert s.get("missing") == []
    assert sorted(s.sessions()) == ["one", "two"]


def test_get_returns_a_copy(tmp_path: Path) -> None:
    """Callers mutate the returned list; that must not reach into the store."""
    s = ConversationStore(tmp_path / "c.json")
    s.set("x", [U])
    s.get("x").append(A)
    assert s.get("x") == [U]


def test_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    ConversationStore(path).set("x", [U, A])
    assert ConversationStore(path).get("x") == [U, A]


def test_clear(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    s = ConversationStore(path)
    s.set("x", [U, A])
    s.clear("x")
    assert s.get("x") == []
    assert ConversationStore(path).get("x") == []


def test_trims_to_max_turns(tmp_path: Path) -> None:
    s = ConversationStore(tmp_path / "c.json", max_turns=4)
    s.set("x", [U, A] * 10)
    assert len(s.get("x")) == 4


def test_trimmed_history_starts_on_user(tmp_path: Path) -> None:
    """The API rejects a leading assistant turn, and few-shot examples end on one."""
    s = ConversationStore(tmp_path / "c.json", max_turns=3)
    s.set("x", [U, A, U, A, U, A])
    kept = s.get("x")
    assert kept[0]["role"] == "user"
    assert len(kept) <= 3


def test_corrupt_file_does_not_block_startup(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text("{not json at all", encoding="utf-8")
    s = ConversationStore(path)
    assert s.sessions() == []
    s.set("x", [U])  # and it recovers on the next write
    assert ConversationStore(path).get("x") == [U]


def test_non_dict_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text('["not", "a", "dict"]', encoding="utf-8")
    assert ConversationStore(path).sessions() == []


def test_write_is_atomic(tmp_path: Path) -> None:
    """No stray temp files left behind after a successful write."""
    path = tmp_path / "sub" / "c.json"
    s = ConversationStore(path)
    s.set("x", [U])
    assert path.exists()
    assert list(path.parent.glob("*.tmp")) == []


def test_memory_only_when_no_path() -> None:
    s = ConversationStore(None)
    s.set("x", [U])
    assert s.get("x") == [U]
