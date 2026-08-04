"""Reminder delivery: the endpoints, and the Telegram bot that drains them."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.engine import Assistant
from assistant.memory import MemoryStore
from assistant.reminders import ReminderStore
from assistant.server import create_app
from assistant.telegram import TelegramBot
from conftest import PERSONA, FakeAPI

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
MINE = 4242
PAST = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
FUTURE = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()


@pytest.fixture
def reminders(tmp_path):
    return ReminderStore(tmp_path / "r.json")


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(tmp_path / "m.json")


@pytest.fixture
def client(api: FakeAPI, store, memory, reminders):
    engine = Assistant(
        PERSONA, store=store, client=api.client(), memory=memory, reminders=reminders
    )
    with TestClient(create_app(token=TOKEN, engine=engine)) as c:
        yield c


# --------------------------------------------------------------- endpoints


def test_due_returns_only_what_is_actually_due(client, reminders) -> None:
    reminders.add("s", "overdue", PAST)
    reminders.add("s", "later", FUTURE)

    body = client.get("/reminders/due", params={"session_id": "s"}, headers=AUTH).json()
    assert [r["text"] for r in body["reminders"]] == ["overdue"]


def test_due_is_scoped_by_session(client, reminders) -> None:
    reminders.add("telegram:1", "mine", PAST)
    reminders.add("telegram:2", "theirs", PAST)

    body = client.get(
        "/reminders/due", params={"session_id": "telegram:1"}, headers=AUTH
    ).json()
    assert [r["text"] for r in body["reminders"]] == ["mine"]


def test_claiming_is_idempotent(client, reminders) -> None:
    """Two pollers must not both fire the same reminder."""
    item = reminders.add("s", "once", PAST)
    assert client.post(f"/reminders/{item['id']}/delivered", headers=AUTH).json() == {
        "delivered": True
    }
    assert client.post(f"/reminders/{item['id']}/delivered", headers=AUTH).json() == {
        "delivered": False
    }


def test_reminder_routes_are_guarded(client, reminders) -> None:
    assert client.get("/reminders/due").status_code == 401
    assert client.post("/reminders/1/delivered").status_code == 401


def test_memory_can_be_read_and_pruned_by_hand(client, memory) -> None:
    """The store is meant to be human-correctable."""
    memory.add("Allergic to shellfish")
    assert len(client.get("/memory", headers=AUTH).json()["facts"]) == 1

    assert client.delete("/memory/1", headers=AUTH).status_code == 200
    assert client.get("/memory", headers=AUTH).json()["facts"] == []
    assert client.delete("/memory/1", headers=AUTH).status_code == 404


def test_memory_routes_are_guarded(client) -> None:
    assert client.get("/memory").status_code == 401
    assert client.delete("/memory/1").status_code == 401


# ------------------------------------------------------------ bot delivery


class Fakes:
    def __init__(self, app) -> None:
        self.app = app
        self.sent: list[dict[str, Any]] = []

    def telegram(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.rsplit("/", 1)[-1] == "sendMessage":
            self.sent.append(json.loads(request.read()))
        return httpx.Response(200, json={"ok": True, "result": {}})

    def clients(self) -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
        return (
            httpx.AsyncClient(transport=httpx.MockTransport(self.telegram)),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url="http://server"
            ),
        )


@pytest.fixture
async def app(api: FakeAPI, store, memory, reminders):
    engine = Assistant(
        PERSONA, store=store, client=api.client(), memory=memory, reminders=reminders
    )
    application = create_app(token=TOKEN, engine=engine)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
def bot() -> TelegramBot:
    return TelegramBot("bot-token", "http://server", TOKEN, {MINE})


async def deliver(app, bot: TelegramBot) -> Fakes:
    fakes = Fakes(app)
    tg, api = fakes.clients()
    async with tg, api:
        await bot._deliver_reminders(tg, api)
    return fakes


async def test_a_due_reminder_reaches_the_user(app, bot, reminders) -> None:
    reminders.add(f"telegram:{MINE}", "call the dentist", PAST)
    fakes = await deliver(app, bot)

    assert [m["text"] for m in fakes.sent] == ["call the dentist"]
    assert fakes.sent[0]["chat_id"] == MINE


async def test_nothing_is_sent_before_it_is_due(app, bot, reminders) -> None:
    reminders.add(f"telegram:{MINE}", "later", FUTURE)
    assert (await deliver(app, bot)).sent == []


async def test_a_reminder_fires_exactly_once(app, bot, reminders) -> None:
    reminders.add(f"telegram:{MINE}", "once", PAST)
    assert len((await deliver(app, bot)).sent) == 1
    assert (await deliver(app, bot)).sent == [], "second poll must not repeat it"


async def test_only_allowed_chats_are_polled(app, bot, reminders) -> None:
    """A reminder on a session the bot doesn't own must not leak to it."""
    reminders.add("telegram:9999", "not yours", PAST)
    assert (await deliver(app, bot)).sent == []


async def test_delivery_survives_an_unreachable_service(bot, reminders) -> None:
    """A dead service must not take the polling loop down with it."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fakes = Fakes(None)
    tg = httpx.AsyncClient(transport=httpx.MockTransport(fakes.telegram))
    api = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    async with tg, api:
        await bot._deliver_reminders(tg, api)  # must not raise
    assert fakes.sent == []
