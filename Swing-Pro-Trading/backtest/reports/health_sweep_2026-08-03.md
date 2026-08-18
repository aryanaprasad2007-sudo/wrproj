# iAPE Health Sweep — 2026-08-03

Automated daily ops check. **Not a clean day** — several real issues found, detailed below. No trades placed, no config touched, nothing modified.

## Summary

| Area | Status |
|---|---|
| Scheduled tasks (10) | All Ready/Enabled; two active issues (see below) |
| forward_state.json / forward_log.csv | Fresh (11:38 AM PT) |
| News scanner API key | Still dead — 311 consecutive 401s, streak ongoing since 2026-07-16 |
| News scanner server | **Currently down** (new finding) |
| Forward_Test order placement | **60 HTTP 500 failures today on AAPL, ongoing** (new finding) |
| Flow_Capture | **0x800710E0 + no flow file for today** (matches historical data-loss pattern) |
| Log sizes | news_scanner.log 469KB (nearing 500KB self-truncate); news_task.log 368KB, growing, no rotation |

## Likely root cause: late machine wake

No log activity exists today before ~10:04–10:12 AM PT in forward_task.log, flow_task.log, or news_scanner.log/news_task.log — all three consistently pick up right around that window. This points to the machine being asleep/off until ~10:12 AM today, well past the 05:25/06:25/06:28 start times these tasks expect. That's roughly 3.5–4 hours of missed pre-market/market-open coverage across Forward_Test, Flow_Capture, and News_Scanner. This is a plausible explanation for items 1 and 3 below, though not for item 2 (news server going silent after it did start).

## Issues found

**1. Flow_Capture — flagging per the specific 0x800710E0 caveat**
- `Last Result: -2147020576` (0x800710E0), `Last Run Time: 8/3/2026 10:12 AM`.
- `flow_task.log` has not been touched today at all (last write: Aug 1).
- No `cache/flow/flow_20260803.csv` exists — today's per-minute CVD/imbalance capture appears to have produced nothing.
- Per the runbook, this exact code has caused real data loss on this task before (not just the benign wake-timing race seen on other tasks). Given the missing log activity and missing output file, today looks like another instance of that, not the harmless variant. Worth a look when you're back at the machine — today's flow data for AAPL/NVDA/TSLA/MSFT/META etc. is likely just gone.

**2. News scanner — API key still dead, and the server is currently not running**
- 401 streak: **311 consecutive JUDGE_ERROR 401s** as of the last log line (10:32:26 AM), continuing since 2026-07-16 10:31 (18+ days now, up from 209 on 7/28). Key still needs to be rotated at console.anthropic.com and set via `ANTHROPIC_API_KEY` (User env var) — no change here.
- **New today:** the scanner's local server (127.0.0.1:8790) restarted fine at 10:12 AM, logged normally through 10:32:36, then went silent. As of this sweep (~11:38 AM), nothing is listening on port 8790 and a direct request to it fails to connect. It should be rescanning every 10 minutes; it's been quiet for over an hour. The process appears to have died sometime after 10:32 rather than just being between scans.

**3. Forward_Test — repeated broker-side order failures on AAPL (unrelated to the July 30 foreign-absorption bug, which is working correctly)**
- State is healthy: AAPL qty=1, entry 335.72, stop 331.63, target 347.99 — correct, and the RECONCILE_FOREIGN_EXCESS/RECONCILE_FOREIGN guards are firing correctly today (foreign AAPL excess of 1537 shares and untracked BA/TSLA positions on the shared venue are being correctly ignored, not adopted). The July 30 fix is doing its job.
- However, since 10:04:16 AM today, every single tick has logged `TICK_ERROR ... HTTP 500 on trade/order/place: {"error_code":"INTERNAL_ERROR"}` for AAPL — **60 consecutive failures** through the most recent tick (11:38 AM), roughly one per minute for over 90 minutes straight. This looks like the broker (Webull) is rejecting an order-management call (likely the stop/target maintenance for the open AAPL position) every tick. Distinct from the historical foreign-qty bug, but the same "wall of repeated order failures" shape — worth checking whether the position's stop/target protection is actually live on the venue right now, since it doesn't look like it's succeeded even once today.

**4. Log sizes — trending up, not yet critical**
- `news_scanner.log`: 469,081 bytes (self-truncates at 500KB — will likely rotate within the next day or so of scanning).
- `news_task.log`: 368,681 bytes (no rotation mechanism; was 303KB on 7/28, so it grew ~65KB in less than a week). Nothing urgent today, but the growth rate suggests it's worth a manual truncate/rotate before it becomes unwieldy.

## Not flagged (expected/benign)
- `Options_Snapshot` also shows Last Result 0x800710E0, but only from its normal 8/2 run and only Flow_Capture is specifically implicated in past data loss — not raising this one.
- `Daily_Signals`, `Forward_Report`, `Weekly_Review`, `MR_Shadow`, `Cockpit`, `Switch_Shadow` all show Last Result 0 and Ready/Enabled state — no action needed.
- `options_daily.csv` last updated Jul 31 — expected, since today's 12:45 PM run hasn't happened yet at sweep time.
