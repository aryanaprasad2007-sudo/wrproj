"""Terminal chat loop — phase 0.

The point of this loop is tone tuning, so the important features are /reload
(re-read the persona file without losing the conversation) and /regen (re-roll
the last response). Edit the YAML in one pane, /reload in this one, compare.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic

from .emotions import EmotionStripper
from .persona import DEFAULT_PERSONA, Persona, load

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
  /raw             toggle showing the raw emotion tag
  /system          print the compiled system prompt
  /help            this
  /quit            exit
"""


class Chat:
    def __init__(self, persona_path: str | Path = DEFAULT_PERSONA) -> None:
        self.client = anthropic.Anthropic()
        self.persona: Persona = load(persona_path)
        self.history: list[dict[str, Any]] = []
        self.show_raw = False

    # ---------------------------------------------------------------- request

    def _build_messages(self) -> list[dict[str, Any]]:
        """Few-shot examples, then the live conversation, with cache breakpoints.

        Breakpoint one sits at the end of the stable prefix (system + examples).
        Breakpoint two rides the last turn so conversation history accrues cache
        hits as the session grows.
        """
        messages = [dict(m) for m in self.persona.few_shot]
        if messages:
            messages[-1] = _with_cache(messages[-1])

        messages += [dict(m) for m in self.history]
        if self.history:
            messages[-1] = _with_cache(messages[-1])
        return messages

    def _system(self) -> list[dict[str, Any]]:
        block: dict[str, Any] = {"type": "text", "text": self.persona.system}
        if not self.persona.few_shot:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def _respond(self) -> None:
        stripper = EmotionStripper()
        printed_label = False
        parts: list[str] = []

        try:
            with self.client.messages.stream(
                model=self.persona.model,
                max_tokens=self.persona.max_tokens,
                system=self._system(),
                thinking=self.persona.thinking_param,
                output_config={"effort": self.persona.effort},
                messages=self._build_messages(),
            ) as stream:
                for delta in stream.text_stream:
                    visible = stripper.feed(delta)
                    if not visible:
                        continue
                    if not printed_label:
                        print(_label(self.persona.name, stripper.tag), end="", flush=True)
                        printed_label = True
                    print(visible, end="", flush=True)
                    parts.append(visible)

                tail = stripper.flush()
                if tail:
                    if not printed_label:
                        print(_label(self.persona.name, stripper.tag), end="", flush=True)
                        printed_label = True
                    print(tail, end="", flush=True)
                    parts.append(tail)

                final = stream.get_final_message()
        except anthropic.RateLimitError:
            print(RED("\n  rate limited — wait a moment and try /regen"))
            return
        except anthropic.APIStatusError as exc:
            print(RED(f"\n  api error {exc.status_code}: {exc.message}"))
            return
        except anthropic.APIConnectionError:
            print(RED("\n  connection failed"))
            return

        print("\n")

        if final.stop_reason == "refusal":
            print(RED("  response was declined by safety classifiers\n"))
            return

        text = "".join(parts).strip()
        stored = f"[{stripper.tag}] {text}" if stripper.tag else text
        self.history.append({"role": "assistant", "content": stored})

        if self.show_raw:
            usage = final.usage
            print(
                DIM(
                    f"  tag={stripper.tag}  in={usage.input_tokens} "
                    f"out={usage.output_tokens} "
                    f"cache_read={usage.cache_read_input_tokens}\n"
                )
            )

    # ----------------------------------------------------------------- commands

    def _command(self, line: str) -> bool:
        """Returns False when the loop should exit."""
        cmd, _, arg = line[1:].partition(" ")
        cmd, arg = cmd.strip().lower(), arg.strip()

        if cmd in ("quit", "exit", "q"):
            return False

        if cmd == "help":
            print(DIM(HELP))

        elif cmd == "reload":
            path = arg or self.persona.path or DEFAULT_PERSONA
            try:
                self.persona = load(path)
                print(DIM(f"  reloaded {self.persona.name} from {path}\n"))
            except Exception as exc:
                print(RED(f"  reload failed: {exc}\n"))

        elif cmd == "regen":
            if len(self.history) < 2:
                print(DIM("  nothing to regenerate\n"))
            else:
                self.history.pop()  # drop the assistant turn, keep the user turn
                self._respond()

        elif cmd == "clear":
            self.history.clear()
            print(DIM("  conversation cleared\n"))

        elif cmd == "save":
            print(DIM(f"  wrote {self._save(arg)}\n"))

        elif cmd == "raw":
            self.show_raw = not self.show_raw
            print(DIM(f"  raw tags {'on' if self.show_raw else 'off'}\n"))

        elif cmd == "system":
            print(DIM("\n" + self.persona.system + "\n"))

        else:
            print(DIM(f"  unknown command: /{cmd} — try /help\n"))

        return True

    def _save(self, arg: str) -> Path:
        root = Path(__file__).resolve().parent.parent
        path = Path(arg) if arg else root / "transcripts" / (
            f"{datetime.now():%Y%m%d-%H%M%S}-{self.persona.name.lower()}.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [f"# {self.persona.name} — {datetime.now():%Y-%m-%d %H:%M}", ""]
        for msg in self.history:
            who = "you" if msg["role"] == "user" else self.persona.name.lower()
            lines.append(f"**{who}:** {msg['content']}")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # --------------------------------------------------------------------- run

    def run(self) -> None:
        print(BOLD(f"\n  {self.persona.name}") + DIM("  ·  /help for commands\n"))
        while True:
            try:
                line = input(CYAN("you> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not line:
                continue
            if line.startswith("/"):
                if not self._command(line):
                    return
                continue

            self.history.append({"role": "user", "content": line})
            print()
            self._respond()


def _label(name: str, tag: str | None) -> str:
    prefix = f"\n{name.lower()}> "
    return BOLD(prefix) + (DIM(f"[{tag}] ") if tag else "")


def _with_cache(message: dict[str, Any]) -> dict[str, Any]:
    """Attach a cache breakpoint to a message's final content block."""
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    else:
        content = [dict(b) for b in content]
    content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    return {**message, "content": content}
