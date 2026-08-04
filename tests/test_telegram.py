import json
from typing import Any

import httpx
import pytest

from assistant.telegram import TELEGRAM_LIMIT, TelegramBot, _split, parse_chat_ids

MINE = 4242
THEIRS = 9999


class Fakes:
    """Captures Telegram calls and serves canned assistant-service replies."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.actions: list[str] = []
        self.server_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.reply = "Sixty-one and overcast."
        self.server_status = 200

    def telegram(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.read())
        if method == "sendMessage":
            self.sent.append(payload)
        elif method == "sendChatAction":
            self.actions.append(payload["action"])
        return httpx.Response(200, json={"ok": True, "result": {}})

    def server(self, request: httpx.Request) -> httpx.Response:
        raw = request.read()
        self.server_calls.append(
            (request.url.path, json.loads(raw) if raw else None)
        )
        if self.server_status != 200:
            return httpx.Response(self.server_status, json={"detail": "nope"})
        return httpx.Response(200, json={"text": self.reply, "tag": "neutral"})

    def clients(self) -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
        return (
            httpx.AsyncClient(transport=httpx.MockTransport(self.telegram)),
            httpx.AsyncClient(transport=httpx.MockTransport(self.server)),
        )


@pytest.fixture
def fakes() -> Fakes:
    return Fakes()


@pytest.fixture
def bot() -> TelegramBot:
    return TelegramBot(
        bot_token="bot-token",
        server_url="http://server",
        server_token="secret",
        allowed_chat_ids={MINE},
    )


def message(text: str, chat_id: int = MINE) -> dict[str, Any]:
    return {"chat": {"id": chat_id}, "text": text}


async def handle(bot: TelegramBot, fakes: Fakes, msg: dict[str, Any]) -> None:
    tg, api = fakes.clients()
    async with tg, api:
        await bot._handle(tg, api, msg)


# ---------------------------------------------------------------- allowlist


async def test_answers_an_allowed_chat(bot, fakes) -> None:
    await handle(bot, fakes, message("what's the weather"))
    assert [m["text"] for m in fakes.sent] == ["Sixty-one and overcast."]
    assert fakes.server_calls[0][0] == "/chat"


async def test_ignores_a_stranger_entirely(bot, fakes) -> None:
    """Anyone can find the bot's username — a stranger must get nothing."""
    await handle(bot, fakes, message("hello?", chat_id=THEIRS))
    assert fakes.sent == []
    assert fakes.server_calls == []


async def test_empty_allowlist_answers_nobody(fakes) -> None:
    bot = TelegramBot("t", "http://server", "secret", allowed_chat_ids=set())
    await handle(bot, fakes, message("hello"))
    assert fakes.sent == []
    assert fakes.server_calls == []


async def test_session_id_is_scoped_per_chat(bot, fakes) -> None:
    await handle(bot, fakes, message("hi"))
    assert fakes.server_calls[0][1]["session_id"] == f"telegram:{MINE}"


async def test_ignores_non_text_messages(bot, fakes) -> None:
    await handle(bot, fakes, {"chat": {"id": MINE}})
    await handle(bot, fakes, {"text": "orphan"})
    assert fakes.server_calls == []


# ----------------------------------------------------------------- commands


@pytest.mark.parametrize("cmd", ["/start", "/help", "/help@mybot"])
async def test_help_commands_do_not_hit_the_model(bot, fakes, cmd) -> None:
    await handle(bot, fakes, message(cmd))
    assert fakes.server_calls == []
    assert "/clear" in fakes.sent[0]["text"]


async def test_clear_targets_this_chats_session(bot, fakes) -> None:
    await handle(bot, fakes, message("/clear"))
    assert fakes.server_calls[0][0] == f"/sessions/telegram:{MINE}/clear"
    assert fakes.sent[0]["text"] == "Forgotten."


async def test_reload_command(bot, fakes) -> None:
    await handle(bot, fakes, message("/reload"))
    assert fakes.server_calls[0][0] == "/persona/reload"


async def test_unknown_command_is_treated_as_speech(bot, fakes) -> None:
    """She should answer '/whatever' rather than silently dropping it."""
    await handle(bot, fakes, message("/whatever"))
    assert fakes.server_calls[0][0] == "/chat"
    assert fakes.server_calls[0][1]["message"] == "/whatever"


# ------------------------------------------------------------------ failures


async def test_server_error_gets_a_human_reply(bot, fakes) -> None:
    fakes.server_status = 500
    await handle(bot, fakes, message("hi"))
    assert fakes.sent and "wrong" in fakes.sent[0]["text"].lower()


async def test_bad_token_is_reported_not_swallowed(bot, fakes) -> None:
    fakes.server_status = 401
    await handle(bot, fakes, message("hi"))
    assert fakes.sent and fakes.sent[0]["text"]


async def test_typing_indicator_is_sent(bot, fakes) -> None:
    await handle(bot, fakes, message("hi"))
    assert "typing" in fakes.actions


async def test_plain_text_only_no_parse_mode(bot, fakes) -> None:
    """Persona forbids markdown; a stray _ or * must not break the send."""
    fakes.reply = "Use snake_case, not *that*."
    await handle(bot, fakes, message("hi"))
    assert "parse_mode" not in fakes.sent[0]
    assert fakes.sent[0]["text"] == "Use snake_case, not *that*."


# -------------------------------------------------------------- chunking


def test_short_text_is_one_chunk() -> None:
    assert _split("hello") == ["hello"]


def test_empty_text_sends_nothing() -> None:
    assert _split("   ") == []


def test_long_text_respects_the_limit() -> None:
    chunks = _split(" ".join(["word"] * 3000))
    assert len(chunks) > 1
    assert all(len(c) <= TELEGRAM_LIMIT for c in chunks)
    assert "".join(c.replace(" ", "") for c in chunks) == "word" * 3000


def test_unbroken_run_is_hard_split() -> None:
    chunks = _split("x" * (TELEGRAM_LIMIT * 2 + 5))
    assert all(len(c) <= TELEGRAM_LIMIT for c in chunks)
    assert sum(len(c) for c in chunks) == TELEGRAM_LIMIT * 2 + 5


def test_prefers_paragraph_breaks() -> None:
    text = ("a" * 2000) + "\n\n" + ("b" * 2500)
    assert _split(text) == ["a" * 2000, "b" * 2500]


async def test_long_reply_is_sent_as_several_messages(bot, fakes) -> None:
    fakes.reply = " ".join(["word"] * 3000)
    await handle(bot, fakes, message("hi"))
    assert len(fakes.sent) > 1


# ------------------------------------------------------------- chat id parsing


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", set()),
        ("123", {123}),
        ("123,456", {123, 456}),
        (" 123 , 456 ", {123, 456}),
        ("-1001234567890", {-1001234567890}),  # group chats are negative
        ("123,junk,456", {123, 456}),
        ("123,123", {123}),
    ],
)
def test_parse_chat_ids(raw, expected) -> None:
    assert parse_chat_ids(raw) == expected
