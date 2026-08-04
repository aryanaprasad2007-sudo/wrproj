"""The brain. Everything that talks to the model lives here.

Both the terminal loop and the HTTP service drive this class, so the persona,
history handling and caching strategy exist in exactly one place — she behaves
the same whether you type at her or message her from your phone.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any, AsyncIterator

import anthropic

from .emotions import EmotionStripper
from .persona import DEFAULT_PERSONA, Persona, load
from .store import ConversationStore

Event = dict[str, Any]


class Assistant:
    def __init__(
        self,
        persona_path: str | Path = DEFAULT_PERSONA,
        store: ConversationStore | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.client = client or anthropic.AsyncAnthropic()
        self.persona: Persona = load(persona_path)
        self.store = store or ConversationStore()
        # One lock per session: two messages arriving at once (easy to do from
        # a phone) would otherwise interleave writes and corrupt the history.
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ------------------------------------------------------------- lifecycle

    def reload(self, persona_path: str | Path | None = None) -> Persona:
        self.persona = load(persona_path or self.persona.path or DEFAULT_PERSONA)
        return self.persona

    def history(self, session_id: str) -> list[dict[str, Any]]:
        return self.store.get(session_id)

    def clear(self, session_id: str) -> None:
        self.store.clear(session_id)

    async def aclose(self) -> None:
        await self.client.close()

    # ---------------------------------------------------------------- speech

    async def send(self, session_id: str, text: str) -> Event:
        """Full turn, no streaming. Returns the terminal `done` or `error` event."""
        final: Event = {"type": "error", "message": "no response"}
        async for event in self.stream(session_id, text):
            if event["type"] in ("done", "error"):
                final = event
        return final

    async def stream(
        self, session_id: str, text: str | None, regenerate: bool = False
    ) -> AsyncIterator[Event]:
        """Drive one turn.

        Yields `{"type": "delta", "text": ...}` as the reply arrives, then
        exactly one `done` or `error`. Pass `regenerate=True` with no text to
        re-roll the previous reply.
        """
        async with self._locks[session_id]:
            history = self.store.get(session_id)

            if regenerate:
                if len(history) < 1:
                    yield {"type": "error", "message": "nothing to regenerate"}
                    return
                if history[-1]["role"] == "assistant":
                    history.pop()
            elif text:
                history.append({"role": "user", "content": text})
            else:
                yield {"type": "error", "message": "no message"}
                return

            stripper = EmotionStripper()
            parts: list[str] = []

            try:
                async with self.client.messages.stream(
                    model=self.persona.model,
                    max_tokens=self.persona.max_tokens,
                    system=self._system(),
                    thinking=self.persona.thinking_param,
                    output_config={"effort": self.persona.effort},
                    messages=self._messages(history),
                ) as stream:
                    async for delta in stream.text_stream:
                        visible = stripper.feed(delta)
                        if visible:
                            parts.append(visible)
                            yield {"type": "delta", "text": visible}

                    tail = stripper.flush()
                    if tail:
                        parts.append(tail)
                        yield {"type": "delta", "text": tail}

                    final = await stream.get_final_message()
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

            if final.stop_reason == "refusal":
                self.store.set(session_id, history)
                yield {"type": "error", "message": "response was declined"}
                return

            body = "".join(parts).strip()
            stored = f"[{stripper.tag}] {body}" if stripper.tag else body
            history.append({"role": "assistant", "content": stored})
            self.store.set(session_id, history)

            yield {
                "type": "done",
                "text": body,
                "tag": stripper.tag,
                "usage": {
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                    "cache_read_input_tokens": final.usage.cache_read_input_tokens,
                },
            }

    # --------------------------------------------------------------- request

    def _system(self) -> list[dict[str, Any]]:
        block: dict[str, Any] = {"type": "text", "text": self.persona.system}
        # If there are no examples the system prompt is the whole stable prefix,
        # so the breakpoint belongs here instead.
        if not self.persona.few_shot:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def _messages(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Few-shot examples then live conversation, with two cache breakpoints.

        The first sits at the end of the stable prefix; the second rides the last
        turn so history accrues cache hits as the conversation grows.
        """
        messages = [dict(m) for m in self.persona.few_shot]
        if messages:
            messages[-1] = with_cache(messages[-1])

        messages += [dict(m) for m in history]
        if history:
            messages[-1] = with_cache(messages[-1])
        return messages


def with_cache(message: dict[str, Any]) -> dict[str, Any]:
    """Attach a cache breakpoint to a message's final content block."""
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    else:
        content = [dict(b) for b in content]
    content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    return {**message, "content": content}
