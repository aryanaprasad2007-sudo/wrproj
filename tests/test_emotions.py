import pytest

from assistant.emotions import EmotionStripper, split_emotion


def stream(chunks: list[str]) -> tuple[str | None, str]:
    s = EmotionStripper()
    out = "".join(s.feed(c) for c in chunks)
    return s.tag, out + s.flush()


@pytest.mark.parametrize(
    "chunks,tag,text",
    [
        # Whole response in one delta
        (["[neutral] Sixty-one and overcast."], "neutral", "Sixty-one and overcast."),
        # Tag split across deltas, `]` mid-chunk
        (["[bo", "red] The", " dentist."], "bored", "The dentist."),
        # `]` lands exactly on a chunk boundary — the space arrives next delta
        (["[", "bo", "red", "]", " The", " dentist."], "bored", "The dentist."),
        # No tag at all: nothing may be swallowed
        (["Just ", "text ", "here."], None, "Just text here."),
        # Leading whitespace before the tag
        (["  [flat] What."], "flat", "What."),
        # Bracket that isn't a tag must not hold output hostage
        (["[" + "x" * 40 + " and more"], None, "[" + "x" * 40 + " and more"),
    ],
)
def test_streaming_cases(chunks, tag, text) -> None:
    assert stream(chunks) == (tag, text)


def test_flush_releases_an_incomplete_buffer() -> None:
    s = EmotionStripper()
    assert s.feed("[neu") == ""
    assert s.flush() == "[neu"
    assert s.flush() == ""  # idempotent


def test_empty_stream() -> None:
    assert stream([]) == (None, "")


def test_tag_only_response() -> None:
    assert stream(["[bored]"]) == ("bored", "")


@pytest.mark.parametrize(
    "text,tag,body",
    [
        ("[neutral] Hello.", "neutral", "Hello."),
        ("[ Bored ] Hello.", "bored", "Hello."),  # normalised
        ("No tag here.", None, "No tag here."),
        ("[" + "x" * 60 + "] nope", None, "[" + "x" * 60 + "] nope"),
    ],
)
def test_split_emotion(text, tag, body) -> None:
    assert split_emotion(text) == (tag, body)


def test_streaming_and_whole_string_agree() -> None:
    full = "[smug] Naturally."
    assert stream([full]) == split_emotion(full)
