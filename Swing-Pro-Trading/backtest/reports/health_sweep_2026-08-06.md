# iAPE Health Sweep — 2026-08-06

Automated daily ops check, run mid-session (~11:08 AM PT, market open since 6:25 AM, no prior sweep today). Report only — no trades placed, no config touched, nothing modified.

## Summary

| Area | Status |
|---|---|
| **Root cause** | 🔴 **`py` launcher's default silently changed from Python 3.12 → a newly-present Python 3.14**, which has none of the third-party packages (numpy/pandas/yfinance/anthropic) the trading stack needs. Every scheduled task invokes bare `py script.py`, so every task that has run since ~8/5 08:00 AM has crashed on its first `import`. |
| Scheduled tasks (10) | All Ready/Enabled, Next Run Times look correct — **but 7 of 10 have crashed on every run since ~8/4 evening / 8/5 morning** (see below); the other 3 (Options_Snapshot, Forward_Report, Weekly_Review) haven't fired yet today/this week but use the identical broken invocation and will almost certainly fail too. |
| forward_state.json / forward_log.csv | **STALE — frozen at 8/4 13:05 / 12:59 PT.** No successful tick since, despite ~2 full market sessions elapsing. |
| Open positions unmanaged | **3 open positions (AAPL, JPM, CVX) have had zero stop/target checks for ~2 days** — see Issue 1. |
| News scanner API key | **Cannot be evaluated this cycle** — the 401 streak has been entirely superseded by `ModuleNotFoundError: No module named 'anthropic'` since ~8/5. |
| Log sizes | news_scanner.log 13.6KB (fine, well under its 500KB self-truncate); news_task.log 403KB, still growing, still no rotation |

## Issues found

**1. 🔴 Machine-wide Python environment regression — breaking nearly the entire pipeline, and 3 live positions are currently unmonitored**

- `py -0` shows two installs: `3.14[-64] *` (marked default) and `3.12` (present, not default). This is new — the tasks all shell out with the bare `py` command (confirmed via `schtasks /xml`: `py forward_trader.py --once`, `py options_snapshot.py`, `py forward_trader.py --report`, etc.), so they now run under 3.14 instead of 3.12.
- Directly invoking `Python312\python.exe` confirms numpy 2.5.0 and pandas 3.0.3 **are installed and importable** — the packages aren't gone, they're just not reachable through the new `py` default. This is a launcher-resolution problem, not a corrupted install.
- **Confirmed broken (crashing on import, verified from each task's own log) since the switch:**
  - `SwingPro_Forward_Test` — `ModuleNotFoundError: No module named 'numpy'`, every minute tick, all day today (430+ occurrences in the log tail alone). This is the every-minute intraday trader.
  - `SwingPro_Flow_Capture` — `No module named 'pandas'` (via `data.py`) at its one daily launch (8/5 06:28). **No `flow_20260805.csv` or `flow_20260806.csv` exists** — two full sessions of per-minute CVD/flow capture lost. This is exactly the Flow_Capture-specific data-loss pattern the runbook warns about, though the trigger this time is the `py` regression, not the historical wake-race.
  - `SwingPro_Daily_Signals` — numpy, crashed at its 8/5 13:05 run (no scan happened; log just stops after the 8/4 entry then shows the traceback).
  - `SwingPro_Cockpit` — numpy, crashed at 8/5 13:22 (cockpit.html is now 2 days stale).
  - `SwingPro_MR_Shadow` — numpy, crashed at 8/5 13:40 (last successful bar still 2026-08-04).
  - `SwingPro_Switch_Shadow` — numpy, crashed at 8/5 13:45 (last successful bar still 2026-08-04).
  - `SwingPro_News_Scanner` — numpy, pandas, yfinance, **and** anthropic all missing; every scan since 8/5 08:00 runs fully degraded (see Issue 2).
- **Not yet observed today but same certainty of failure:** `SwingPro_Options_Snapshot` (due 12:45 PM) and `SwingPro_Forward_Report` (due 1:20 PM) both invoke bare `py` and log to the same `forward_task.log` — they haven't fired yet today, so no direct log evidence, but given 7/7 confirmed failures across every other task using the same invocation, expect them to fail identically unless the environment is fixed first. `SwingPro_Weekly_Review` (next due Fri 8/7) is at the same risk.
- **Note on `Last Result` / `0x800710E0`:** schtasks reports `-2147020576` (0x800710E0) on Forward_Test and Flow_Capture, and `0` (apparent success) on Daily_Signals/Cockpit/MR_Shadow/Switch_Shadow — **neither is trustworthy**, per the known `run_hidden.vbs`-swallows-exit-codes gotcha. All of the above was confirmed by reading actual log content, not by the reported result codes. 0x800710E0 is a red herring here, not the real diagnosis.
- **⚠ Operational consequence — 3 open positions are currently unmonitored:** `forward_state.json` (frozen since 8/4 13:05) still shows open positions in **AAPL** (intraday, entry $335.72 / stop $331.63 / target $347.99), **JPM** (daily, entry $347.02 / stop $323.26 / target $418.32), and **CVX** (daily, entry $192.54 / stop $184.56 / target $216.49). Since Forward_Test can't get past its first `import`, none of these have had a stop/target check for ~2 days of market time (all of 8/5's session plus today so far). Worth a manual look at the actual Webull paper positions if/until the environment is fixed.

**2. News scanner ANTHROPIC_API_KEY status — question moot this cycle, superseded by the same environment bug**

- The 401 streak tracked in prior sweeps (312 as of 8/4, ongoing since 2026-07-16) is **not visible anywhere in the current log window** — every `JUDGE_ERROR` since 8/5 08:00 reads `No module named 'anthropic'` instead (30/30 in the current log; log self-truncates at 500KB so older 401 history has rolled off, consistent with normal behavior, not a new problem).
- The "consecutive scans without AI judgment" counter keeps incrementing (392 as of 10:58:45 AM today) but **no longer reflects an auth problem** — it reflects the same `py`-default regression as Issue 1. Whether the API key itself is now valid **cannot be determined** until `anthropic` (and numpy/pandas/yfinance) are importable again from whatever the scheduled tasks actually run under.
- Headline/local-signal scanning still works (SYSTEM signals compute independent of the missing packages, per the log), so the scanner isn't fully dead — it's running in the same degraded fallback mode as before, just for a different underlying reason now.

**3. Log sizes — trending up, not yet critical**

- `news_scanner.log`: 13,623 bytes (~13.6KB). Well under its 500KB self-truncate cap — healthy, and the small size here is itself evidence the file recently truncated (explains why no 401-era history remains).
- `news_task.log`: 412,606 bytes (~403KB). No rotation mechanism. Was 303KB on 7/28, ~361KB on 8/4 → ~42KB growth in 2 days, faster than the earlier ~9.5KB/day trend (plausibly inflated by the new tracebacks being appended every 10-min scan cycle since 8/5). Nothing urgent, but worth a manual truncate before it gets unwieldy, and it'll keep growing faster than usual while the import errors persist.

## Not flagged (expected/benign)

- All 10 scheduled tasks are Ready/Enabled with sane Next Run Times — the Task Scheduler registrations themselves are fine; this is a runtime/environment issue, not a scheduling issue.
- `SwingPro_Weekly_Review` next run 8/7 (Fri) — correct, last successful run 7/31 (its 8/7 run is at the same environment risk as everything else, noted above).

## Suggested next step (not performed — report only)

Whoever addresses this will want to either point `py`'s default back at the 3.12 install (`py -0p` / the Python Install Manager config) or repoint the scheduled tasks' command lines at the 3.12 interpreter explicitly (e.g. `py -3.12 forward_trader.py --once`) — verified working directly against `Python312\python.exe` in this sweep. Until then, expect every SwingPro_* task to keep failing on import, and the three open positions above to stay unmonitored.
