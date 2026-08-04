"""Telegram bot — the phone client.

A thin client of the HTTP service, not a second copy of the brain. Uses long
polling rather than webhooks so it runs on a laptop or home box with no public
HTTPS endpoint and no port forwarding.

Anyone who finds the bot's username can message it, so an explicit chat-id
allowlist is mandatory. With no allowlist configured the bot answers nobody and
logs the id of whoever wrote, so you can add your own.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("assistant.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_LIMIT = 4096
POLL_TIMEOUT = 30

HELP = (
    "Just talk to me.\n\n"
    "/clear — forget this conversation\n"
    "/reload — re-read the persona file\n"
    "/help — this"
)


class TelegramBot:
    def __init__(
        self,
        bot_token: str,
        server_url: str,
        server_token: str,
        allowed_chat_ids: set[int],
    ) -> None:
        self.bot_token = bot_token
        self.server_url = server_url.rstrip("/")
        self.server_token = server_token
        self.allowed = allowed_chat_ids
        self._offset: int | None = None

    # ------------------------------------------------------------- telegram

    async def _call(self, client: httpx.AsyncClient, method: str, **params: Any) -> Any:
        resp = await client.post(
            API.format(token=self.bot_token, method=method), json=params
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"telegram {method} failed: {payload.get('description')}")
        return payload.get("result")

    async def _send(self, client: httpx.AsyncClient, chat_id: int, text: str) -> None:
        # Persona forbids markdown, so send as plain text — no parse_mode. That
        # also means a stray underscore or asterisk can't break the send.
        for chunk in _split(text):
            await self._call(client, "sendMessage", chat_id=chat_id, text=chunk)

    async def _typing(self, client: httpx.AsyncClient, chat_id: int) -> None:
        try:
            await self._call(client, "sendChatAction", chat_id=chat_id, action="typing")
        except Exception:
            pass  # cosmetic only — never let it block a reply

    # --------------------------------------------------------------- server

    async def _ask(self, client: httpx.AsyncClient, chat_id: int, text: str) -> str:
        resp = await client.post(
            f"{self.server_url}/chat",
            headers={"Authorization": f"Bearer {self.server_token}"},
            json={"session_id": f"telegram:{chat_id}", "message": text},
            timeout=180.0,
        )
        if resp.status_code == 401:
            log.error("server rejected our token — check ASSISTANT_TOKEN on both sides")
            return "I can't reach myself right now. Check the service."
        if resp.status_code != 200:
            log.error("server returned %s: %s", resp.status_code, resp.text[:300])
            return "Something went wrong on my end."
        return resp.json().get("text", "")

    async def _post(self, client: httpx.AsyncClient, path: str) -> bool:
        resp = await client.post(
            f"{self.server_url}{path}",
            headers={"Authorization": f"Bearer {self.server_token}"},
            timeout=30.0,
        )
        return resp.status_code == 200

    # ---------------------------------------------------------------- loop

    async def _handle(
        self, tg: httpx.AsyncClient, api: httpx.AsyncClient, message: dict[str, Any]
    ) -> None:
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or not text:
            return

        if chat_id not in self.allowed:
            log.warning(
                "ignored message from unauthorised chat id %s — add it to "
                "TELEGRAM_ALLOWED_CHAT_IDS if it's yours",
                chat_id,
            )
            return

        if text.startswith("/"):
            command = text.split()[0].lstrip("/").split("@")[0].lower()
            if command in ("start", "help"):
                await self._send(tg, chat_id, HELP)
                return
            if command == "clear":
                ok = await self._post(api, f"/sessions/telegram:{chat_id}/clear")
                await self._send(tg, chat_id, "Forgotten." if ok else "Couldn't clear that.")
                return
            if command == "reload":
                ok = await self._post(api, "/persona/reload")
                await self._send(tg, chat_id, "Reloaded." if ok else "Reload failed.")
                return
            # Anything else falls through and is treated as ordinary text.

        # Send the first one inline rather than from the refresh task: a fast
        # reply would otherwise cancel that task before the loop ever ran it,
        # and the indicator should appear the moment the message lands anyway.
        await self._typing(tg, chat_id)
        refresh = asyncio.create_task(self._keep_typing(tg, chat_id))
        try:
            reply = await self._ask(api, chat_id, text)
        finally:
            refresh.cancel()

        if reply:
            await self._send(tg, chat_id, reply)

    async def _keep_typing(self, client: httpx.AsyncClient, chat_id: int) -> None:
        """Telegram's typing indicator lapses after ~5s; refresh it while we wait."""
        try:
            while True:
                await asyncio.sleep(4)
                await self._typing(client, chat_id)
        except asyncio.CancelledError:
            pass

    async def _drop_backlog(self, tg: httpx.AsyncClient) -> None:
        """Skip messages sent while the bot was down.

        Waking up and answering four-hour-old questions is worse than silence.
        """
        updates = await self._call(tg, "getUpdates", offset=-1, timeout=0)
        if updates:
            self._offset = updates[-1]["update_id"] + 1
            log.info("skipped backlog up to update %s", self._offset - 1)

    async def run(self) -> None:
        log.info("polling telegram; %d chat id(s) allowed", len(self.allowed))
        if not self.allowed:
            log.warning(
                "TELEGRAM_ALLOWED_CHAT_IDS is empty — the bot will answer nobody. "
                "Message it once and add the chat id it logs."
            )

        async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 15) as tg:
            async with httpx.AsyncClient() as api:
                await self._drop_backlog(tg)
                backoff = 1.0
                while True:
                    try:
                        updates = await self._call(
                            tg, "getUpdates", offset=self._offset, timeout=POLL_TIMEOUT
                        )
                        backoff = 1.0
                    except Exception as exc:
                        log.warning("poll failed (%s); retrying in %.0fs", exc, backoff)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 60)
                        continue

                    for update in updates or []:
                        self._offset = update["update_id"] + 1
                        message = update.get("message") or update.get("edited_message")
                        if not message:
                            continue
                        try:
                            await self._handle(tg, api, message)
                        except Exception:
                            log.exception("failed handling update %s", update["update_id"])


def _split(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on paragraph, then line, then hard boundaries to fit Telegram's cap."""
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


def from_env() -> TelegramBot:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set — get one from @BotFather")

    server_token = os.environ.get("ASSISTANT_TOKEN", "").strip()
    if not server_token:
        raise RuntimeError("ASSISTANT_TOKEN is not set — it must match the service")

    return TelegramBot(
        bot_token=bot_token,
        server_url=os.environ.get("ASSISTANT_URL", "http://127.0.0.1:8000"),
        server_token=server_token,
        allowed_chat_ids=parse_chat_ids(os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")),
    )


def parse_chat_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            log.warning("ignoring non-numeric chat id %r", part)
    return ids
