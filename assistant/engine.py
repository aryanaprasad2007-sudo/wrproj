"""The brain. Everything that talks to the model lives here.

Both the terminal loop and the HTTP service drive this class, so the persona,
history handling, tools and caching strategy exist in exactly one place — she
behaves the same whether you type at her or message her from your phone.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import anthropic

from .chunker import SentenceChunker
from .emotions import EmotionStripper
from .memory import MemoryStore
from .persona import DEFAULT_PERSONA, Persona, load
from .reminders import ReminderStore
from .store import ConversationStore
from .stt import STTEngine
from .stt import from_config as stt_from_config
from .tools import MAX_TOOL_ROUNDS, Toolbox
from .tools import build as build_toolbox
from .tts import TTSEngine
from .tts import from_config as tts_from_config

Event = dict[str, Any]


class Assistant:
    def __init__(
        self,
        persona_path: str | Path = DEFAULT_PERSONA,
        store: ConversationStore | None = None,
        client: anthropic.AsyncAnthropic | None = None,
        tts: TTSEngine | None = None,
        stt: STTEngine | None = None,
        memory: MemoryStore | None = None,
        reminders: ReminderStore | None = None,
    ) -> None:
        self.client = client or anthropic.AsyncAnthropic()
        self.persona: Persona = load(persona_path)
        self.store = store or ConversationStore()
        self.memory = memory or MemoryStore()
        self.reminders = reminders or ReminderStore()
        self._tts = tts
        self._stt = stt
        self._toolbox: Toolbox | None = None
        # Flipped permanently if the model rejects a mid-conversation system
        # message. See _context_block for why that channel is preferred.
        self._context_inline = False
        # One lock per session: two messages arriving at once (easy to do from
        # a phone) would otherwise interleave writes and corrupt the history.
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ------------------------------------------------------------- lifecycle

    def reload(self, persona_path: str | Path | None = None) -> Persona:
        voice, stt, tools = self.persona.voice, self.persona.stt, self.persona.tools
        self.persona = load(persona_path or self.persona.path or DEFAULT_PERSONA)
        # Rebuild an engine only if its config actually changed — loading a TTS
        # or Whisper model is slow, and a reload is usually just a tone tweak.
        if self._tts is not None and self.persona.voice != voice:
            self._tts = None
        if self._stt is not None and self.persona.stt != stt:
            self._stt = None
        if self.persona.tools != tools:
            self._toolbox = None
        return self.persona

    @property
    def tts(self) -> TTSEngine:
        """Built on first use so a text-only deployment never loads an engine."""
        if self._tts is None:
            self._tts = tts_from_config(self.persona.voice)
        return self._tts

    @property
    def stt(self) -> STTEngine:
        if self._stt is None:
            self._stt = stt_from_config(self.persona.stt)
        return self._stt

    @property
    def toolbox(self) -> Toolbox:
        if self._toolbox is None:
            self._toolbox = build_toolbox(self.persona.tools, self.memory, self.reminders)
        return self._toolbox

    def history(self, session_id: str) -> list[dict[str, Any]]:
        return self.store.get(session_id)

    def clear(self, session_id: str) -> None:
        self.store.clear(session_id)

    async def aclose(self) -> None:
        await self.client.close()
        if self._tts is not None:
            await self._tts.aclose()
        if self._stt is not None:
            await self._stt.aclose()

    # ---------------------------------------------------------------- speech

    async def send(self, session_id: str, text: str) -> Event:
        """Full turn, no streaming. Returns the terminal `done` or `error` event."""
        final: Event = {"type": "error", "message": "no response"}
        async for event in self.stream(session_id, text):
            if event["type"] in ("done", "error"):
                final = event
        return final

    async def transcribe(self, pcm: bytes) -> str:
        return await self.stt.transcribe(pcm)

    async def converse(self, session_id: str, pcm: bytes) -> AsyncIterator[Event]:
        """One spoken turn: audio in, transcript and spoken reply out."""
        try:
            transcript = await self.transcribe(pcm)
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
            return

        yield {"type": "transcript", "text": transcript}
        if not transcript.strip():
            # Silence, or a noise the recogniser couldn't make anything of.
            # Answering it would be worse than ignoring it.
            yield {"type": "done", "text": "", "tag": None, "usage": {}, "skipped": True}
            return

        async for event in self.speak(session_id, transcript):
            yield event

    async def speak(
        self, session_id: str, text: str | None, regenerate: bool = False
    ) -> AsyncIterator[Event]:
        """Drive one turn and synthesise it as she goes.

        Text is cut into speakable chunks the moment each one is complete and
        synthesised immediately, so the first sound arrives while the model is
        still writing the rest of the reply.
        """
        engine = self.tts
        yield {"type": "start", "engine": engine.name, "format": engine.format.as_dict()}

        chunker = SentenceChunker()

        async def voice(chunk: str) -> AsyncIterator[Event]:
            yield {"type": "text", "text": chunk}
            async for pcm in engine.synthesize(chunk):
                yield {"type": "audio", "pcm": pcm}

        async for event in self.stream(session_id, text, regenerate=regenerate):
            if event["type"] == "delta":
                for chunk in chunker.feed(event["text"]):
                    async for out in voice(chunk):
                        yield out
            elif event["type"] == "done":
                tail = chunker.flush()
                if tail:
                    async for out in voice(tail):
                        yield out
                yield event
            else:
                # `tag`, `tool_use`, `tool_result` pass through; `error` ends it.
                yield event
                if event["type"] == "error":
                    return

    # ----------------------------------------------------------------- turns

    async def stream(
        self, session_id: str, text: str | None, regenerate: bool = False
    ) -> AsyncIterator[Event]:
        """Drive one turn, including any tool rounds it needs.

        Yields `delta` text as it arrives, `tool_use`/`tool_result` around each
        call, and exactly one `done` or `error`. Pass `regenerate=True` with no
        text to re-roll the previous reply.
        """
        async with self._locks[session_id]:
            history = self.store.get(session_id)

            if regenerate:
                if not _rewind(history):
                    yield {"type": "error", "message": "nothing to regenerate"}
                    return
            elif text:
                history.append({"role": "user", "content": text})
            else:
                yield {"type": "error", "message": "no message"}
                return

            stripper = EmotionStripper()
            parts: list[str] = []
            announced_tag = False
            rounds = 0
            usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}

            while True:
                try:
                    async with self.client.messages.stream(
                        **self._request(history)
                    ) as stream:
                        async for delta in stream.text_stream:
                            visible = stripper.feed(delta)
                            # Announce the emotion as soon as it's parsed: the
                            # voice client wants it while she is still speaking.
                            if stripper.tag and not announced_tag:
                                announced_tag = True
                                yield {"type": "tag", "tag": stripper.tag}
                            if visible:
                                parts.append(visible)
                                yield {"type": "delta", "text": visible}

                        # Deliberately not flushed here. A round that only calls
                        # a tool produces no text, and flushing would mark the
                        # tag resolved before any arrived — so the next round's
                        # "[bored] ..." would be spoken with the tag in it.
                        final = await stream.get_final_message()
                except anthropic.BadRequestError as exc:
                    if self._downgrade_context(exc):
                        continue  # same round, context moved into the system prompt
                    self.store.set(session_id, history)
                    yield {"type": "error", "message": f"api error 400: {exc.message}"}
                    return
                except anthropic.RateLimitError:
                    # The user turn stays in history so a retry doesn't lose it.
                    self.store.set(session_id, history)
                    yield {"type": "error", "message": "rate limited — try again shortly"}
                    return
                except anthropic.APIStatusError as exc:
                    self.store.set(session_id, history)
                    yield {"type": "error", "message": f"api error {exc.status_code}"}
                    return
                except anthropic.APIConnectionError:
                    self.store.set(session_id, history)
                    yield {"type": "error", "message": "could not reach the api"}
                    return

                for key in usage:
                    usage[key] += getattr(final.usage, key, 0) or 0

                if final.stop_reason == "refusal":
                    self.store.set(session_id, history)
                    yield {"type": "error", "message": "response was declined"}
                    return

                history.append({"role": "assistant", "content": _dump(final.content)})

                # A server-side tool ran out of its own iteration budget; re-send
                # to let it carry on. No client work to do.
                if final.stop_reason == "pause_turn":
                    rounds += 1
                    if rounds > MAX_TOOL_ROUNDS:
                        break
                    continue

                calls = [b for b in final.content if getattr(b, "type", None) == "tool_use"]
                if not calls:
                    break

                rounds += 1
                if rounds > MAX_TOOL_ROUNDS:
                    yield {
                        "type": "error",
                        "message": f"gave up after {MAX_TOOL_ROUNDS} tool rounds",
                    }
                    self.store.set(session_id, history)
                    return

                results = []
                for call in calls:
                    yield {"type": "tool_use", "name": call.name, "input": call.input}
                    output, failed = await self.toolbox.run(
                        call.name, dict(call.input or {}), session_id
                    )
                    yield {"type": "tool_result", "name": call.name, "is_error": failed}
                    block: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": output,
                    }
                    if failed:
                        block["is_error"] = True
                    results.append(block)

                # All results go back in one user message — splitting them
                # trains the model out of calling tools in parallel.
                history.append({"role": "user", "content": results})

            # The turn is over, so release anything the tag parser was holding.
            tail = stripper.flush()
            if tail:
                parts.append(tail)
                yield {"type": "delta", "text": tail}

            body = "".join(parts).strip()
            self.store.set(session_id, history)

            yield {
                "type": "done",
                "text": body,
                "tag": stripper.tag,
                "usage": usage,
                "tool_rounds": rounds,
            }

    # --------------------------------------------------------------- request

    def _request(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.persona.model,
            "max_tokens": self.persona.max_tokens,
            "system": self._system(),
            "thinking": self.persona.thinking_param,
            "output_config": {"effort": self.persona.effort},
            "messages": self._messages(history),
        }
        if self.toolbox:
            request["tools"] = self.toolbox.definitions()
        return request

    def _system(self) -> list[dict[str, Any]]:
        block: dict[str, Any] = {"type": "text", "text": self.persona.system}
        # If there are no examples the system prompt is the whole stable prefix,
        # so the breakpoint belongs here instead.
        if not self.persona.few_shot:
            block["cache_control"] = {"type": "ephemeral"}
        blocks = [block]
        if self._context_inline:
            blocks.append({"type": "text", "text": self._context_block()})
        return blocks

    def _context_block(self) -> str:
        """Volatile context: the time, and what she remembers.

        The clock changes on every request and memories change whenever she
        learns something, so this must sit *after* everything cached. Put it in
        the system prompt proper and every request reprocesses the persona, the
        examples and the entire conversation history.
        """
        lines = [
            "# Current context",
            "",
            f"The time is {datetime.now().astimezone().isoformat(timespec='seconds')}.",
        ]
        remembered = self.memory.as_prompt()
        if remembered:
            lines += [
                "",
                "What you know about them, from previous conversations. Use it "
                "without announcing that you are using it, and never recite the "
                "list back at them.",
                "",
                remembered,
            ]
        return "\n".join(lines)

    def _messages(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Few-shot examples, live conversation, then volatile context.

        Two cache breakpoints: one at the end of the stable prefix, one riding
        the last turn so history accrues hits as the conversation grows. The
        context message goes after both, where changing it costs nothing.
        """
        messages = [dict(m) for m in self.persona.few_shot]
        if messages:
            messages[-1] = with_cache(messages[-1])

        messages += [dict(m) for m in history]
        # Only breakpoint a plain text turn — a trailing thinking or tool_use
        # block is not somewhere a cache marker belongs.
        if history and isinstance(messages[-1].get("content"), str):
            messages[-1] = with_cache(messages[-1])

        if not self._context_inline:
            messages.append({"role": "system", "content": self._context_block()})
        return messages

    def _downgrade_context(self, exc: anthropic.BadRequestError) -> bool:
        """Move volatile context into the system prompt on models without the
        mid-conversation system role, and report whether to retry."""
        if self._context_inline:
            return False
        message = str(getattr(exc, "message", exc)).lower()
        if "system" not in message or "role" not in message:
            return False
        self._context_inline = True
        return True


def _dump(content: Any) -> list[dict[str, Any]]:
    """Response blocks as plain JSON, for storage and for echoing back.

    Thinking and server-tool blocks have to survive this round trip intact or
    the next request is rejected, so nothing is filtered out by type.
    """
    return [
        b.model_dump(mode="json", exclude_none=True) if hasattr(b, "model_dump") else dict(b)
        for b in content
    ]


def _rewind(history: list[dict[str, Any]]) -> bool:
    """Drop everything after the last real user turn, ready to re-roll it.

    A turn that used tools leaves assistant and tool_result messages behind;
    popping only the last one would strand a tool result with no call.
    """
    while history and not (
        history[-1]["role"] == "user" and isinstance(history[-1].get("content"), str)
    ):
        history.pop()
    return bool(history)


def with_cache(message: dict[str, Any]) -> dict[str, Any]:
    """Attach a cache breakpoint to a message's final content block."""
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    else:
        content = [dict(b) for b in content]
    content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    return {**message, "content": content}
