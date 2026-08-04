"""HTTP service wrapping the assistant.

One brain, many thin clients. The Telegram bot talks to this; the desktop voice
client in phase 2/3 will talk to the same endpoints. Persona, memory and (later)
tools live here and nowhere else, so she's the same entity on every surface.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from base64 import b64decode, b64encode
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .avatar import AvatarBus
from .engine import Assistant
from .memory import MemoryStore
from .persona import DEFAULT_PERSONA
from .reminders import ReminderStore
from .store import ConversationStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = ROOT / "data" / "conversations.json"
AVATAR_PAGE = Path(__file__).resolve().parent / "web" / "avatar.html"

# Long enough to open a socket, short enough that a leaked one is worthless.
TICKET_TTL = 60.0


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    regenerate: bool = False


class AvatarEvent(BaseModel):
    """What a playing client is allowed to put on the bus.

    Only the two things it actually knows: whether sound is coming out of the
    speakers right now, and how far open her mouth should be while it does.
    Expression and dialogue come from the engine, which is the only thing that
    knows them.
    """

    type: Literal["mouth", "state"]
    state: Literal["idle", "thinking", "speaking"] | None = None
    frame_ms: int | None = Field(default=None, ge=10, le=250)
    # A cap, not a budget: ~80s of frames, far more than one chunk of speech.
    open: list[float] | None = Field(default=None, max_length=2000)


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


def _bearer(header: str) -> str:
    return header[7:] if header.lower().startswith("bearer ") else ""


def _issue_ticket(app: FastAPI) -> str:
    """A single-use, short-lived stand-in for the token, for the avatar socket.

    Browsers can't set headers on a WebSocket, and the usual answer — putting
    the token in the query string — writes your long-lived secret into the URL
    bar, the history, and every access log that sees the request. This is the
    cheap fix: exchange the token for something that expires in a minute and
    only works once.
    """
    now = time.monotonic()
    tickets: dict[str, float] = app.state.tickets
    for issued, expiry in list(tickets.items()):
        if expiry <= now:
            del tickets[issued]
    ticket = secrets.token_urlsafe(24)
    tickets[ticket] = now + TICKET_TTL
    return ticket


def _redeem_ticket(app: FastAPI, ticket: str) -> bool:
    expiry = app.state.tickets.pop(ticket, None)
    return expiry is not None and expiry > time.monotonic()


def _websocket_authorized(websocket: WebSocket) -> bool:
    app = websocket.app
    supplied = _bearer(websocket.headers.get("authorization", ""))
    if supplied:
        return _constant_time_eq(supplied, app.state.token)
    ticket = websocket.query_params.get("ticket", "")
    return bool(ticket) and _redeem_ticket(app, ticket)


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
        data = Path(os.environ.get("ASSISTANT_DATA") or ROOT / "data")
        app.state.engine = engine or Assistant(
            persona_path or os.environ.get("PERSONA_PATH") or DEFAULT_PERSONA,
            store=ConversationStore(
                Path(store_path or os.environ.get("ASSISTANT_STORE") or DEFAULT_STORE),
                max_turns=int(os.environ.get("ASSISTANT_MAX_TURNS", "40")),
            ),
            memory=MemoryStore(data / "memory.json"),
            reminders=ReminderStore(data / "reminders.json"),
        )
        try:
            yield
        finally:
            await app.state.engine.aclose()

    app = FastAPI(title="assistant", lifespan=lifespan)
    app.state.token = resolved_token
    app.state.tickets = {}

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

    @app.get("/reminders/due", dependencies=[Depends(require_auth)])
    async def reminders_due(request: Request, session_id: str | None = None) -> dict[str, Any]:
        """Reminders that have come due and not yet been delivered.

        Polled by whichever client can reach the user. There is no scheduler:
        a client already sitting in a loop can just ask, which removes a thread,
        a restart-recovery story, and a way to lose reminders across a crash.
        """
        engine: Assistant = request.app.state.engine
        return {"reminders": engine.reminders.due(session_id)}

    @app.post("/reminders/{reminder_id}/delivered", dependencies=[Depends(require_auth)])
    async def reminder_delivered(reminder_id: int, request: Request) -> dict[str, Any]:
        """Claim a reminder. Idempotent, so two pollers can't double-deliver."""
        engine: Assistant = request.app.state.engine
        return {"delivered": engine.reminders.mark_delivered(reminder_id)}

    @app.get("/memory", dependencies=[Depends(require_auth)])
    async def memory_list(request: Request) -> dict[str, Any]:
        engine: Assistant = request.app.state.engine
        return {"facts": engine.memory.all()}

    @app.delete("/memory/{fact_id}", dependencies=[Depends(require_auth)])
    async def memory_forget(fact_id: int, request: Request) -> dict[str, Any]:
        engine: Assistant = request.app.state.engine
        removed = engine.memory.remove(fact_id)
        if removed is None:
            raise HTTPException(status_code=404, detail="no such memory")
        return {"removed": removed}

    # ------------------------------------------------------------------ face

    @app.get("/avatar")
    async def avatar_page() -> FileResponse:
        """The viewer. Unauthenticated because it holds no secret — it reads the
        token from the URL fragment, which browsers never send to a server."""
        if not AVATAR_PAGE.exists():  # pragma: no cover - shipped with the package
            raise HTTPException(status_code=404, detail="avatar page not installed")
        return FileResponse(AVATAR_PAGE, media_type="text/html")

    @app.post("/avatar/ticket", dependencies=[Depends(require_auth)])
    async def avatar_ticket(request: Request) -> dict[str, Any]:
        return {"ticket": _issue_ticket(request.app), "expires_in": int(TICKET_TTL)}

    @app.post("/avatar/publish", dependencies=[Depends(require_auth)])
    async def avatar_publish(body: AvatarEvent, request: Request) -> dict[str, Any]:
        """Where the client playing the audio reports what the speakers are doing.

        The mouth has to be driven from playback, not from synthesis: audio is
        generated far faster than it plays, so animating at the source would put
        her face seconds ahead of her voice.
        """
        bus: AvatarBus = request.app.state.engine.avatar
        bus.publish(body.model_dump(exclude_none=True))
        # Returned so a client with nobody watching can skip the analysis.
        return {"listeners": bus.listeners}

    @app.websocket("/avatar/events")
    async def avatar_events(websocket: WebSocket) -> None:
        if not _websocket_authorized(websocket):
            await websocket.close(code=1008)
            return
        await websocket.accept()

        engine: Assistant = websocket.app.state.engine
        await websocket.send_json(
            {
                "type": "hello",
                "persona": engine.persona.name,
                "emotions": list(engine.persona.emotions),
            }
        )

        with engine.avatar.subscribe() as queue:
            # The face never sends us anything; this task exists only so a
            # closed socket is noticed while we're blocked waiting on the bus.
            reader = asyncio.create_task(_until_closed(websocket))
            getter: asyncio.Task[dict[str, Any]] | None = None
            try:
                while not reader.done():
                    getter = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait(
                        {getter, reader}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if getter not in done:
                        break
                    await websocket.send_json(getter.result())
            except WebSocketDisconnect:
                pass
            finally:
                reader.cancel()
                if getter is not None:
                    getter.cancel()

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


async def _until_closed(websocket: WebSocket) -> None:
    """Return when the socket closes. Anything the client sends is ignored."""
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
    except (WebSocketDisconnect, RuntimeError):
        return
