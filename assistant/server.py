"""HTTP service wrapping the assistant.

One brain, many thin clients. The Telegram bot talks to this; the desktop voice
client in phase 2/3 will talk to the same endpoints. Persona, memory and (later)
tools live here and nowhere else, so she's the same entity on every surface.
"""

from __future__ import annotations

import json
import os
from base64 import b64decode, b64encode
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .engine import Assistant
from .persona import DEFAULT_PERSONA
from .store import ConversationStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = ROOT / "data" / "conversations.json"


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    regenerate: bool = False


class ConverseRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    # base64 16-bit mono PCM. ~30s of 16kHz speech is a little under 1.3MB
    # encoded; the cap stops a runaway client sending unbounded audio.
    audio: str = Field(min_length=1, max_length=8_000_000)


def _token() -> str:
    token = os.environ.get("ASSISTANT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "ASSISTANT_TOKEN is not set. This service exposes your assistant and "
            "your API spend, so it refuses to start without a shared secret. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    return token


def require_auth(request: Request) -> None:
    expected = request.app.state.token
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else ""
    # Constant-time compare: this endpoint is reachable by anything that can
    # route to the host, so a timing oracle on the token is worth closing.
    if not _constant_time_eq(supplied, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def _constant_time_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode(), b.encode())


def create_app(
    persona_path: str | Path | None = None,
    store_path: str | Path | None = None,
    token: str | None = None,
    engine: Assistant | None = None,
) -> FastAPI:
    """Build the app. Pass `engine` to supply a pre-built brain (used by tests).

    Config is resolved here rather than in the lifespan so a missing token fails
    with a readable message at construction, instead of a startup traceback.
    """
    resolved_token = token or _token()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine or Assistant(
            persona_path or os.environ.get("PERSONA_PATH") or DEFAULT_PERSONA,
            store=ConversationStore(
                Path(store_path or os.environ.get("ASSISTANT_STORE") or DEFAULT_STORE),
                max_turns=int(os.environ.get("ASSISTANT_MAX_TURNS", "40")),
            ),
        )
        try:
            yield
        finally:
            await app.state.engine.aclose()

    app = FastAPI(title="assistant", lifespan=lifespan)
    app.state.token = resolved_token

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        """Unauthenticated on purpose — it leaks nothing and makes probes easy."""
        persona = request.app.state.engine.persona
        return {
            "status": "ok",
            "persona": persona.name,
            "model": persona.model,
            "effort": persona.effort,
        }

    @app.post("/chat", dependencies=[Depends(require_auth)])
    async def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
        engine: Assistant = request.app.state.engine
        event = await engine.send(body.session_id, body.message)
        if event["type"] == "error":
            raise HTTPException(status_code=502, detail=event["message"])
        return event

    @app.post("/chat/stream", dependencies=[Depends(require_auth)])
    async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
        engine: Assistant = request.app.state.engine

        async def events() -> AsyncIterator[str]:
            async for event in engine.stream(
                body.session_id,
                None if body.regenerate else body.message,
                regenerate=body.regenerate,
            ):
                yield f"data: {json.dumps(event)}\n\n"
                if await request.is_disconnected():
                    break

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/chat/voice", dependencies=[Depends(require_auth)])
    async def chat_voice(body: ChatRequest, request: Request) -> StreamingResponse:
        """Text and audio for one turn, interleaved on a single stream.

        One stream rather than a text call plus a speech call: it keeps the two
        in sync for display, and avoids paying for the model turn twice. PCM is
        base64'd to ride inside SSE — a third of overhead, which costs nothing
        over loopback and keeps the client trivial.
        """
        engine: Assistant = request.app.state.engine

        async def events() -> AsyncIterator[str]:
            async for event in engine.speak(
                body.session_id,
                None if body.regenerate else body.message,
                regenerate=body.regenerate,
            ):
                if event["type"] == "audio":
                    event = {"type": "audio", "pcm": b64encode(event["pcm"]).decode()}
                yield f"data: {json.dumps(event)}\n\n"
                if await request.is_disconnected():
                    break

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/converse", dependencies=[Depends(require_auth)])
    async def converse(body: ConverseRequest, request: Request) -> StreamingResponse:
        """A spoken turn: PCM up, transcript and spoken reply back on one stream.

        Transcription lives here rather than in the client so the recogniser is
        configured once, alongside the persona. Voice activity detection stays
        client-side — it has to, since barge-in cannot afford a round trip.
        """
        engine: Assistant = request.app.state.engine

        try:
            pcm = b64decode(body.audio, validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail="audio is not valid base64")

        async def events() -> AsyncIterator[str]:
            async for event in engine.converse(body.session_id, pcm):
                if event["type"] == "audio":
                    event = {"type": "audio", "pcm": b64encode(event["pcm"]).decode()}
                yield f"data: {json.dumps(event)}\n\n"
                if await request.is_disconnected():
                    break

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/sessions/{session_id}/clear", dependencies=[Depends(require_auth)])
    async def clear(session_id: str, request: Request) -> dict[str, str]:
        request.app.state.engine.clear(session_id)
        return {"status": "cleared", "session_id": session_id}

    @app.post("/persona/reload", dependencies=[Depends(require_auth)])
    async def reload(request: Request) -> dict[str, str]:
        try:
            persona = request.app.state.engine.reload()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"reload failed: {exc}")
        return {"status": "reloaded", "persona": persona.name}

    return app
