# wrproj

A personal AI assistant with a defined character — calm, level, faintly
condescending — reachable by text on a phone and by voice on a desktop.

Currently at **phase 4**: the persona, a service that holds it, a Telegram bot
for the phone, a desktop client you can hold a spoken conversation with, and
memory and tools so she can actually do things.

```
                        ┌────────────────────────────────┐
 Telegram (phone) ────► │  service                       │
 terminal (tuning) ───► │    persona · memory · tools    │ ────► Claude
 desktop voice ───────► │    STT · chunker · TTS         │
   mic + VAD            └────────────────────────────────┘
```

One brain, thin clients. The persona, conversation history, voice and — later —
tools live in exactly one place, so she's the same entity whether you type at
her or talk to her.

Voice activity detection is the deliberate exception: it stays on the client,
because barge-in is judged in tens of milliseconds and can't afford a round
trip.

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
python run_listen.py       # talk to her out loud
python run_voice.py        # type, and hear her answer (no mic needed)
python run_chat.py         # the tuning terminal (talks to Claude directly)
```

Then open `http://127.0.0.1:8000/avatar#token=$ASSISTANT_TOKEN` to watch her
face while you talk to her.

### Talking to her

```bash
python run_listen.py
```

Then just talk. She detects when you've started and stopped, transcribes,
answers out loud, and — if you talk over her — stops mid-sentence and listens.

**Wear headphones.** Without acoustic echo cancellation the microphone hears
her own voice through the speakers and reads it as you interrupting, so she
cuts herself off, repeatedly, in a loop. `BARGE_IN=0` disables interruption if
you have to use speakers, at the cost of the feature that most makes this feel
like a conversation.

Speech recognition uses faster-whisper: local, offline, free. `base.en`
downloads once on first use; `small.en` is noticeably better and still fine on
CPU. Change it in the `stt:` block of the persona file.

Two knobs matter more than the rest, both in `.env`:

| | |
|---|---|
| `END_SILENCE_MS` (600) | how long you have to stop talking before she answers. This is dead time on **every** turn — the single biggest latency lever in the pipeline. Too low and she cuts you off mid-sentence. |
| `VAD_AGGRESSIVENESS` (2) | 0–3. Raise it if background noise keeps waking her. |

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

## Memory

She writes her own memories, through a `remember` tool, rather than having them
extracted from transcripts by a summariser. The model is good at judging what's
worth keeping, and the result is a short file you can read and correct:

```bash
curl -H "Authorization: Bearer $ASSISTANT_TOKEN" localhost:8000/memory
curl -X DELETE -H "Authorization: Bearer $ASSISTANT_TOKEN" localhost:8000/memory/3
```

It's `data/memory.json` — plain text, editable by hand.

Deliberately not a vector store. At personal scale the whole set fits in the
prompt, and injecting all of it beats retrieving some of it: no embedding model,
no similarity threshold to tune, no relevant fact quietly missed. If it ever
outgrows that, `assistant/memory.py` is the only file that changes.

## Reminders

Ask her to remind you and she works out the absolute time and stores it.
Delivery is a client asking "anything due?" — the Telegram bot is already
sitting in a polling loop, so it costs nothing to ask.

There's no scheduler on purpose. A background timer would add a thread, a
restart-recovery story, and a way to lose reminders silently across a crash.
Asking a store is none of those. Claiming is idempotent, so two clients polling
can't double-fire.

## Tools

Configured in the `tools:` block of the persona file:

| | |
|---|---|
| `memory` | `remember`, `forget` |
| `reminders` | `set_reminder`, `list_reminders`, `cancel_reminder` |
| `web_search` | Anthropic's server-side search. Off by default — it's billed per search. |

Tool descriptions say *when* to call, not just what the tool does. That wording
is load-bearing: recent models are conservative about reaching for custom tools,
and a description that only states a capability gets noticeably fewer calls.

Tools render at the very front of the prompt, so toggling any of these
invalidates the entire cache. Set them and leave them.

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
| `POST /converse` | `{session_id, audio}` (base64 PCM) → SSE: `transcript`, then the whole `/chat/voice` stream |
| `GET /reminders/due` | what's come due and not been delivered |
| `POST /reminders/{id}/delivered` | claim one; idempotent, so pollers can't double-fire |
| `GET /memory`, `DELETE /memory/{id}` | read and prune what she remembers |
| `POST /sessions/{id}/clear` | forget one conversation |
| `POST /persona/reload` | re-read the persona file without a restart |
| `GET /avatar` | the face viewer. Unauthenticated — it holds no secret, it asks for one |
| `POST /avatar/ticket` | swap the token for a single-use, one-minute ticket |
| `POST /avatar/publish` | where a playing client reports `mouth` and `state` |
| `WS /avatar/events` | the face feed: `hello`, `tag`, `say`, `state`, `mouth` |

Turns that use tools emit `tool_use` and `tool_result` events on the streaming
endpoints, so a client can show what she's doing rather than going quiet.

`/chat/voice` is one stream rather than a text call plus a speech call: it keeps
text and audio in sync for display, and avoids paying for the model turn twice.
PCM rides inside SSE as base64 — a third of overhead, which costs nothing over
loopback and keeps the client trivial.

Two things guard this service: it binds to `127.0.0.1` by default, and it
refuses to start without `ASSISTANT_TOKEN`. Both matter, because a reachable
endpoint here is someone else spending your API budget.

## The face

Not the character — that's still open. This is the feed a character subscribes
to, so that whichever rig gets chosen is a rendering job and nothing more.

```
python run_server.py
open http://127.0.0.1:8000/avatar#token=...
```

What arrives on the socket:

| | |
|---|---|
| `hello` | her name and the emotion tags this persona uses |
| `tag` | the expression, sent the moment it's parsed — while she's still speaking |
| `say` | what she's saying, chunk by chunk. Subtitles |
| `state` | `thinking`, `speaking`, `idle` |
| `mouth` | `{frame_ms, open: [0..1]}` — the mouth curve for the audio starting now |

To attach a real rig, replace `window.rig` in `assistant/web/avatar.html` with
something implementing the same four methods — `setMouth`, `setExpression`,
`setState`, `setSubtitle`. The socket, the auth, the reconnect and the mouth
timing stay as they are. The placeholder drawn there now is four shapes on
purpose: it exists to prove the feed is live and in sync, and to be deleted.

**Amplitude, not visemes.** Phoneme-accurate mouth shapes need forced alignment
and a phoneme set that depends on both the TTS engine and the rig — neither of
which is chosen. An openness curve drives the one parameter every rig already
has (Live2D's `ParamMouthOpenY`, VRM's `A` blendshape, VTube Studio's
`MouthOpen`), so any of them can be wired up now and upgraded later without
touching the transport.

**The mouth is published by whoever plays the audio**, never by whoever
synthesises it. Synthesis runs far ahead of playback — that's the point of
streaming it — so animating at the source would put her face seconds ahead of
her voice. Expression and dialogue come from the engine instead, where being a
few hundred milliseconds early is invisible. That's also why a *typed* turn on
Telegram still drives her expression and subtitles: it's the same brain.

**Auth, because browsers can't set headers on a WebSocket.** The usual answer —
token in the query string — writes your long-lived secret into the URL bar, the
history and every access log on the way. Instead the page reads it from the URL
*fragment*, which browsers never send anywhere, and swaps it for a ticket that
expires in a minute and works once. `AVATAR=0` turns the client-side reporting
off entirely.

## Design decisions worth knowing

**Listening never stops.** One task reads the microphone for the whole session,
including while she's talking. Speaking and listening aren't modes, which is
what makes barge-in possible at all — and the utterance that interrupted her
then arrives on the same queue as any other, so cutting her off isn't a special
case, it's just the next thing you said.

**Cancel, don't drain.** When you talk over her, stopping the *feed* isn't
enough: a second of speech is already sitting in the device buffer. Playback is
aborted so she goes quiet immediately.

**Pre-roll, or you lose the first syllable.** Speech is only confirmed a few
frames after it starts, so the segmenter keeps a rolling window from before that
point. Skip it and every capture is missing its first word — which reads as a
bad transcript rather than a bad recording.

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

**Volatile context goes last, not in the system prompt.** She needs to know the
time, and the clock changes on every single request. Put that in the system
prompt and every request reprocesses the persona, the examples *and* the entire
conversation history — the cache never hits. So the time and her memories ride
in a trailing `role: "system"` message, after both breakpoints, where changing
them costs nothing. Models that don't accept that role get it moved into the
system prompt automatically, once, on the first rejection.

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
| 2 | streaming TTS + desktop client that plays audio ✅ |
| 3 | mic, VAD, STT, barge-in → real conversation ✅ |
| 4 | memory and tools ✅ |
| **5** | avatar — the feed ✅, the character ← **you are here** |

The architecture is a pipeline (STT → LLM → TTS), not a speech-to-speech model,
because the character voice needs to be a swappable box — it hasn't been chosen
yet. The `voice:` block in the persona file is where that plugs in.

What's left is the character itself. Everything a face needs is now published
and in sync — expression, dialogue, state, and a mouth curve measured off the
audio as it plays — so picking a rig is a rendering job against four methods,
not a change to any of this.

## Layout

```
persona/rei.yaml         the character — the only file with character text in it
assistant/persona.py     loads the YAML, compiles system prompt + few-shot turns
assistant/emotions.py    emotion tag parsing, streaming and whole-string
assistant/chunker.py     splits streamed text into speakable chunks
assistant/engine.py      the brain: history, caching, streaming, speech, tools
assistant/tools.py       tool definitions and dispatch
assistant/memory.py      what she remembers between conversations
assistant/reminders.py   scheduled nudges, delivered by whoever can reach you
assistant/store.py       conversation persistence
assistant/server.py      HTTP service
assistant/telegram.py    Telegram long-polling client
assistant/voice_client.py desktop playback client
assistant/conversation.py the spoken loop: listening, barge-in
assistant/chat.py        the tuning terminal
assistant/avatar.py      the face feed: mouth envelope, event bus, client link
assistant/web/avatar.html the viewer, and the seam a real rig plugs into
assistant/audio/         mic capture, VAD, utterance segmentation
assistant/tts/           the swappable box: base.py, tone.py, piper.py
assistant/stt/           recognisers: base.py, whisper.py
run_server.py  run_telegram.py  run_listen.py  run_voice.py  run_chat.py
```
