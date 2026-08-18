---
name: label-footage
description: Turn a new recording into a scored regression test for the wrproj lifestyle-tracker detectors — generate blind contact sheets, label them, and score a detector against the labels. Use when Ari says he has new footage to label, wants to score a detector against ground truth, or asks to turn a recording into a regression test.
---

Migrated from CLAUDE.md's "Workflow: turning footage into a regression test"
section (2026-08-13, by `/doctor`) — this is a task-specific procedure invoked
only when new footage arrives, not something every session needs loaded.

```bash
py -3.12 src/claude_eyes.py sheet <video> --every 30   # blind sheets
# Claude reads the sheets in chat and labels them
py -3.12 src/claude_eyes.py score <session>            # writes score.json
```

`labels.json` accepts either `ranges` (`{"from":"00:00","to":"12:30",...}`) or
`tiles` (`{"0":"at_desk",...}`, joined via `manifest.json`). `unsure` bursts
are excluded from the denominator — scoring a detector on a frame the judge
could not read punishes it for the camera's failure, not its own.

See also: `sessions/IMG_9874_analysis/labels.json` + `score.json` for a worked
example, and CLAUDE.md's "Scored against ground truth" section for what the
existing IMG_9874 score does and does not prove.
