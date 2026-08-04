# wrproj

A personal AI assistant with a defined character — calm, level, faintly
condescending — reachable by text on a phone and by voice on a desktop.

This is **phase 0**: the persona and a terminal chat loop. Getting the tone right
is the hard part and it costs almost nothing to iterate on, so it comes first.
Everything after this is plumbing.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env        # add your ANTHROPIC_API_KEY
python run_chat.py
```

Point it at a different character with `python run_chat.py persona/other.yaml`.

## The tuning loop

Open `persona/rei.yaml` in one pane and the chat in another:

| command | |
|---|---|
| `/reload` | re-read the persona file, keeping the conversation |
| `/regen` | throw away the last reply and re-roll it |
| `/raw` | show the emotion tag and token counts |
| `/system` | print the compiled system prompt |
| `/save` | write the transcript to `transcripts/` |
| `/clear`, `/help`, `/quit` | |

Edit the YAML, `/reload`, `/regen`, compare. When she gets a situation wrong,
**add an example** — the `examples:` block does more work than every adjective
above it. Adjectives give you a caricature; examples give you a register.

## How the character is defined

Everything lives in `persona/rei.yaml`. No character text exists anywhere else.

- **`tone`** — the register, plus the rules that keep it from drifting. The two
  failure modes are generic-sassy-assistant and actually-mean-and-unhelpful. The
  rule that prevents both: competence first, disdain as garnish. She does the
  task completely; the condescension lives in the framing, never the substance.
- **`sincerity_switch`** — when something is genuinely serious she drops the
  register entirely, without announcing it. A persona that can't turn it off
  gets exhausting inside a week, and this is the one failure that actually
  matters.
- **`examples`** — ten exchanges covering the situations that define the edges:
  repeated questions, bad ideas, ambiguity, praise, pushback, real distress.
- **`format`** — plain spoken sentences, no markdown. That's a real constraint
  once TTS is in front of it, so it's enforced from day one.

## Design decisions worth knowing

**Emotion tags now, avatar later.** Every response opens with `[neutral]`,
`[bored]`, `[smug]` and so on. It's parsed off before display (and later before
the text reaches TTS) and surfaced separately. It costs nothing today and means
the Live2D/VRM work in phase 5 is a plug-in rather than a refactor.

**Adaptive thinking at low effort.** Conversation isn't a reasoning task, and
latency matters once this sits behind a voice pipeline. Disabling thinking
outright is the wrong lever — on Opus 5 it causes tool calls to leak into
visible text and `<thinking>` tags to leak into output. Low effort is the
correct way to cut latency and cost.

**Prompt caching.** The system prompt plus few-shot examples are a stable prefix,
so a cache breakpoint sits at the end of the examples and a second rides the
last turn. The examples are effectively free after the first request.

**Streaming with a buffered tag parser.** `EmotionStripper` holds back only the
leading few characters — enough to decide whether a tag is present — then passes
everything through. The tag can be split across any number of stream deltas,
including `]` landing exactly on a chunk boundary.

## Where this is going

| | |
|---|---|
| **0** | persona + terminal chat ← **you are here** |
| 1 | wrap in a backend service, Telegram bot for phone |
| 2 | streaming TTS in the backend, desktop client that plays audio |
| 3 | mic, VAD, STT, barge-in → real conversation |
| 4 | memory and tools |
| 5 | avatar |

The architecture is a pipeline (STT → LLM → TTS), not a speech-to-speech model,
because the character voice needs to be a swappable box — it hasn't been chosen
yet. One backend holds persona, memory and tools; the phone and desktop clients
are both thin.

## Layout

```
persona/rei.yaml       the character — the only file with character text in it
assistant/persona.py   loads the YAML, compiles system prompt + few-shot turns
assistant/emotions.py  emotion tag parsing, streaming and whole-string
assistant/chat.py      the terminal loop
run_chat.py            entry point
```
