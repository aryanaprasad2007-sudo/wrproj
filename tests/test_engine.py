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
    # Assistant turns are stored as blocks, not text: thinking and tool_use
    # blocks have to survive the round trip or the next request is rejected.
    history = engine.history("s")
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "[flat] What."}]},
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
    # Volatile context rides last, after everything cached.
    assert roles[-1] == "system"
    conversation = roles[:-1]
    assert conversation[0] == "user"
    assert conversation[-1] == "user"
    assert all(a != b for a, b in zip(conversation, conversation[1:])), roles


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
    few_shot = len(engine.persona.few_shot)
    # End of the stable prefix, then the last conversation turn. The trailing
    # context message sits after both, so changing it invalidates neither.
    assert marks == [few_shot - 1, few_shot]
    assert msgs[-1]["role"] == "system"
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
        {"role": "assistant", "content": [{"type": "text", "text": "[bored] second"}]},
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


# ------------------------------------------------------------------ context


async def test_volatile_context_rides_last(engine: Assistant, api: FakeAPI) -> None:
    """The clock changes every request. In the cached prefix it would void the
    persona, the examples and the whole history, every single turn."""
    api.queue_reply(["[neutral] ok"])
    await collect(engine, "s", "hello")

    context = api.last["messages"][-1]
    assert context["role"] == "system"
    assert "The time is" in context["content"]
    assert len(api.last["system"]) == 1
    assert "The time is" not in api.last["system"][0]["text"]


SYSTEM_ROLE_400 = (
    '{"type":"error","error":{"type":"invalid_request_error",'
    "\"message\":\"role 'system' is not supported on this model\"}}"
)


async def test_falls_back_when_the_model_rejects_a_system_message(
    engine: Assistant, api: FakeAPI
) -> None:
    """Not every model takes a mid-conversation system role. Rather than fail
    the turn, move the context into the system prompt and retry."""
    api.queue_status(400, SYSTEM_ROLE_400)
    api.queue_reply(["[neutral] recovered"])

    events = await collect(engine, "s", "hello")

    assert events[-1]["type"] == "done"
    assert events[-1]["text"] == "recovered"
    assert len(api.last["system"]) == 2, "context moved into the system prompt"
    assert "The time is" in api.last["system"][1]["text"]
    assert api.last["messages"][-1]["role"] == "user"


async def test_the_fallback_is_remembered(engine: Assistant, api: FakeAPI) -> None:
    """One probe per process, not one per turn."""
    api.queue_status(400, SYSTEM_ROLE_400)
    api.queue_reply(["[neutral] one"])
    await collect(engine, "s", "first")

    api.queue_reply(["[neutral] two"])
    await collect(engine, "s", "second")

    assert len(api.requests) == 3, "must not re-probe the rejected channel"
    assert len(api.last["system"]) == 2


async def test_other_400s_are_not_swallowed(engine: Assistant, api: FakeAPI) -> None:
    api.queue_status(
        400,
        '{"type":"error","error":{"type":"invalid_request_error",'
        '"message":"max_tokens is too large"}}',
    )
    events = await collect(engine, "s", "hello")
    assert events[-1]["type"] == "error"
    assert "max_tokens" in events[-1]["message"]


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
