"""Shared fixtures.

The model is mocked at the HTTP layer rather than by patching the SDK, so tests
exercise real request construction — cache breakpoints, message alternation and
parameter shape are all checked against what would actually go on the wire.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import anthropic
import httpx
import pytest

from assistant.engine import Assistant
from assistant.store import ConversationStore

ROOT = Path(__file__).resolve().parent.parent
PERSONA = ROOT / "persona" / "rei.yaml"


def sse(events: Iterable[tuple[str, dict[str, Any]]]) -> str:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events)


def reply_stream(deltas: list[str], stop_reason: str = "end_turn") -> str:
    """A well-formed streaming response emitting `deltas` as text."""
    message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1100,
        },
    }
    return sse(
        [
            ("message_start", {"type": "message_start", "message": message}),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            *[
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": t},
                    },
                )
                for t in deltas
            ],
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                    "usage": {"output_tokens": 12},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


class FakeAPI:
    """Scriptable stand-in for the Messages API. Records every request body."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[httpx.Response] = []

    def queue_reply(self, deltas: list[str], stop_reason: str = "end_turn") -> None:
        self.responses.append(
            httpx.Response(
                200,
                content=reply_stream(deltas, stop_reason),
                headers={"content-type": "text/event-stream"},
            )
        )

    def queue_status(self, status: int, body: str = '{"error":{"message":"x"}}') -> None:
        self.responses.append(
            httpx.Response(status, content=body, headers={"content-type": "application/json"})
        )

    @property
    def last(self) -> dict[str, Any]:
        return self.requests[-1]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.read()))
        if not self.responses:
            raise AssertionError("model called more times than the test scripted")
        return self.responses.pop(0)

    def client(self) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            api_key="sk-ant-fake",
            max_retries=0,  # keep failure-path tests fast and deterministic
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self._handle)),
        )


@pytest.fixture
def api() -> FakeAPI:
    return FakeAPI()


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "conversations.json")


@pytest.fixture
def engine(api: FakeAPI, store: ConversationStore) -> Assistant:
    return Assistant(PERSONA, store=store, client=api.client())
