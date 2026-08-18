---
name: aria-read
description: >-
  Have Aria read course material out loud in her voice so Ari can get through
  it without holding focus on a screen. Use when he says "have Aria read this",
  "read me this page", "aria read my course", "read this out loud", "keep
  reading", "next page", or points at a lecture / PDF / Canvas page and wants
  it spoken. Works both for text he can copy and for screens he can't (video
  slides, embedded PDF viewers) via screenshot. Written to run on Haiku.
---

# Aria reads it to him

He can't hold focus on a page of course text, but he can listen. This puts the
text in front of her and opens the reader in its own window.

**One command does all the plumbing** — starting her service, saving the
document, opening a console he can actually type in. Your only job is getting
the words. Do not script around it.

```bash
py -3.12 "C:/Users/aware/OneDrive/Desktop/wrproj/aria-assistant/read_this.py" --title "ANTH 1 Lecture 4" --stdin <<'TEXT'
<the text, exactly as it appears>
TEXT
```

Then tell him it's reading, in one line. He drives from there:
`space` pause · `b` back a block · `n` next · `r` repeat · `q` stop.

## Getting the words — cheapest first

Try these in order. The top two are exact and cost nothing; only fall through
when the one above genuinely isn't available.

1. **A file** — PDF, markdown, HTML, txt. Pass the path, no transcription:
   `py -3.12 ".../read_this.py" "C:/path/lecture.pdf"`
2. **Selectable text on screen** — a normal Canvas or web page. Use
   `mcp__claude-in-chrome__get_page_text` and pipe it in on `--stdin`.
   (If the browser tools aren't connected, ask him to Ctrl+A Ctrl+C and use
   `--clipboard` instead — still exact, still free.)
3. **Text he cannot copy** — video slides, an embedded PDF viewer, a locked
   course player. Only here: screenshot and transcribe. Load
   `ToolSearch({query: "computer-use", max_results: 30})`, call
   `request_access`, then `screenshot`, and type out what's on screen.

**Say which one you used** when it was 3. "Read off the screen" and "read from
the page" are different promises, and he's revising from it.

## Transcribing a screen (step 3 only)

Copy the words out. You are a transcriber here, not an editor.

- **Do not** summarise, shorten, reword, reorder, or "clean up" a clumsy
  sentence. He is studying this. A tidied sentence is wrong in a way he cannot
  hear, because it still sounds like prose and still sounds like her.
- **Do** skip the interface: nav bars, sidebars, buttons, progress bars,
  timestamps, "Next lesson". That's furniture, not content.
- **Keep** real headings that are on the screen. Don't invent new ones.
- If something is cut off, too small, or covered, **say so** and leave it out.
  Never fill a gap with what it probably said.

## The screenshot loop — how he'll actually use it

One screen isn't a lecture. Keep **the same `--title`** and add `--append` for
every screen after the first, so it stays one document with one position:

```bash
py -3.12 "C:/.../read_this.py" --title "ANTH 1 Lecture 4" --append --stdin <<'TEXT'
<the next screen>
TEXT
```

When he says "keep reading" / "next page": screenshot, append, done.
When he comes back later, `--title` alone resumes where he stopped:

```bash
py -3.12 "C:/.../read_this.py" --title "ANTH 1 Lecture 4"
```

Same title = same file = same bookmark. A new title starts a new document at
the top, so don't paraphrase the title differently each time.

## Guardrails

- **Never send the model's words in as the text.** Everything on `--stdin` is
  the source material. `read_this.py` hands it straight to speech with no model
  in the path — that guarantee is only worth something if you honour it. If you
  want to say something *about* the material, say it to him in chat.
- **Don't read what he didn't ask for.** A screenshot catches his whole
  desktop. Transcribe the course window, not his mail, messages, or anything
  else that happens to be open.
- **Don't summarise instead.** If he wanted the summary he'd have asked for
  one; offering it is fine, substituting it is not.
- **One window.** If a reader is already running, he stops it with `q` — don't
  launch a second one over the top of it.
- Nothing here is destructive. `--restart` only discards a saved position.

## If it doesn't work

- *"her service didn't come up"* — a console opened with the traceback in it.
  Usually the port is taken by an older copy; check that console, don't retry.
- *No sound* — her voice engine (kokoro) takes ~50s to load the first time
  after the service starts. It's not stuck. After that it's under a second.
- *`--stdin` with nothing on it* — the heredoc has to end with `TEXT` on its
  own line, in column 1.

Built on `read_this.py` and `run_read.py` in `aria-assistant/`. The README's
"Reading things to you" section covers why the model is kept out of the read
path.
