# wrproj

A personal AI assistant with a defined character — calm, level, faintly
condescending — reachable by text on a phone and by voice on a desktop.

Currently at **phase 2**: the persona, a service that holds it, a Telegram bot
for the phone, and a desktop client that speaks.

```
                        ┌──────────────────────────────┐
 Telegram (phone) ────► │  service                     │
                        │    persona · memory · tools  │ ────► Claude
 terminal (tuning) ───► │    chunker · TTS             │
                        └──────────────────────────────┘
 desktop voice ───────► │  (mic arrives in phase 3)    │
                        └──────────────────────────────┘
```

One brain, thin clients. The persona, conversation history, voice and — later —
tools live in exactly one place, so she's the same entity whether you type at
her or talk to her.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `ANTHROPIC_API_KEY` and generate a service token:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Then, in separate shells:

```bash
python run_server.py       # the brain, on 127.0.0.1:8000
python run_telegram.py     # the phone client
python run_voice.py        # the desktop client — type, and hear her answer
python run_chat.py         # the tuning terminal (talks to Claude directly)
```

### Voice

Out of the box the voice engine is `tone`, which emits soft tones rather than
speech. That's deliberate: it needs no download and no key, so the whole
pipeline runs on a fresh clone and you can hear that it works. It is obviously
not speech, so there's no chance of mistaking it for working TTS.

For actual speech, download a Piper voice once and switch the engine:

```bash
python -m piper.download_voices en_US-lessac-medium --download-dir voices
```

```yaml
# persona/rei.yaml
voice:
  engine: piper
```

Piper is local, offline, free and CPU-only. It is not the character voice — it's
what lets you build and hear the rest of the system before that decision is
made. When you pick a real voice, write one adapter in `assistant/tts/`, add a
line to the registry, and change `engine:`. Nothing else moves.

If there's no audio output device — over SSH, in a container — the client writes
WAV files to `audio/` instead and tells you so. That's also the easier way to
scrub back over how a particular chunk sounded.

### Telegram setup

1. Message [@BotFather](https://t.me/botfather), `/newbot`, copy the token into
   `TELEGRAM_BOT_TOKEN`.
2. Start `run_telegram.py` and message your bot once. It will refuse to answer
   and log the chat id it saw.
3. Put that id in `TELEGRAM_ALLOWED_CHAT_IDS` and restart.

The allowlist is not optional in practice — anyone who finds the bot's username
can message it, and without the allowlist she answers nobody. The bot uses long
polling, so no public URL, HTTPS certificate or port forwarding is needed.

In Telegram: `/clear` forgets the conversation, `/reload` re-reads the persona
file, anything else is just talking to her.

## The tuning loop

`run_chat.py` is the tool for getting the character right. Open
`persona/rei.yaml` in one pane and the chat in another:

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

Terminal history is in-memory on purpose: a tuning session should start clean.
Telegram conversations persist to `data/conversations.json` and survive a
restart.

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

## API

Everything except `/health` needs `Authorization: Bearer $ASSISTANT_TOKEN`.

| | |
|---|---|
| `GET /health` | persona name, model, effort. Unauthenticated — leaks nothing |
| `POST /chat` | `{session_id, message}` → `{text, tag, usage}` |
| `POST /chat/stream` | same body, SSE: `tag`, then `delta`s, then `done`/`error` |
| `POST /chat/voice` | same body, SSE: `start`, `tag`, then interleaved `text` and base64 `audio`, then `done` |
| `POST /sessions/{id}/clear` | forget one conversation |
| `POST /persona/reload` | re-read the persona file without a restart |

`/chat/voice` is one stream rather than a text call plus a speech call: it keeps
text and audio in sync for display, and avoids paying for the model turn twice.
PCM rides inside SSE as base64 — a third of overhead, which costs nothing over
loopback and keeps the client trivial.

Two things guard this service: it binds to `127.0.0.1` by default, and it
refuses to start without `ASSISTANT_TOKEN`. Both matter, because a reachable
endpoint here is someone else spending your API budget.

## Design decisions worth knowing

**Speak the first sentence before the last one is written.** The chunker cuts
the model's output into speakable pieces the moment each is complete, and the
first cut is deliberately aggressive — in practice the first chunk is a dozen
characters and audio starts while the model is still typing. Waiting for the
full reply before synthesising adds a second or more of dead air to every turn,
and that delay is most of what makes a voice assistant feel sluggish. Later
chunks are allowed to grow, because a TTS engine given a whole sentence produces
better prosody than one fed fragments.

**Sentence detection has an asymmetric cost.** A missed split just makes one
chunk longer; a wrong split makes her pause mid-sentence. So the abbreviation
list is conservative and deliberately excludes anything that is also a common
word — `no.` and `am.` would swallow far more real sentence endings than the
rare "No. 5" they'd catch.

**Emotion tags now, avatar later.** Every response opens with `[neutral]`,
`[bored]`, `[smug]` and so on. It's parsed off before display and before the
text reaches TTS, and emitted as its own event as soon as it's known — while
she's still speaking, not after. It costs nothing today and means the Live2D/VRM
work in phase 5 is a plug-in rather than a refactor.

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

**A failed turn keeps what you typed.** If the model call errors, the user
message stays in history so `/regen` retries it instead of losing it.

**One lock per session.** Two messages fired off from a phone in quick
succession would otherwise interleave and corrupt the history.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The model is mocked at the HTTP layer rather than by patching the SDK, so the
tests exercise real request construction — cache breakpoint placement, message
alternation and parameter shape are checked against what would actually go on
the wire.

## Where this is going

| | |
|---|---|
| 0 | persona + terminal chat ✅ |
| 1 | backend service + Telegram bot ✅ |
| **2** | streaming TTS + desktop client that plays audio ← **you are here** |
| 3 | mic, VAD, STT, barge-in → real conversation |
| 4 | memory and tools |
| 5 | avatar |

The architecture is a pipeline (STT → LLM → TTS), not a speech-to-speech model,
because the character voice needs to be a swappable box — it hasn't been chosen
yet. The `voice:` block in the persona file is where that plugs in.

Phase 3 is where it starts feeling like a conversation. The piece that matters
most there is barge-in: cutting the audio the instant you start talking over
her. That single feature does more for "feels alive" than anything else left.

## Layout

```
persona/rei.yaml         the character — the only file with character text in it
assistant/persona.py     loads the YAML, compiles system prompt + few-shot turns
assistant/emotions.py    emotion tag parsing, streaming and whole-string
assistant/chunker.py     splits streamed text into speakable chunks
assistant/engine.py      the brain: history, caching, streaming, speech
assistant/store.py       conversation persistence
assistant/server.py      HTTP service
assistant/telegram.py    Telegram long-polling client
assistant/voice_client.py desktop playback client
assistant/chat.py        the tuning terminal
assistant/tts/           the swappable box: base.py, tone.py, piper.py
run_server.py  run_telegram.py  run_voice.py  run_chat.py
```
