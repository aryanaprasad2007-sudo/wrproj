# iAPE Health Sweep — 2026-08-01

Automated daily ops check. Report only — nothing was modified, no config touched, no orders placed.

Context: today is Saturday, markets closed. Last live session was Friday 2026-07-31.

## 1. Scheduled tasks — all 10 healthy

All ten `SwingPro_*` tasks: **Last Result 0x0, Status Ready, Scheduled Task State Enabled.** No error codes seen on this sweep — including no `0x800710E0` on `Flow_Capture`, which had shown that code (with real data loss) on 7/28 and 7/30.

| Task | Last Run | Result | Next Run |
|---|---|---|---|
| Forward_Test | 7/31 1:20 PM | 0 | 8/1 6:25 AM |
| Flow_Capture | 7/31 6:28 AM | 0 | 8/1 6:28 AM |
| Options_Snapshot | 7/31 12:45 PM | 0 | 8/1 12:45 PM |
| Daily_Signals | 7/31 1:05 PM | 0 | 8/1 1:05 PM |
| Forward_Report | 7/31 1:20 PM | 0 | 8/1 1:20 PM |
| Weekly_Review | 7/31 1:30 PM | 0 | 8/7 1:30 PM (Fri) |
| MR_Shadow | 7/31 1:40 PM | 0 | 8/1 1:40 PM |
| Cockpit | 7/31 1:22 PM | 0 | 8/1 1:22 PM |
| Switch_Shadow | 7/31 1:45 PM | 0 | 8/1 1:45 PM |
| News_Scanner | 7/31 5:25 AM | 0 | 8/3 5:25 AM (Mon, weekday-only) |

Next-run times all look correct given the Sat/Sun gap (News_Scanner and Weekly_Review both correctly skip to the next weekday).

## 2. Forward-state freshness — healthy

- `forward_state.json`: mtime **7/31 1:05 PM** — matches the last market session.
- `forward_log.csv`: mtime **7/31 12:59 PM** — matches the last market session.

Both fresh, no staleness.

## 3. News scanner API key — still dead, 16 days now

Tail of `news_scanner.log` (last entries, 7/31 12:54 PM): still `JUDGE_ERROR: Error code: 401 - authentication_error: API key is invalid`, and the degraded-mode gate (shipped 7/28) is working correctly — logging `SCAN done — DEGRADED: no AI judgment for 307 consecutive scans since 2026-07-16 10:31` rather than a silent clean line.

Streak progression across sweeps: 209 (7/28) → 268 (7/31) → **307 (now, 8/1)**. Key has been dead continuously since 2026-07-16 10:31 — **16 days**. No action possible on this end; still needs Ari to mint a replacement key at console.anthropic.com and set it via `[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY","sk-ant-…","User")`, then restart the scanner process (it prefers stale `os.environ` over the registry value).

## 4. Log file sizes — news_scanner.log approaching its self-truncation limit

- `news_scanner.log`: **466 KB** (was 402 KB on 7/28) — self-truncates at 500 KB, so it's within ~34 KB of that threshold and will likely truncate on its own soon. Not an error, just noting it's imminent.
- `news_task.log`: **366 KB** (was 303 KB on 7/28) — this one has **no rotation** (plain `cmd` redirect) and keeps growing. Not urgent today, but the standing recommendation (unacted, needs Ari's go) to give it rotation or move it out of the unbounded-append path still stands.

## 5. Flow_Capture — no data loss this session

`cache/flow/flow_20260731.csv` exists (226 KB, mtime 7/31 1:02 PM) — Friday's capture completed normally. This breaks the two-in-a-row data-loss streak from 7/28 and 7/30 (both missing their `flow_<date>.csv` under the same `0x800710E0` signature). Good news, but the underlying cause of those two prior losses is still unproven/unfixed — this one clean day doesn't rule out a recurrence.

## 6. Escalated finding: AAPL order-place error loop ran the ENTIRE 7/31 session, not just the morning

The 7/31 sweep flagged this as active "07:32–08:58 and possibly still ongoing." Checking `forward_log.csv` directly: it did **not** stop at 08:58 — `TICK_ERROR HTTP 500 on trade/order/place: INTERNAL_ERROR` for AAPL fired on essentially every one-minute tick from **06:31 through 12:59** (the last tick of the day), **388 error events in that single session**.

This is also not a one-off — it's the second occurrence of this exact `HTTP 500 INTERNAL_ERROR` signature on AAPL: **184 events on 7/30**, now **388 on 7/31** (more than double, and this time spanning the full session rather than clearing partway through). Not root-caused either day.

Current state (`forward_state.json`): AAPL position still open — qty=1, entry_ref $335.72, entered 2026-07-27, `be_done: true` (stop already moved to breakeven). Whatever the bot is trying to do with this position every tick (manage the stop, presumably) is failing against Alpaca's paper order-place endpoint every single minute.

This is Alpaca-paper only (broker.py hardcodes paper-api.alpaca.markets — no real-money path), so no money is at risk, and exits are never gated by the halt/observer logic, but the position has effectively been un-manageable for two sessions running and the trend is getting worse, not better. Worth root-causing soon — check whether this is an Alpaca-side outage on this specific order vs. a corrupted local order/qty state before the next session starts ticking Monday.

## Summary

Mostly healthy day: all 10 tasks green, state fresh, Flow_Capture recovered. Two items to keep watching, one of which has escalated:
- News API key: still dead, 16 days, no action possible without Ari.
- **AAPL order-place error loop: escalated from partial-morning to full-session, second consecutive occurrence, still unresolved — recommend prioritizing root-cause before Monday's open.**
