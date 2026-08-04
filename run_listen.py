#!/usr/bin/env python3
"""Full voice conversation — talk to her, she talks back.

    python run_listen.py

Needs the service (run_server.py) running, a microphone, and a Whisper model
(downloads once on first use).

Wear headphones. Without acoustic echo cancellation the microphone hears her
own voice through speakers and reads it as you interrupting, so she cuts
herself off mid-sentence, repeatedly. Set BARGE_IN=0 to disable interruption
if you have to use speakers.
"""

import asyncio
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import httpx

from assistant.audio import Microphone, Segmenter, SegmenterConfig, WebrtcVAD
from assistant.conversation import Conversation
from assistant.voice_client import VoiceClient, default_player

_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


async def run(url: str, token: str) -> None:
    if not Microphone.available():
        print(_c("31", "  no microphone found"))
        return

    player, note = default_player()
    if note:
        print(_c("2", f"  {note}"))

    config = SegmenterConfig(
        end_silence_ms=int(os.environ.get("END_SILENCE_MS", "600")),
        pre_roll_ms=int(os.environ.get("PRE_ROLL_MS", "300")),
    )
    mic = Microphone(sample_rate=config.sample_rate, frame_ms=config.frame_ms)
    segmenter = Segmenter(
        WebrtcVAD(int(os.environ.get("VAD_AGGRESSIVENESS", "2"))), config
    )
    barge_in = os.environ.get("BARGE_IN", "1") != "0"

    async with httpx.AsyncClient() as http:
        try:
            health = await http.get(f"{url}/health", timeout=10.0)
            name = health.json().get("persona", "assistant")
        except httpx.HTTPError:
            print(_c("31", f"  can't reach the service at {url} — is run_server.py up?"))
            return

        print(_c("1", f"\n  {name}") + _c("2", "  ·  just talk. ctrl-c to stop."))
        print(
            _c(
                "2",
                f"  endpoint silence {config.end_silence_ms}ms · "
                f"barge-in {'on' if barge_in else 'off'}\n",
            )
        )

        state = {"labelled": False}

        def show(event: dict) -> None:
            kind = event["type"]
            if kind == "transcript":
                text = event["text"].strip()
                print(_c("36", f"you> ") + (text or _c("2", "(nothing heard)")))
                state["labelled"] = False
            elif kind == "text":
                if not state["labelled"]:
                    print(_c("1", f"{name.lower()}> "), end="", flush=True)
                    state["labelled"] = True
                print(event["text"], end=" ", flush=True)
            elif kind == "interrupted":
                print(_c("2", "  [cut off]\n"))
            elif kind == "error":
                print(_c("31", f"\n  {event['message']}\n"))
            elif kind == "done" and state["labelled"]:
                print("\n")

        conversation = Conversation(
            VoiceClient(url, token), mic, segmenter, player, barge_in=barge_in
        )
        await conversation.run(http, on_event=show)


def main() -> int:
    token = os.environ.get("ASSISTANT_TOKEN", "").strip()
    if not token:
        print("ASSISTANT_TOKEN is not set — it must match the service.")
        return 1
    url = os.environ.get("ASSISTANT_URL", "http://127.0.0.1:8000")
    try:
        asyncio.run(run(url, token))
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
