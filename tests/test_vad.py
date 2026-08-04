import pytest

from assistant.audio.vad import Segmenter, SegmenterConfig, WebrtcVAD, frames_of

CFG = SegmenterConfig(
    sample_rate=16000, frame_ms=30, start_frames=3,
    end_silence_ms=300, pre_roll_ms=150, min_utterance_ms=100,
)
FRAME = b"\x00" * CFG.frame_bytes


class ScriptedVAD:
    """Speech/silence from a fixed script — no audio, no model, deterministic."""

    def __init__(self, script: str) -> None:
        self.script = script
        self.i = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        ch = self.script[self.i] if self.i < len(self.script) else "."
        self.i += 1
        return ch == "S"


def run(script: str, config: SegmenterConfig = CFG) -> list[dict]:
    """`S` = speech frame, `.` = silence frame."""
    seg = Segmenter(ScriptedVAD(script), config)
    events = []
    for i in range(len(script)):
        events += seg.feed(bytes([i % 256]) * config.frame_bytes)
    tail = seg.flush()
    if tail:
        events.append(tail)
    return events


# ------------------------------------------------------------------- config


def test_rejects_frame_sizes_webrtc_cannot_use() -> None:
    with pytest.raises(ValueError, match="frame_ms"):
        SegmenterConfig(frame_ms=25)
    with pytest.raises(ValueError, match="sample_rate"):
        SegmenterConfig(sample_rate=44100)


def test_rejects_pre_roll_that_would_clip_the_first_syllable() -> None:
    """pre_roll shorter than the start debounce loses the start of every word."""
    with pytest.raises(ValueError, match="pre_roll_ms"):
        SegmenterConfig(frame_ms=30, start_frames=5, pre_roll_ms=60)


def test_frame_size_arithmetic() -> None:
    cfg = SegmenterConfig(sample_rate=16000, frame_ms=30)
    assert cfg.frame_bytes == 960  # 480 samples, 16-bit


def test_wrong_frame_size_is_rejected_loudly() -> None:
    seg = Segmenter(ScriptedVAD("S"), CFG)
    with pytest.raises(ValueError, match="expected"):
        seg.feed(b"\x00" * 100)


# ---------------------------------------------------------------- detection


def test_silence_produces_nothing() -> None:
    assert run("." * 20) == []


def test_a_single_speech_frame_is_debounced_away() -> None:
    """One frame is a click or a chair, not speech."""
    assert run("..S......." ) == []


def test_speech_start_fires_after_the_debounce() -> None:
    events = run("..SSSSSSSS")
    assert events[0]["type"] == "speech_start"


def test_utterance_is_emitted_after_the_end_silence() -> None:
    events = run("..SSSSSSSSSS" + "." * 12)
    kinds = [e["type"] for e in events]
    assert kinds == ["speech_start", "utterance"]
    assert events[1]["reason"] == "silence"


def test_short_pauses_do_not_split_an_utterance() -> None:
    """Breathing mid-sentence must not end the turn."""
    events = run("..SSSSS..SSSSS" + "." * 12)
    assert [e["type"] for e in events] == ["speech_start", "utterance"]


def test_two_utterances_are_separated() -> None:
    events = run("..SSSSSS" + "." * 12 + "SSSSSS" + "." * 12)
    assert [e["type"] for e in events] == [
        "speech_start", "utterance", "speech_start", "utterance",
    ]


# ------------------------------------------------------------------ pre-roll


def test_pre_roll_keeps_audio_from_before_speech_was_confirmed() -> None:
    """Without this the attack of the first word is missing from every capture."""
    cfg = SegmenterConfig(
        sample_rate=16000, frame_ms=30, start_frames=3,
        end_silence_ms=300, pre_roll_ms=150, min_utterance_ms=0,
    )
    events = run("...SSSSSS" + "." * 12, cfg)
    utterance = next(e for e in events if e["type"] == "utterance")

    # 5 pre-roll frames are retained; speech was confirmed on frame 6, so the
    # capture must reach back before it rather than starting there.
    captured = utterance["pcm"]
    assert len(captured) > 6 * cfg.frame_bytes
    assert captured[:1] != captured[-1:], "pre-roll frames should differ from later ones"


def test_pre_roll_does_not_leak_between_utterances() -> None:
    cfg = SegmenterConfig(
        sample_rate=16000, frame_ms=30, start_frames=3,
        end_silence_ms=300, pre_roll_ms=300, min_utterance_ms=0,
    )
    events = run("..SSSS" + "." * 12 + "SSSS" + "." * 12, cfg)
    lengths = [len(e["pcm"]) for e in events if e["type"] == "utterance"]
    assert len(lengths) == 2
    # The second must not carry a full window of the first one's trailing silence.
    assert lengths[1] <= lengths[0] + cfg.frame_bytes * 2


# -------------------------------------------------------------------- limits


def test_blips_are_discarded() -> None:
    """A cough clears the debounce but is not a sentence."""
    cfg = SegmenterConfig(
        sample_rate=16000, frame_ms=30, start_frames=3,
        end_silence_ms=150, pre_roll_ms=150, min_utterance_ms=1000,
    )
    events = run("..SSS" + "." * 8, cfg)
    assert [e["type"] for e in events] == ["speech_start"]
    assert not any(e["type"] == "utterance" for e in events)


def test_endless_speech_is_cut_at_the_maximum() -> None:
    cfg = SegmenterConfig(
        sample_rate=16000, frame_ms=30, start_frames=3,
        end_silence_ms=300, pre_roll_ms=150, min_utterance_ms=0,
        max_utterance_ms=300,
    )
    events = run("S" * 60, cfg)
    utterances = [e for e in events if e["type"] == "utterance"]
    assert utterances and utterances[0]["reason"] == "max_length"


def test_trailing_silence_is_trimmed() -> None:
    cfg = SegmenterConfig(
        sample_rate=16000, frame_ms=30, start_frames=3,
        end_silence_ms=300, pre_roll_ms=150, min_utterance_ms=0,
    )
    short = run("..SSSSSS" + "." * 11, cfg)[1]["ms"]
    long = run("..SSSSSS" + "." * 40, cfg)[1]["ms"]
    assert short == long, "extra trailing silence must not inflate the utterance"


# --------------------------------------------------------------------- state


def test_active_tracks_whether_someone_is_talking() -> None:
    seg = Segmenter(ScriptedVAD("SSSSS" + "." * 20), CFG)
    assert not seg.active
    for _ in range(4):
        seg.feed(FRAME)
    assert seg.active
    for _ in range(20):
        seg.feed(FRAME)
    assert not seg.active


def test_flush_emits_an_utterance_in_progress() -> None:
    """A closing stream must not silently drop what was being said."""
    seg = Segmenter(ScriptedVAD("S" * 20), CFG)
    for _ in range(10):
        seg.feed(FRAME)
    tail = seg.flush()
    assert tail and tail["type"] == "utterance"
    assert seg.flush() is None


def test_reset_clears_everything() -> None:
    seg = Segmenter(ScriptedVAD("S" * 20), CFG)
    for _ in range(6):
        seg.feed(FRAME)
    seg.reset()
    assert not seg.active
    assert seg.flush() is None


# ------------------------------------------------------------------ helpers


def test_frames_of_drops_a_partial_tail() -> None:
    frames = frames_of(b"\x00" * 2500, 960)
    assert len(frames) == 2
    assert all(len(f) == 960 for f in frames)


def test_frames_of_handles_empty_and_exact() -> None:
    assert frames_of(b"", 960) == []
    assert len(frames_of(b"\x00" * 1920, 960)) == 2


# ------------------------------------------------------------- real detector


def test_webrtc_vad_runs_and_rejects_silence() -> None:
    vad = WebrtcVAD(2)
    assert vad.is_speech(b"\x00" * 960, 16000) is False


def test_webrtc_vad_accepts_every_supported_frame_size() -> None:
    vad = WebrtcVAD(1)
    for frame_ms in (10, 20, 30):
        samples = int(16000 * frame_ms / 1000)
        assert vad.is_speech(b"\x00" * samples * 2, 16000) in (True, False)
