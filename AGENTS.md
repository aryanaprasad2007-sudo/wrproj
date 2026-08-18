# wrproj — agent instructions

**The project doc is [CLAUDE.md](CLAUDE.md). Read that.**

This file is a stub on purpose. It used to be a 407-line `sed s/Claude/Codex/`
copy of CLAUDE.md, which cost ~6.7k tokens to load a *second* time and had
already drifted (it rewrote the real path `.claude/skills/label-footage/` into
`.Codex/skills/`, a directory that does not exist).

OpenCode auto-loads this file and is pointed at CLAUDE.md via `instructions`
in `opencode.json`, so the real doc arrives either way. Do not restore the
copy — put new facts in CLAUDE.md.

The old copy is kept at `local-agent/AGENTS.md.old-duplicate` until you're
satisfied nothing unique was lost in it.
