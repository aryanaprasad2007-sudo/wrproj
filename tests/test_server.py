import json

import pytest
from fastapi.testclient import TestClient

from assistant.server import create_app
from conftest import FakeAPI

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(engine):
    with TestClient(create_app(token=TOKEN, engine=engine)) as c:
        yield c


# --------------------------------------------------------------------- auth


def test_health_needs_no_auth(client) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["persona"] == "Rei"
    assert body["model"] == "claude-opus-5"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": TOKEN},  # missing the Bearer prefix
        {"Authorization": "Basic dGVzdC10b2tlbg=="},
    ],
)
def test_chat_rejects_bad_auth(client, headers) -> None:
    resp = client.post("/chat", json={"session_id": "s", "message": "hi"}, headers=headers)
    assert resp.status_code == 401


def test_every_mutating_route_is_guarded(client) -> None:
    """A new endpoint added without a guard should fail this."""
    for method, path, body in [
        ("post", "/chat", {"session_id": "s", "message": "hi"}),
        ("post", "/chat/stream", {"session_id": "s", "message": "hi"}),
        ("post", "/sessions/s/clear", None),
        ("post", "/persona/reload", None),
    ]:
        resp = getattr(client, method)(path, json=body)
        assert resp.status_code == 401, f"{path} is unguarded"


def test_missing_token_refuses_to_build(monkeypatch) -> None:
    """Must fail at construction with a readable message, not a startup traceback."""
    monkeypatch.delenv("ASSISTANT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ASSISTANT_TOKEN"):
        create_app()


def test_blank_token_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_TOKEN", "   ")
    with pytest.raises(RuntimeError, match="ASSISTANT_TOKEN"):
        create_app()


# --------------------------------------------------------------------- chat


def test_chat_returns_text_and_tag(client, api: FakeAPI) -> None:
    api.queue_reply(["[bored] The dentist."])
    body = client.post(
        "/chat", json={"session_id": "s", "message": "what was it"}, headers=AUTH
    ).json()

    assert body["text"] == "The dentist."
    assert body["tag"] == "bored"
    assert "usage" in body


def test_chat_is_stateful_across_calls(client, api: FakeAPI, engine) -> None:
    api.queue_reply(["[neutral] one"])
    client.post("/chat", json={"session_id": "s", "message": "first"}, headers=AUTH)
    api.queue_reply(["[neutral] two"])
    client.post("/chat", json={"session_id": "s", "message": "second"}, headers=AUTH)

    assert len(engine.history("s")) == 4
    sent = [m["content"] for m in api.last["messages"] if isinstance(m["content"], str)]
    assert "first" in sent


def test_model_failure_becomes_502(client, api: FakeAPI) -> None:
    api.queue_status(500)
    resp = client.post("/chat", json={"session_id": "s", "message": "hi"}, headers=AUTH)
    assert resp.status_code == 502


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "", "message": "hi"},
        {"session_id": "s", "message": ""},
        {"session_id": "s"},
        {"message": "hi"},
        {"session_id": "s", "message": "x" * 8001},
    ],
)
def test_chat_validates_input(client, payload) -> None:
    resp = client.post("/chat", json=payload, headers=AUTH)
    assert resp.status_code == 422


# ------------------------------------------------------------------- stream


def test_stream_emits_sse_deltas_then_done(client, api: FakeAPI) -> None:
    api.queue_reply(["[neutral] Six", "ty-one."])

    with client.stream(
        "POST", "/chat/stream", json={"session_id": "s", "message": "weather"}, headers=AUTH
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[6:])
            for line in resp.iter_lines()
            if line.startswith("data: ")
        ]

    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Sixty-one."
    assert events[-1]["tag"] == "neutral"


def test_stream_regenerate(client, api: FakeAPI) -> None:
    api.queue_reply(["[flat] first"])
    client.post("/chat", json={"session_id": "s", "message": "hi"}, headers=AUTH)

    api.queue_reply(["[bored] second"])
    with client.stream(
        "POST",
        "/chat/stream",
        json={"session_id": "s", "message": "ignored", "regenerate": True},
        headers=AUTH,
    ) as resp:
        events = [
            json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")
        ]

    assert events[-1]["text"] == "second"


# ------------------------------------------------------------------ session


def test_clear_endpoint(client, api: FakeAPI, engine) -> None:
    api.queue_reply(["[neutral] ok"])
    client.post("/chat", json={"session_id": "s", "message": "hi"}, headers=AUTH)
    assert engine.history("s")

    assert client.post("/sessions/s/clear", headers=AUTH).status_code == 200
    assert engine.history("s") == []


def test_reload_endpoint(client) -> None:
    body = client.post("/persona/reload", headers=AUTH).json()
    assert body == {"status": "reloaded", "persona": "Rei"}
