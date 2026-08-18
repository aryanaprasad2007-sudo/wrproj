# TF3 shadow — Task Scheduler setup (not registered yet)

`tf3_shadow.py` was built and run once manually (see `reports/tf3_shadow.md` for
the first output — currently **ARMED**, 0 closed trades, as expected since the
audition just started today). No Windows Task Scheduler job was created — that's
a standing system change and needs your explicit go-ahead in a live session.

The two sibling shadows (`SwingPro_MR_Shadow` at 13:40 PT, `SwingPro_Switch_Shadow`
at 13:45 PT) are both registered with `WakeToRun` enabled, running windowless via
`run_hidden.vbs`, daily. TF3 fits the next slot: **13:50 PT**.

## Option A — classic `schtasks` (matches the sibling tasks' command/log/hidden pattern)

```bash
schtasks /Create /TN "SwingPro_TF3_Shadow" /SC DAILY /ST 13:50 /RL LIMITED /F /TR "wscript.exe \"C:\Users\aware\OneDrive\Desktop\wrproj\Swing-Pro-Trading\backtest\run_hidden.vbs\" \"cmd /c cd /d C:\Users\aware\OneDrive\Desktop\wrproj\Swing-Pro-Trading\backtest && py tf3_shadow.py >> tf3_shadow_task.log 2>&1\""
```

Caveat: classic `schtasks /Create` has no flag for "wake the computer to run this
task" (`WakeToRun`), which both sibling tasks have set. After creating the task
above, either:
- open Task Scheduler -> `SwingPro_TF3_Shadow` -> Properties -> Conditions ->
  check "Wake the computer to run this task", or
- use Option B below, which sets it in one shot.

## Option B — PowerShell `Register-ScheduledTask` (sets WakeToRun directly)

```bash
powershell -NoProfile -Command "$a = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '\"C:\Users\aware\OneDrive\Desktop\wrproj\Swing-Pro-Trading\backtest\run_hidden.vbs\" \"cmd /c cd /d C:\Users\aware\OneDrive\Desktop\wrproj\Swing-Pro-Trading\backtest && py tf3_shadow.py >> tf3_shadow_task.log 2>&1\"'; $t = New-ScheduledTaskTrigger -Daily -At 1:50PM; $s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew; Register-ScheduledTask -TaskName 'SwingPro_TF3_Shadow' -Action $a -Trigger $t -Settings $s -Force"
```

Either way, review the task in Task Scheduler afterward and compare its
Conditions/Settings tab against `SwingPro_Switch_Shadow` to confirm they match.

## Everything else already done

- `backtest/tf3_shadow.py` — built, follows the exact `mr_forward.py` /
  `switch_shadow.py` pattern (deterministic daily recompute, no persisted
  state, shadow-only, never places an order).
- Ran once manually: `reports/tf3_shadow.md`, `tf3_shadow_equity.csv`,
  `tf3_shadow_trades.csv` all produced successfully.
- Judge threshold left at >=30 closed trades per house rule 3 — not loosened.
- No broker calls, no touching of `forward_state.json` / `forward_log.csv`,
  no Pine script edits.
