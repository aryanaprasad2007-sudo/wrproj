"""Tool definitions and dispatch.

Descriptions say *when* to call, not just what the tool does. That wording is
load-bearing: recent models are conservative about reaching for custom tools,
and a description that only states a capability gets noticeably fewer calls than
one that names the trigger condition.

Definitions are emitted in a fixed order because tools render at the very front
of the prompt — reordering them invalidates the entire cache, for every request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .memory import MemoryStore
from .reminders import ReminderStore

Handler = Callable[[dict[str, Any], str], Awaitable[str]]

# Cap on tool rounds in a single turn. Reached only if she loops; the cap
# turns a runaway into a truncated answer rather than an unbounded bill.
MAX_TOOL_ROUNDS = 6


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class Toolbox:
    def __init__(
        self, tools: list[Tool] | None = None, server_tools: list[dict[str, Any]] | None = None
    ) -> None:
        self._tools = {t.name: t for t in (tools or [])}
        self._server = list(server_tools or [])

    def __bool__(self) -> bool:
        return bool(self._tools or self._server)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def definitions(self) -> list[dict[str, Any]]:
        """Server tools first, then custom ones by name — stable across runs."""
        return self._server + [self._tools[n].definition() for n in sorted(self._tools)]

    async def run(self, name: str, arguments: dict[str, Any], session_id: str) -> tuple[str, bool]:
        """Execute a tool. Returns (result text, is_error).

        Failures come back as tool results rather than exceptions so she can
        read the message and adjust — an unknown id or a malformed time is
        something to correct, not a reason to abandon the turn.
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"No tool named {name!r}.", True
        try:
            return await tool.handler(arguments or {}, session_id), False
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}", True


# --------------------------------------------------------------------- tools


def memory_tools(memory: MemoryStore) -> list[Tool]:
    async def remember(args: dict[str, Any], session_id: str) -> str:
        fact = memory.add(str(args.get("text", "")))
        return f"Stored as memory {fact['id']}."

    async def forget(args: dict[str, Any], session_id: str) -> str:
        removed = memory.remove(int(args["id"]))
        if removed is None:
            return f"No memory with id {args['id']}."
        return f"Forgot: {removed['text']}"

    return [
        Tool(
            name="remember",
            description=(
                "Store a durable fact about the person you work for, so you still "
                "know it in future conversations. Call this whenever they tell you "
                "something about themselves that will still be true next week — "
                "preferences, relationships, recurring commitments, constraints, "
                "ongoing projects, how they like things done. Store the fact, not "
                "the conversation: write 'Allergic to shellfish', not 'said they "
                "were allergic to shellfish at dinner'. Do not store passwords, "
                "card numbers or anything else secret. Do not store one-off "
                "details that expire, like where they parked today."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The fact, in one short sentence.",
                    }
                },
                "required": ["text"],
            },
            handler=remember,
        ),
        Tool(
            name="forget",
            description=(
                "Delete a stored memory by its id. Call this when a fact you have "
                "stored has become wrong or out of date, or when they ask you to "
                "forget something. Your current memories are listed with their ids "
                "in your context."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Id of the memory to delete."}
                },
                "required": ["id"],
            },
            handler=forget,
        ),
    ]


def reminder_tools(reminders: ReminderStore) -> list[Tool]:
    async def set_reminder(args: dict[str, Any], session_id: str) -> str:
        item = reminders.add(session_id, str(args.get("text", "")), str(args["due_at"]))
        return f"Reminder {item['id']} set for {item['due_at']}."

    async def list_reminders(args: dict[str, Any], session_id: str) -> str:
        pending = reminders.pending(session_id)
        if not pending:
            return "No reminders set."
        return "\n".join(f"[{r['id']}] {r['due_at']} — {r['text']}" for r in pending)

    async def cancel_reminder(args: dict[str, Any], session_id: str) -> str:
        cancelled = reminders.cancel(int(args["id"]))
        if cancelled is None:
            return f"No pending reminder with id {args['id']}."
        return f"Cancelled: {cancelled['text']}"

    return [
        Tool(
            name="set_reminder",
            description=(
                "Schedule a reminder to be delivered to them at a specific time. "
                "Call this whenever they ask to be reminded, or say they need to do "
                "something at a particular time. The current time is given in your "
                "context — work out the absolute time yourself and pass it as ISO "
                "8601. Do not ask them to convert 'in twenty minutes' for you."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "What to remind them about, phrased as you'd say it.",
                    },
                    "due_at": {
                        "type": "string",
                        "description": "When, ISO 8601 with a timezone, e.g. 2026-08-04T17:30:00Z.",
                    },
                },
                "required": ["text", "due_at"],
            },
            handler=set_reminder,
        ),
        Tool(
            name="list_reminders",
            description=(
                "List reminders that have been set and not yet delivered. Call this "
                "when they ask what is coming up, or before setting something that "
                "might duplicate an existing reminder."
            ),
            input_schema={"type": "object", "properties": {}},
            handler=list_reminders,
        ),
        Tool(
            name="cancel_reminder",
            description=(
                "Cancel a pending reminder by id. Call this when they say a reminder "
                "is no longer needed. Use list_reminders first if you don't know the id."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Id of the reminder to cancel."}
                },
                "required": ["id"],
            },
            handler=cancel_reminder,
        ),
    ]


def build(
    config: dict[str, Any] | None,
    memory: MemoryStore,
    reminders: ReminderStore,
) -> Toolbox:
    """Assemble the toolbox named by a persona's `tools:` block."""
    config = dict(config or {})
    tools: list[Tool] = []
    server: list[dict[str, Any]] = []

    if config.get("memory", True):
        tools += memory_tools(memory)
    if config.get("reminders", True):
        tools += reminder_tools(reminders)
    if config.get("web_search", False):
        # Runs on Anthropic's side — no handler, results arrive in the response.
        entry: dict[str, Any] = {"type": "web_search_20260209", "name": "web_search"}
        if config.get("web_search_max_uses"):
            entry["max_uses"] = int(config["web_search_max_uses"])
        server.append(entry)

    return Toolbox(tools, server)
