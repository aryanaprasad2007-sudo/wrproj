import pytest

from assistant.chunker import SentenceChunker


def run(text: str, deltas: int = 1, **kwargs) -> list[str]:
    """Feed `text` split into `deltas` pieces, mimicking a model stream."""
    c = SentenceChunker(**kwargs)
    step = max(1, len(text) // deltas)
    out: list[str] = []
    for i in range(0, len(text), step):
        out += c.feed(text[i : i + step])
    tail = c.flush()
    if tail:
        out.append(tail)
    return out


# ------------------------------------------------------------------ sentences


def test_splits_on_sentences() -> None:
    assert run("One thing. Two things. Three things.") == [
        "One thing.",
        "Two things.",
        "Three things.",
    ]


@pytest.mark.parametrize("deltas", [1, 3, 7, 40, 200])
def test_result_is_independent_of_delta_boundaries(deltas: int) -> None:
    """The model splits text arbitrarily; chunking must not depend on where."""
    text = "Sixty-one and overcast. Rain after four. Take the jacket."
    assert run(text, deltas) == [
        "Sixty-one and overcast.",
        "Rain after four.",
        "Take the jacket.",
    ]


def test_nothing_is_lost_or_duplicated() -> None:
    text = (
        "You have three unfinished ones. I'm not going to stop you, I'd just "
        "like it noted that I said something. What's the new one?"
    )
    assert "".join(run(text, deltas=25)).replace(" ", "") == text.replace(" ", "")


@pytest.mark.parametrize("mark", ["!", "?", "...", "?!"])
def test_other_terminators(mark: str) -> None:
    assert run(f"Really{mark} Yes indeed.") == [f"Really{mark}", "Yes indeed."]


def test_closing_quote_stays_with_its_sentence() -> None:
    assert run('She said "no." Then she left.') == ['She said "no."', "Then she left."]


# -------------------------------------------------------------- false splits


@pytest.mark.parametrize(
    "text",
    [
        "Dr. Smith is late again.",
        "The dentist at 10 a.m. tomorrow morning.",
        "That's 3.14 to two decimals, roughly.",
        "J. R. R. Tolkien wrote that one.",
        "Bring milk, eggs, etc. before you get home.",
    ],
)
def test_abbreviations_and_decimals_do_not_split(text: str) -> None:
    """A period inside a word must not be treated as the end of a sentence."""
    assert run(text, deltas=5, first_chunk_chars=500, target_chars=500) == [text]


# ------------------------------------------------------------------- latency


def test_first_chunk_is_emitted_early() -> None:
    """Time-to-first-sound dominates how responsive she feels."""
    c = SentenceChunker(first_chunk_chars=40, target_chars=200)
    long_opening = "The thing about that particular question, which you have asked before, "
    chunks = c.feed(long_opening)
    assert chunks, "should not wait for a full stop before the first chunk"
    assert len(chunks[0]) < 100


def test_later_chunks_are_allowed_to_be_longer() -> None:
    """Bigger chunks give the engine more context and better prosody."""
    c = SentenceChunker(first_chunk_chars=30, target_chars=200)
    c.feed("Short one. ")
    later = c.feed(
        "Now a considerably longer stretch of speech, with a comma here, "
        "that should not be cut at the very first opportunity available. "
    )
    assert later
    assert max(len(x) for x in later) > 40


def test_runaway_text_is_cut_at_whitespace() -> None:
    """No punctuation at all must not mean one enormous chunk."""
    text = " ".join(["word"] * 300)
    chunks = run(text, max_chars=120)
    assert all(len(c) <= 120 for c in chunks)
    assert not any(c.startswith(" ") or c.endswith(" ") for c in chunks)


def test_no_tiny_fragments() -> None:
    chunks = run("Yes. No. Maybe. Fine.", min_chars=12)
    assert all(len(c) >= 12 for c in chunks[:-1])


# -------------------------------------------------------------------- edges


def test_empty_input() -> None:
    assert run("") == []


def test_whitespace_only() -> None:
    assert run("   \n  ") == []


def test_flush_returns_the_remainder() -> None:
    c = SentenceChunker()
    assert c.feed("No terminator yet") == []
    assert c.flush() == "No terminator yet"
    assert c.flush() is None


def test_chunks_are_stripped() -> None:
    for chunk in run("One thing.   Two things.   Three things."):
        assert chunk == chunk.strip()
        assert chunk
