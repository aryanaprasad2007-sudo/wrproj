import json
from datetime import datetime, timedelta, timezone

import pytest

from assistant.engine import Assistant
from assistant.memory import MemoryStore
from assistant.reminders import ReminderStore
from assistant.tools import MAX_TOOL_ROUNDS, Toolbox
from assistant.tools import build as build_toolbox
from conftest import PERSONA, FakeAPI


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(tmp_path / "m.json")


@pytest.fixture
def reminders(tmp_path):
    return ReminderStore(tmp_path / "r.json")


@pytest.fixture
def engine(api: FakeAPI, store, memory, reminders):
    return Assistant(
        PERSONA, store=store, client=api.client(), memory=memory, reminders=reminders
    )


async def collect(engine: Assistant, text: str, session: str = "s"):
    return [e async for e in engine.stream(session, text)]


# ------------------------------------------------------------------ toolbox


def test_definitions_are_ordered_deterministically(memory, reminders) -> None:
    """Tools render first in the prompt — reordering them voids the whole cache."""
    first = build_toolbox({}, memory, reminders).definitions()
    second = build_toolbox({}, memory, reminders).definitions()
    assert [t["name"] for t in first] == [t["name"] for t in second]
    assert [t["name"] for t in first] == sorted(t["name"] for t in first)


def test_config_selects_which_tools_exist(memory, reminders) -> None:
    assert build_toolbox({"memory": True, "reminders": False}, memory, reminders).names == [
        "forget",
        "remember",
    ]
    assert not build_toolbox({"memory": False, "reminders": False}, memory, reminders)


def test_web_search_is_a_server_tool_with_no_handler(memory, reminders) -> None:
    box = build_toolbox({"web_search": True, "memory": False, "reminders": False}, memory, reminders)
    definitions = box.definitions()
    assert definitions[0]["type"] == "web_search_20260209"
    assert box.names == [], "server tools are executed by Anthropic, not by us"


def test_descriptions_say_when_to_call(memory, reminders) -> None:
    """Recent models under-reach for custom tools given capability-only wording."""
    for definition in build_toolbox({}, memory, reminders).definitions():
        assert "Call this" in definition["description"], definition["name"]


async def test_unknown_tool_is_reported_not_raised(memory, reminders) -> None:
    output, failed = await build_toolbox({}, memory, reminders).run("nope", {}, "s")
    assert failed and "nope" in output


async def test_a_failing_tool_comes_back_as_an_error_result(memory, reminders) -> None:
    """She should be able to read the message and correct herself."""
    box = build_toolbox({}, memory, reminders)
    output, failed = await box.run("set_reminder", {"text": "x", "due_at": "tuesday"}, "s")
    assert failed and "ISO 8601" in output


# ------------------------------------------------------------ memory tools


async def test_remember_writes_a_fact(engine, api: FakeAPI, memory) -> None:
    api.queue_tool_use([("remember", {"text": "Allergic to shellfish"})])
    api.queue_reply(["[neutral] Noted."])

    events = await collect(engine, "I'm allergic to shellfish")

    assert [f["text"] for f in memory.all()] == ["Allergic to shellfish"]
    assert events[-1]["type"] == "done"
    assert events[-1]["text"] == "Noted."
    assert events[-1]["tool_rounds"] == 1


async def test_tool_use_and_result_are_surfaced(engine, api: FakeAPI) -> None:
    """The voice client needs these to say something while she works."""
    api.queue_tool_use([("remember", {"text": "Works nights"})])
    api.queue_reply(["[neutral] Fine."])

    events = await collect(engine, "I work nights")
    kinds = [e["type"] for e in events]

    assert "tool_use" in kinds and "tool_result" in kinds
    use = next(e for e in events if e["type"] == "tool_use")
    assert use["name"] == "remember"
    assert use["input"] == {"text": "Works nights"}
    assert next(e for e in events if e["type"] == "tool_result")["is_error"] is False


async def test_the_result_is_sent_back_to_the_model(engine, api: FakeAPI) -> None:
    api.queue_tool_use([("remember", {"text": "Allergic to shellfish"})])
    api.queue_reply(["[neutral] Noted."])
    await collect(engine, "I'm allergic to shellfish")

    assert len(api.requests) == 2
    results = [
        block
        for message in api.requests[1]["messages"]
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert len(results) == 1
    assert results[0]["tool_use_id"] == "toolu_1"
    assert "Stored as memory 1" in results[0]["content"]


async def test_forget_removes_a_fact(engine, api: FakeAPI, memory) -> None:
    memory.add("Allergic to shellfish")
    api.queue_tool_use([("forget", {"id": 1})])
    api.queue_reply(["[neutral] Gone."])

    await collect(engine, "actually that's wrong")
    assert memory.all() == []


async def test_remembered_facts_reach_the_prompt(engine, api: FakeAPI, memory) -> None:
    memory.add("Allergic to shellfish")
    api.queue_reply(["[neutral] Noted."])
    await collect(engine, "what should I order")

    context = api.last["messages"][-1]
    assert context["role"] == "system"
    assert "Allergic to shellfish" in context["content"]


# ---------------------------------------------------------- reminder tools


async def test_set_reminder_stores_it(engine, api: FakeAPI, reminders) -> None:
    due = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    api.queue_tool_use([("set_reminder", {"text": "call the dentist", "due_at": due})])
    api.queue_reply(["[neutral] Set."])

    await collect(engine, "remind me in an hour to call the dentist", session="telegram:7")

    pending = reminders.pending("telegram:7")
    assert [r["text"] for r in pending] == ["call the dentist"]


async def test_a_reminder_belongs_to_the_session_that_set_it(
    engine, api: FakeAPI, reminders
) -> None:
    due = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    api.queue_tool_use([("set_reminder", {"text": "x", "due_at": due})])
    api.queue_reply(["[neutral] Set."])
    await collect(engine, "remind me", session="telegram:7")

    assert reminders.pending("telegram:9") == []


async def test_a_bad_time_is_handed_back_for_her_to_fix(
    engine, api: FakeAPI, reminders
) -> None:
    api.queue_tool_use([("set_reminder", {"text": "x", "due_at": "tomorrow-ish"})])
    api.queue_reply(["[flat] Try again."])

    events = await collect(engine, "remind me tomorrow-ish")

    assert next(e for e in events if e["type"] == "tool_result")["is_error"] is True
    assert events[-1]["type"] == "done", "a tool error must not end the turn"
    results = [
        block
        for message in api.requests[1]["messages"]
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert results[0]["is_error"] is True


# ------------------------------------------------------------- the tool loop


async def test_parallel_calls_return_in_one_user_message(engine, api: FakeAPI) -> None:
    """Splitting them trains the model out of calling tools in parallel."""
    api.queue_tool_use(
        [("remember", {"text": "one"}), ("remember", {"text": "two"})]
    )
    api.queue_reply(["[neutral] Both noted."])

    await collect(engine, "two things")

    tool_result_messages = [
        m
        for m in api.requests[1]["messages"]
        if isinstance(m.get("content"), list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    ]
    assert len(tool_result_messages) == 1
    assert len(tool_result_messages[0]["content"]) == 2


async def test_a_tool_only_first_round_does_not_leak_the_tag(
    engine, api: FakeAPI
) -> None:
    """A round with no text must not resolve the tag parser early, or the tag
    ends up in the spoken reply and she says 'neutral' out loud."""
    api.queue_tool_use([("remember", {"text": "one"})])
    api.queue_reply(["[neutral] Noted."])

    events = await collect(engine, "remember this")
    spoken = "".join(e["text"] for e in events if e["type"] == "delta")

    assert spoken == "Noted."
    assert "[neutral]" not in spoken
    assert events[-1]["tag"] == "neutral"


async def test_text_before_a_tool_call_is_still_streamed(engine, api: FakeAPI) -> None:
    """For voice this is her saying 'let me check' while she works."""
    api.queue_tool_use([("list_reminders", {})], text="[bored] Looking. ")
    api.queue_reply(["Nothing until Tuesday."])

    events = await collect(engine, "what's coming up")
    spoken = "".join(e["text"] for e in events if e["type"] == "delta")

    assert spoken.startswith("Looking.")
    assert "Nothing until Tuesday." in spoken
    assert events[0] == {"type": "tag", "tag": "bored"}


async def test_several_rounds_chain(engine, api: FakeAPI, memory) -> None:
    api.queue_tool_use([("remember", {"text": "one"})])
    api.queue_tool_use([("remember", {"text": "two"})])
    api.queue_reply(["[neutral] Done."])

    events = await collect(engine, "remember a couple of things")

    assert events[-1]["tool_rounds"] == 2
    assert len(memory.all()) == 2
    assert len(api.requests) == 3


async def test_a_runaway_loop_is_capped(engine, api: FakeAPI) -> None:
    """Turns an unbounded bill into a truncated answer."""
    for _ in range(MAX_TOOL_ROUNDS + 2):
        api.queue_tool_use([("remember", {"text": "again"})])

    events = await collect(engine, "loop forever")

    assert events[-1]["type"] == "error"
    assert str(MAX_TOOL_ROUNDS) in events[-1]["message"]
    assert len(api.requests) <= MAX_TOOL_ROUNDS + 1


async def test_usage_is_summed_across_rounds(engine, api: FakeAPI) -> None:
    api.queue_tool_use([("remember", {"text": "one"})])
    api.queue_reply(["[neutral] Done."])

    done = (await collect(engine, "hi"))[-1]
    assert done["usage"]["input_tokens"] == 900 + 1200


async def test_history_round_trips_the_tool_call(engine, api: FakeAPI) -> None:
    """The assistant turn must go back with its tool_use block intact."""
    api.queue_tool_use([("remember", {"text": "one"})])
    api.queue_reply(["[neutral] Done."])
    await collect(engine, "hi")

    roles = [m["role"] for m in engine.history("s")]
    assert roles == ["user", "assistant", "user", "assistant"]

    assistant = engine.history("s")[1]["content"]
    assert any(b["type"] == "tool_use" and b["name"] == "remember" for b in assistant)


async def test_regenerate_rewinds_past_the_whole_tool_exchange(
    engine, api: FakeAPI
) -> None:
    """Popping one message would strand a tool result with no matching call."""
    api.queue_tool_use([("remember", {"text": "one"})])
    api.queue_reply(["[neutral] First."])
    await collect(engine, "hi")

    api.queue_reply(["[flat] Second."])
    events = [e async for e in engine.stream("s", None, regenerate=True)]

    assert events[-1]["text"] == "Second."
    roles = [m["role"] for m in engine.history("s")]
    assert roles == ["user", "assistant"]


async def test_tools_are_absent_from_the_request_when_all_disabled(
    api: FakeAPI, store, tmp_path, memory, reminders
) -> None:
    persona = tmp_path / "p.yaml"
    persona.write_text(
        "name: X\nemotions: [neutral]\ntools:\n  memory: false\n  reminders: false\n",
        encoding="utf-8",
    )
    bare = Assistant(
        persona, store=store, client=api.client(), memory=memory, reminders=reminders
    )
    api.queue_reply(["[neutral] ok"])
    await collect(bare, "hi")

    assert "tools" not in api.last


async def test_tools_render_before_system_and_stay_stable(engine, api: FakeAPI) -> None:
    api.queue_reply(["[neutral] one"])
    await collect(engine, "first")
    first = json.dumps(api.last["tools"])

    api.queue_reply(["[neutral] two"])
    await collect(engine, "second")
    assert json.dumps(api.last["tools"]) == first
