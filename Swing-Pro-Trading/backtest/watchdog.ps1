# watchdog.ps1 - iAPE liveness check that CANNOT die the way the system dies.
#
# WHY THIS EXISTS (2026-08-12):
# On ~2026-08-04 a Python 3.14 install silently became the `py` launcher's
# default. 3.14 has none of this project's packages, so all ten SwingPro_*
# tasks crashed on `import numpy` for 8 days. Task Scheduler reported success
# the whole time (run_hidden.vbs detaches, so exit codes are swallowed), and
# forward_state.json simply stopped advancing while three paper positions sat
# unmanaged.
#
# The existing health sweep DID diagnose it correctly on 8/6 - and then stopped
# running, because it was itself a Python script invoked through the same
# broken `py`. A monitor that shares a failure mode with the thing it monitors
# is not a monitor.
#
# So this deliberately uses NO Python: pure PowerShell, and it probes the
# interpreter as an external subject rather than running inside it.
#
# It reports FACTS, not verdicts - a stale state file can mean "the trader is
# broken" or "the PC was switched off", and this script cannot tell those
# apart. It says which it sees and lets a human judge. (Same facts-not-
# judgments rule the camera/screen sensors follow elsewhere in wrproj.)
#
# RUN IT:  watchdog.cmd          (the .cmd wrapper is required - .ps1 files are
#                                 blocked by the Restricted execution policy)

$ErrorActionPreference = 'Continue'

$Backtest = Split-Path -Parent $MyInvocation.MyCommand.Path
$Reports  = Join-Path $Backtest 'reports'
$Cache    = Join-Path $Backtest 'cache'
$AlertFile = Join-Path $Cache 'WATCHDOG_ALERT.txt'
$Pinned   = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'

$problems = New-Object System.Collections.ArrayList
$warnings = New-Object System.Collections.ArrayList
$lines    = New-Object System.Collections.ArrayList
function Say([string]$t) { [void]$lines.Add($t); Write-Host $t }
function Bad([string]$t) { [void]$problems.Add($t) }
function Warn([string]$t) { [void]$warnings.Add($t) }

Say "iAPE watchdog - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Say ("=" * 62)

# ---------------------------------------------------------------- interpreter
Say ""
Say "## Interpreter"
if (Test-Path $Pinned) {
    $probe = & $Pinned -c "import numpy, pandas; print('ok')" 2>&1
    if ($probe -match 'ok') {
        Say "  [OK]   pinned 3.12 present, numpy+pandas import"
    } else {
        Say "  [FAIL] pinned 3.12 present but imports BROKE: $probe"
        Bad "Pinned Python 3.12 can no longer import numpy/pandas."
    }
} else {
    Say "  [FAIL] pinned interpreter MISSING: $Pinned"
    Bad "Pinned Python 3.12 is gone. run_hidden.vbs will fall back to bare 'py'."
}

# Drift probe: what does a bare `py` resolve to now? The tasks no longer depend
# on this (run_hidden.vbs pins the path), but a drift here is the early warning
# that something re-shuffled the Python installs again.
$bare = & py -c "import sys; print(sys.executable)" 2>&1 | Select-Object -Last 1
if ($bare -like '*Python312*') {
    Say "  [OK]   bare 'py' -> 3.12"
} else {
    Say "  [WARN] bare 'py' -> $bare"
    Warn "Bare 'py' does not resolve to 3.12. Scheduled tasks are protected by the pin in run_hidden.vbs, but anything you run by hand with 'py' will use the wrong interpreter. Use the full path or 'py -3.12'."
}

# Is the pin actually still in place? A restored/overwritten launcher would
# silently reintroduce the original outage.
$vbs = Join-Path $Backtest 'run_hidden.vbs'
if ((Test-Path $vbs) -and (Select-String -Path $vbs -Pattern 'Python312' -Quiet)) {
    Say "  [OK]   run_hidden.vbs interpreter pin intact"
} else {
    Say "  [FAIL] run_hidden.vbs is missing its interpreter pin"
    Bad "run_hidden.vbs no longer pins Python 3.12 - the 2026-08-04 outage can recur."
}

# ------------------------------------------------------------------ freshness
Say ""
Say "## Trader liveness"
$stateFile = Join-Path $Backtest 'forward_state.json'
if (Test-Path $stateFile) {
    $age = (Get-Date) - (Get-Item $stateFile).LastWriteTime
    $ageTxt = "{0:N1}h" -f $age.TotalHours
    Say ("  forward_state.json last advanced: {0}  ({1} ago)" -f (Get-Item $stateFile).LastWriteTime, $ageTxt)

    # Most recent weekday on which a session should have run.
    $probe = Get-Date
    if ($probe.DayOfWeek -eq 'Saturday' -or $probe.DayOfWeek -eq 'Sunday' -or $probe.Hour -lt 7) { $probe = $probe.AddDays(-1) }
    while ($probe.DayOfWeek -eq 'Saturday' -or $probe.DayOfWeek -eq 'Sunday') { $probe = $probe.AddDays(-1) }
    $expected = Get-Date -Year $probe.Year -Month $probe.Month -Day $probe.Day -Hour 6 -Minute 30 -Second 0

    if ((Get-Item $stateFile).LastWriteTime -lt $expected) {
        Say ("  [STALE] expected activity on or after {0}" -f $expected)
        Bad ("forward_state.json has not advanced since {0} - no successful tick in {1}. Either the tasks are failing again, or the PC was off/shut down (WakeToRun wakes from sleep, not from shutdown)." -f (Get-Item $stateFile).LastWriteTime, $ageTxt)
    } else {
        Say "  [OK]   state advanced within the last expected session"
    }

    # Unmanaged-position check: this is the part with money attached.
    try {
        $st = Get-Content $stateFile -Raw | ConvertFrom-Json
        $n1 = @($st.positions.PSObject.Properties).Count
        $n2 = @($st.daily_positions.PSObject.Properties).Count
        Say ("  open positions: {0} intraday, {1} daily" -f $n1, $n2)
        if (($n1 + $n2) -gt 0 -and (Get-Item $stateFile).LastWriteTime -lt $expected) {
            Bad ("{0} open position(s) have had NO stop/target check since {1}." -f ($n1 + $n2), (Get-Item $stateFile).LastWriteTime)
        }
    } catch { Say "  [WARN] could not parse forward_state.json" }
} else {
    Bad "forward_state.json is missing."
}

# ----------------------------------------------------------------- task logs
Say ""
Say "## Task logs (only output appended since the previous check)"
# WHY A BASELINE and not a tail scan: a quiet successful tick appends NOTHING
# to forward_task.log (verified 2026-08-12 - 11,083 lines, only 1,981 of them
# non-error), so "do the last N lines look clean?" would stay permanently red
# after a fixed outage, because the old traceback is still the final thing in
# the file. And a fixed-size window is wrong in the other direction too:
# daily_task.log gets one line per day, so a 40-line window would keep
# reporting a healed outage for ~40 days.
#
# Recording a line count per log and judging ONLY the lines added since then
# answers the question that actually matters - "has anything failed since I
# last looked?" - regardless of how chatty the task is.
$pat = 'Traceback|ModuleNotFoundError|ImportError'
$logs = 'forward_task.log','daily_task.log','cockpit_task.log','mr_forward_task.log',
        'switch_shadow_task.log','flow_task.log','news_task.log'

$baseFile = Join-Path $Cache 'watchdog_baseline.json'
$base = @{}
if (Test-Path $baseFile) {
    try { (Get-Content $baseFile -Raw | ConvertFrom-Json).PSObject.Properties |
            ForEach-Object { $base[$_.Name] = [int]$_.Value } } catch { }
}
$newBase = @{}

foreach ($l in $logs) {
    $p = Join-Path $Backtest $l
    if (-not (Test-Path $p)) { Say ("  [ -- ] {0,-24} absent" -f $l); continue }
    $content = @(Get-Content $p -ErrorAction SilentlyContinue)
    $count   = $content.Count
    $newBase[$l] = $count
    $mt = (Get-Item $p).LastWriteTime
    $sz = [math]::Round((Get-Item $p).Length / 1KB, 0)

    if ($base.ContainsKey($l)) {
        $added = $count - $base[$l]
        if ($added -lt 0) {
            Say ("  [ -- ] {0,-24} log rotated/truncated        last {1}  {2}KB" -f $l, $mt, $sz)
        } elseif ($added -eq 0) {
            Say ("  [ -- ] {0,-24} nothing new since last check  last {1}  {2}KB" -f $l, $mt, $sz)
        } else {
            $fresh = @($content | Select-Object -Last $added)
            $bad   = @($fresh | Select-String -Pattern $pat).Count
            if ($bad -gt 0) {
                Say ("  [FAIL] {0,-24} {1} new tracebacks           last {2}  {3}KB" -f $l, $bad, $mt, $sz)
                Bad "$l has logged $bad new traceback line(s) since the last watchdog run."
            } else {
                Say ("  [OK]   {0,-24} {1} new lines, clean         last {2}  {3}KB" -f $l, $added, $mt, $sz)
            }
        }
    } else {
        # First ever run: no baseline to diff against, so fall back to the tail
        # and say plainly that this reading is a snapshot, not a delta.
        $tailBad = @(@($content | Select-Object -Last 60) | Select-String -Pattern $pat).Count
        if ($tailBad -gt 0) {
            Say ("  [FAIL] {0,-24} {1} tracebacks in tail (no baseline yet)  last {2}" -f $l, $tailBad, $mt)
            Bad "$l shows $tailBad traceback line(s) in its recent tail (first watchdog run - no baseline to diff against yet)."
        } else {
            Say ("  [OK]   {0,-24} tail clean (no baseline yet)   last {1}" -f $l, $mt)
        }
    }
    if ($sz -gt 5120) { Warn "$l is ${sz}KB and has no rotation." }
}

if (-not (Test-Path $Cache)) { New-Item -ItemType Directory -Path $Cache -Force | Out-Null }
$newBase | ConvertTo-Json | Set-Content -LiteralPath $baseFile -Encoding utf8

# ------------------------------------------------------------ output freshness
Say ""
Say "## Generated outputs"
$outs = @{
    'cockpit.html'              = (Join-Path (Split-Path -Parent $Backtest) 'cockpit.html')
    'reports\forward_test.md'   = (Join-Path $Reports 'forward_test.md')
    'reports\mr_forward.md'     = (Join-Path $Reports 'mr_forward.md')
    'reports\switch_shadow.md'  = (Join-Path $Reports 'switch_shadow.md')
}
foreach ($k in $outs.Keys | Sort-Object) {
    if (Test-Path $outs[$k]) {
        $d = ((Get-Date) - (Get-Item $outs[$k]).LastWriteTime).TotalDays
        $tag = if ($d -gt 4) { '[WARN]' } else { '[OK]  ' }
        Say ("  {0} {1,-26} {2:N1} days old" -f $tag, $k, $d)
        if ($d -gt 4) { Warn "$k is $([math]::Round($d,1)) days old." }
    } else { Say ("  [ -- ] {0,-26} absent" -f $k) }
}

# ------------------------------------------------------------------- verdict
Say ""
Say ("=" * 62)
if ($problems.Count -gt 0) {
    Say "VERDICT: PROBLEMS FOUND ($($problems.Count))"
    foreach ($p in $problems) { Say "  * $p" }
} else {
    Say "VERDICT: healthy"
}
if ($warnings.Count -gt 0) {
    Say "Warnings ($($warnings.Count)):"
    foreach ($w in $warnings) { Say "  - $w" }
}

# The alert file's EXISTENCE is the signal - so it is removed when clean.
if (-not (Test-Path $Cache)) { New-Item -ItemType Directory -Path $Cache -Force | Out-Null }
if ($problems.Count -gt 0) {
    $lines -join "`r`n" | Set-Content -LiteralPath $AlertFile -Encoding utf8
    Say ""
    Say "ALERT written -> $AlertFile"
} elseif (Test-Path $AlertFile) {
    Remove-Item -LiteralPath $AlertFile -Force
    Say ""
    Say "(previous alert cleared)"
}

if (-not (Test-Path $Reports)) { New-Item -ItemType Directory -Path $Reports -Force | Out-Null }
$rp = Join-Path $Reports ("watchdog_{0}.md" -f (Get-Date -Format 'yyyy-MM-dd'))
"``````" + "`r`n" + ($lines -join "`r`n") + "`r`n" + "``````" | Set-Content -LiteralPath $rp -Encoding utf8
Say "Report  -> $rp"
