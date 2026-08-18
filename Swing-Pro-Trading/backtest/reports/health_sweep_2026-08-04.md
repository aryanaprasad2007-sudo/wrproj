# iAPE Health Sweep — 2026-08-04

Automated daily ops check, run pre-market (~5:44 AM PT, before today's 6:25 AM session start). Report only — no trades placed, no config touched, nothing modified.

## Summary

| Area | Status |
|---|---|
| Scheduled tasks (10) | All Ready/Enabled; Flow_Capture shows 0x800710E0 (see below) |
| forward_state.json / forward_log.csv | Fresh as of last session close (8/3 ~1:05 PM PT) — today's session hasn't started yet |
| News scanner API key | Still dead — 312 consecutive 401s, streak ongoing since 2026-07-16 (19 days) |
| News scanner server | Currently up (port 8790 responding, HTTP 200) |
| Log sizes | news_scanner.log 459KB (nearing 500KB self-truncate); news_task.log 361KB, growing, no rotation |
| Carried-over issues from 8/3 (unresolved, not new today) | Flow_Capture produced no output for 8/3; Forward_Test had 141 consecutive order-placement failures for the back half of 8/3's session |

## Issues found

**1. Flow_Capture — 0x800710E0 on the specifically-flagged task, and it matches the data-loss pattern, not the benign one**
- `Last Result: -2147020576` = `0x800710E0`, `Last Run Time: 8/3/2026 10:12 AM`.
- `flow_task.log` has not been touched since **Aug 1** — the 8/3 run left no log trace at all.
- No `cache/flow/flow_20260803.csv` exists — yesterday's per-minute CVD/imbalance capture produced nothing.
- This is the same finding as yesterday's sweep, still unrecovered. Per the runbook, this specific code has caused real data loss on Flow_Capture before (unlike the same error code seen harmlessly elsewhere, e.g. Options_Snapshot). Today's run is due at 6:28 AM — worth checking after market open whether it recovers on its own or needs a manual look.

**2. News scanner API key — still dead, 19 days now**
- 312 consecutive `JUDGE_ERROR: 401` as of the last log line (05:35:21 AM today), unbroken since 2026-07-16 10:31 (up from 209 on 7/28, 311 on 8/3). No change — key still needs rotation at console.anthropic.com and setting via the `ANTHROPIC_API_KEY` User env var. Headline/local-signal scanning is unaffected (SYSTEM signals still computing fine each scan).
- Unlike yesterday's sweep (which found the server itself had silently died mid-session), the server is currently up and responding on port 8790 — no server-availability issue right now.

**3. Log sizes — trending up, not yet critical**
- `news_scanner.log`: 469,963 bytes (~459KB). Self-truncates at 500KB — will likely rotate within the next day of scanning.
- `news_task.log`: 369,553 bytes (~361KB). No rotation mechanism; was 303KB on 7/28, so ~66KB growth in 7 days (~9.5KB/day). Nothing urgent, same standing recommendation to manually truncate/rotate before it becomes unwieldy.

## Carried over from yesterday (context, not a new finding today)

- **Forward_Test HTTP 500s, 8/3:** every tick from 10:04:20 AM through the last logged tick at 12:59:09 PM (141 consecutive ticks, ~3 hours) failed with `HTTP 500 on trade/order/place: INTERNAL_ERROR` while trying to manage the open AAPL position. The log simply stops at 12:59, before the normal 1:20 PM close — no recovery visible before the session ended. Worth checking once today's session opens whether AAPL's stop/target protection is actually live on Webull, since it doesn't look like a single order-management call succeeded for the second half of 8/3.

## Not flagged (expected/benign)

- `forward_state.json` (8/3 1:05 PM) / `forward_log.csv` (8/3 12:59 PM) — last touched at yesterday's session close; today's session hasn't opened yet at check time, so this is expected, not stale.
- `Options_Snapshot`, `Daily_Signals`, `Forward_Report`, `Weekly_Review`, `MR_Shadow`, `Cockpit`, `Switch_Shadow` all show Last Result 0 and Ready/Enabled — no action needed.
- `Weekly_Review` next run 8/7 (Fri) — correct, last ran 7/31.
