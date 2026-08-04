#!/usr/bin/env python3
"""Desktop voice client — type at her, hear her answer.

    python run_voice.py

Needs the service (run_server.py) running. The microphone side arrives in
phase 3; this is the output half.
"""

import asyncio
import os
import sys
from contextlib import AsyncExitStack

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import httpx

from assistant.avatar import AvatarLink
from assistant.voice_client import VoiceClient, default_player

SESSION = "desktop"
_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


async def run(url: str, token: str) -> None:
    client = VoiceClient(url, token)
    player, note = default_player()
    if note:
        print(_c("2", f"  {note}"))

    async with httpx.AsyncClient() as http:
        try:
            health = await http.get(f"{url}/health", timeout=10.0)
            name = health.json().get("persona", "assistant")
        except httpx.HTTPError:
            print(_c("31", f"  can't reach the service at {url} — is run_server.py up?"))
            return

        print(_c("1", f"\n  {name}") + _c("2", "  ·  /quit to exit, /regen to re-roll\n"))

        async with AsyncExitStack() as stack:
            avatar = None
            if os.environ.get("AVATAR", "1") != "0":
                # Costs two small posts a turn when nobody has the page open.
                avatar = await stack.enter_async_context(AvatarLink(url, token, http))

            while True:
                try:
                    line = (await asyncio.to_thread(input, _c("36", "you> "))).strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if not line:
                    continue
                if line in ("/quit", "/exit", "/q"):
                    return

                regenerate = line == "/regen"
                first = True

                def show(text: str) -> None:
                    nonlocal first
                    if first:
                        print(_c("1", f"\n{name.lower()}> "), end="", flush=True)
                        first = False
                    print(text, end=" ", flush=True)

                result = await client.say(
                    http,
                    SESSION,
                    line,
                    player,
                    on_text=show,
                    regenerate=regenerate,
                    avatar=avatar,
                )
                print()

                if result["type"] == "error":
                    print(_c("31", f"  {result['message']}"))
                if result.get("audio_note"):
                    print(_c("2", f"  wrote {result['audio_note']}"))
                print()


def main() -> int:
    token = os.environ.get("ASSISTANT_TOKEN", "").strip()
    if not token:
        print("ASSISTANT_TOKEN is not set — it must match the service.")
        return 1
    url = os.environ.get("ASSISTANT_URL", "http://127.0.0.1:8000")
    try:
        asyncio.run(run(url, token))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
