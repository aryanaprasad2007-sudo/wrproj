"""Terminal chat loop — the persona tuning tool.

Thin client over `Assistant`. The important features are /reload (re-read the
persona file without losing the conversation) and /regen (re-roll the last
reply). Edit the YAML in one pane, /reload in this one, compare.

History here is deliberately in-memory: a tuning session should start clean.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from .engine import Assistant
from .persona import DEFAULT_PERSONA

SESSION = "terminal"
_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


DIM = lambda s: _c("2", s)  # noqa: E731
BOLD = lambda s: _c("1", s)  # noqa: E731
CYAN = lambda s: _c("36", s)  # noqa: E731
RED = lambda s: _c("31", s)  # noqa: E731

HELP = """
  /reload [path]   re-read the persona file (keeps the conversation)
  /regen           throw away the last reply and generate a new one
  /clear           wipe the conversation, keep the persona
  /save [path]     write the transcript to transcripts/
  /raw             toggle showing the emotion tag and token counts
  /system          print the compiled system prompt
  /help            this
  /quit            exit
"""


class Chat:
    def __init__(self, persona_path: str | Path = DEFAULT_PERSONA) -> None:
        self.engine = Assistant(persona_path)
        self.show_raw = False

    @property
    def name(self) -> str:
        return self.engine.persona.name

    # ---------------------------------------------------------------- output

    async def _respond(self, text: str | None = None, regenerate: bool = False) -> None:
        labelled = False
        async for event in self.engine.stream(SESSION, text, regenerate=regenerate):
            if event["type"] == "delta":
                if not labelled:
                    print(BOLD(f"\n{self.name.lower()}> "), end="", flush=True)
                    labelled = True
                print(event["text"], end="", flush=True)

            elif event["type"] == "error":
                print(RED(f"\n  {event['message']}\n"))
                return

            elif event["type"] == "done":
                print("\n")
                if self.show_raw:
                    u = event["usage"]
                    print(
                        DIM(
                            f"  tag={event['tag']}  in={u['input_tokens']} "
                            f"out={u['output_tokens']} "
                            f"cache_read={u['cache_read_input_tokens']}\n"
                        )
                    )

    # -------------------------------------------------------------- commands

    async def _command(self, line: str) -> bool:
        """Returns False when the loop should exit."""
        cmd, _, arg = line[1:].partition(" ")
        cmd, arg = cmd.strip().lower(), arg.strip()

        if cmd in ("quit", "exit", "q"):
            return False

        if cmd == "help":
            print(DIM(HELP))

        elif cmd == "reload":
            try:
                persona = self.engine.reload(arg or None)
                print(DIM(f"  reloaded {persona.name} from {persona.path}\n"))
            except Exception as exc:
                print(RED(f"  reload failed: {exc}\n"))

        elif cmd == "regen":
            await self._respond(regenerate=True)

        elif cmd == "clear":
            self.engine.clear(SESSION)
            print(DIM("  conversation cleared\n"))

        elif cmd == "save":
            print(DIM(f"  wrote {self._save(arg)}\n"))

        elif cmd == "raw":
            self.show_raw = not self.show_raw
            print(DIM(f"  raw tags {'on' if self.show_raw else 'off'}\n"))

        elif cmd == "system":
            print(DIM("\n" + self.engine.persona.system + "\n"))

        else:
            print(DIM(f"  unknown command: /{cmd} — try /help\n"))

        return True

    def _save(self, arg: str) -> Path:
        root = Path(__file__).resolve().parent.parent
        path = Path(arg) if arg else root / "transcripts" / (
            f"{datetime.now():%Y%m%d-%H%M%S}-{self.name.lower()}.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [f"# {self.name} — {datetime.now():%Y-%m-%d %H:%M}", ""]
        for msg in self.engine.history(SESSION):
            who = "you" if msg["role"] == "user" else self.name.lower()
            lines.append(f"**{who}:** {msg['content']}")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # ------------------------------------------------------------------- run

    async def run(self) -> None:
        print(BOLD(f"\n  {self.name}") + DIM("  ·  /help for commands\n"))
        try:
            while True:
                try:
                    # Keeps the event loop free while waiting on the keyboard.
                    line = (await asyncio.to_thread(input, CYAN("you> "))).strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return

                if not line:
                    continue
                if line.startswith("/"):
                    if not await self._command(line):
                        return
                    continue

                print()
                await self._respond(line)
        finally:
            await self.engine.aclose()
