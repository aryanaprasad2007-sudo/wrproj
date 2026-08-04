import asyncio

import pytest

from assistant.engine import Assistant
from conftest import FakeAPI


async def collect(engine: Assistant, session: str, text=None, regenerate=False):
    return [e async for e in engine.stream(session, text, regenerate=regenerate)]


# --------------------------------------------------------------- happy path


async def test_streams_deltas_then_done(engine: Assistant, api: FakeAPI) -> None:
    api.queue_reply(["[", "bo", "red", "]", " The", " dentist."])
    events = await collect(engine, "s", "what was that")

    # The tag must land before any text — the voice client and the avatar both
    # need the expression while she is still speaking, not after.
    assert [e["type"] for e in events] == ["tag", "delta", "delta", "done"]
    assert events[0] == {"type": "tag", "tag": "bored"}
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "The dentist."

    done = events[-1]
    assert done["tag"] == "bored"
    assert done["text"] == "The dentist."
    assert done["usage"]["cache_read_input_tokens"] == 1100


async def test_history_keeps_the_tag_but_output_strips_it(
    engine: Assistant, api: FakeAPI
) -> None:
    api.queue_reply(["[flat] What."])
    done = (await collect(engine, "s", "hi"))[-1]

    assert done["text"] == "What."
    history = engine.history("s")
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "[flat] What."},
    ]


async def test_send_returns_only_the_terminal_event(
    engine: Assistant, api: FakeAPI
) -> None:
    api.queue_reply(["[neutral] Fine."])
    assert (await engine.send("s", "hi"))["text"] == "Fine."


# ------------------------------------------------------------ request shape


async def test_request_shape(engine: Assistant, api: FakeAPI) -> None:
    api.queue_reply(["[neutral] ok"])
    await collect(engine, "s", "hello")

    body = api.last
    assert body["model"] == "claude-opus-5"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "low"}
    assert isinstance(body["system"], list)


async def test_messages_alternate_and_end_on_user(
    engine: Assistant, api: FakeAPI
) -> None:
    api.queue_reply(["[neutral] a"])
    await collect(engine, "s", "one")
    api.queue_reply(["[neutral] b"])
    await collect(engine, "s", "two")

    roles = [m["role"] for m in api.last["messages"]]
    assert roles[0] == "user"
    assert roles[-1] == "user"
    assert all(a != b for a, b in zip(roles, roles[1:])), roles


async def test_two_cache_breakpoints_in_the_right_places(
    engine: Assistant, api: FakeAPI
) -> None:
    api.queue_reply(["[neutral] ok"])
    await collect(engine, "s", "hello")

    msgs = api.last["messages"]
    marks = [
        i
        for i, m in enumerate(msgs)
        if isinstance(m["content"], list) and any("cache_control" in b for b in m["content"])
    ]
    assert marks == [len(engine.persona.few_shot) - 1, len(msgs) - 1]
    # The API caps breakpoints at 4; we must stay well under.
    assert len(marks) <= 4
    # System carries no breakpoint while examples exist — it'd be redundant.
    assert "cache_control" not in api.last["system"][0]


async def test_sessions_do_not_leak_into_each_other(
    engine: Assistant, api: FakeAPI
) -> None:
    api.queue_reply(["[neutral] a"])
    await collect(engine, "alice", "my secret")
    api.queue_reply(["[neutral] b"])
    await collect(engine, "bob", "hello")

    texts = [m["content"] for m in api.last["messages"] if isinstance(m["content"], str)]
    assert "my secret" not in texts
    assert len(engine.history("alice")) == 2
    assert len(engine.history("bob")) == 2


# --------------------------------------------------------------- regenerate


async def test_regenerate_drops_only_the_assistant_turn(
    engine: Assistant, api: FakeAPI
) -> None:
    api.queue_reply(["[flat] first"])
    await collect(engine, "s", "hi")

    api.queue_reply(["[bored] second"])
    done = (await collect(engine, "s", None, regenerate=True))[-1]

    assert done["text"] == "second"
    assert engine.history("s") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "[bored] second"},
    ]


async def test_regenerate_on_empty_history_errors(engine: Assistant) -> None:
    events = await collect(engine, "s", None, regenerate=True)
    assert events == [{"type": "error", "message": "nothing to regenerate"}]


async def test_empty_message_errors(engine: Assistant) -> None:
    events = await collect(engine, "s", None)
    assert events[-1]["type"] == "error"


# ------------------------------------------------------------- failure paths


@pytest.mark.parametrize("status", [429, 500, 400])
async def test_api_errors_surface_and_keep_the_user_turn(
    engine: Assistant, api: FakeAPI, status: int
) -> None:
    """A failed turn must not swallow what the user typed — retry has to work."""
    api.queue_status(status)
    events = await collect(engine, "s", "hello")

    assert events[-1]["type"] == "error"
    assert engine.history("s") == [{"role": "user", "content": "hello"}]

    api.queue_reply(["[neutral] recovered"])
    assert (await collect(engine, "s", None, regenerate=True))[-1]["text"] == "recovered"


async def test_refusal_is_reported_not_stored(engine: Assistant, api: FakeAPI) -> None:
    api.queue_reply(["partial"], stop_reason="refusal")
    events = await collect(engine, "s", "hello")

    assert events[-1]["type"] == "error"
    assert [m["role"] for m in engine.history("s")] == ["user"]


# -------------------------------------------------------------- concurrency


async def test_concurrent_sends_do_not_corrupt_history(
    engine: Assistant, api: FakeAPI
) -> None:
    """Two messages fired at once from a phone must not interleave."""
    api.queue_reply(["[neutral] one"])
    api.queue_reply(["[neutral] two"])

    await asyncio.gather(engine.send("s", "first"), engine.send("s", "second"))

    roles = [m["role"] for m in engine.history("s")]
    assert roles == ["user", "assistant", "user", "assistant"]


# ------------------------------------------------------------------ persona


async def test_reload_picks_up_a_different_file(engine: Assistant, tmp_path) -> None:
    other = tmp_path / "other.yaml"
    other.write_text(
        "name: Other\nemotions: [neutral]\nidentity: You are Other.\n", encoding="utf-8"
    )
    assert engine.reload(other).name == "Other"
    assert engine.persona.name == "Other"


async def test_clear_wipes_the_session(engine: Assistant, api: FakeAPI) -> None:
    api.queue_reply(["[neutral] ok"])
    await collect(engine, "s", "hi")
    engine.clear("s")
    assert engine.history("s") == []
