"""Load a persona YAML file and compile it into API-ready request pieces.

The persona file is the source of truth for the character. This module turns it
into a system prompt plus few-shot messages; nothing else in the codebase should
contain character text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PERSONA = Path(__file__).resolve().parent.parent / "persona" / "rei.yaml"


@dataclass
class Persona:
    name: str
    system: str
    few_shot: list[dict[str, Any]]
    emotions: list[str]
    model: str
    max_tokens: int
    effort: str
    thinking: str
    voice: dict[str, Any] = field(default_factory=dict)
    stt: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @property
    def thinking_param(self) -> dict[str, str]:
        return {"type": "adaptive"} if self.thinking == "adaptive" else {"type": "disabled"}


def load(path: str | Path = DEFAULT_PERSONA) -> Persona:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    model = raw.get("model") or {}
    emotions = raw.get("emotions") or ["neutral"]

    return Persona(
        name=raw.get("name", "Assistant"),
        system=_compile_system(raw, emotions),
        few_shot=_compile_few_shot(raw.get("examples") or []),
        emotions=emotions,
        model=model.get("id", "claude-opus-5"),
        max_tokens=int(model.get("max_tokens", 4096)),
        effort=model.get("effort", "low"),
        thinking=model.get("thinking", "adaptive"),
        voice=raw.get("voice") or {},
        stt=raw.get("stt") or {},
        tools=raw.get("tools") or {},
        path=path,
    )


def _compile_system(raw: dict[str, Any], emotions: list[str]) -> str:
    sections: list[str] = []

    def add(title: str, body: Any) -> None:
        if body and str(body).strip():
            sections.append(f"# {title}\n\n{str(body).strip()}")

    add("Who you are", raw.get("identity"))
    add("How you speak", raw.get("tone"))
    add("When to drop the act", raw.get("sincerity_switch"))
    add("Response format", raw.get("format"))

    sections.append(
        "# Emotion tags\n\nThe only valid tags are: "
        + ", ".join(f"[{e}]" for e in emotions)
        + ".\nUse exactly one, at the very start of every response."
    )

    user = raw.get("user") or {}
    name, notes = user.get("name"), (user.get("notes") or "").strip()
    if name or notes:
        lines = ["# The person you work for", ""]
        if name:
            lines.append(f"Their name is {name}.")
        if notes:
            lines.append(notes)
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _compile_few_shot(examples: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Turn example exchanges into alternating message turns.

    These are prepended to every conversation. They cost tokens on each request
    but are the single strongest lever on tone, and prompt caching makes the
    repeated cost negligible once the prefix is warm.
    """
    messages: list[dict[str, Any]] = []
    for ex in examples:
        user, assistant = ex.get("user"), ex.get("assistant")
        if not user or not assistant:
            continue
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})
    return messages
