# Claude Code status line: where you are in the NightOwl day.
# Reads config directly (no module import) so it stays fast enough to run on
# every render. Claude Code pipes session JSON on stdin; we ignore it.

$ErrorActionPreference = "SilentlyContinue"
try { $null = [Console]::In.ReadToEnd() } catch { }

$cfgPath = "C:\Users\aware\OneDrive\Desktop\wrproj\nightowl\config.json"
if (-not (Test-Path $cfgPath)) { Write-Output ""; exit 0 }

$c = Get-Content $cfgPath -Raw | ConvertFrom-Json
$now = Get-Date

$wp   = $c.wake.Split(":")
$wake = $now.Date.AddHours([int]$wp[0]).AddMinutes([int]$wp[1])
if ($now -lt $wake) { $wake = $wake.AddDays(-1) }

$bp  = $c.bedtime.Split(":")
$bed = $wake.Date.AddHours([int]$bp[0]).AddMinutes([int]$bp[1])
if ($bed -le $wake) { $bed = $bed.AddDays(1) }

$wind  = $bed.AddMinutes(-1 * $c.windDownMinutes)
$awake = [math]::Round(($now - $wake).TotalHours, 1)
$toBed = [math]::Round(($bed - $now).TotalMinutes)

if ($now -ge $bed) {
    $late = [math]::Round((($now - $bed).TotalHours), 1)
    $phase = "past bedtime +${late}h"
} elseif ($now -ge $wind) {
    $phase = "wind-down"
} elseif ($toBed -lt 240) {
    $phase = "evening"
} else {
    $phase = "day"
}

if ($toBed -ge 0) {
    $h = [math]::Floor($toBed / 60); $m = $toBed % 60
    if ($h -gt 0) { $left = "${h}h ${m}m to bed" } else { $left = "${m}m to bed" }
} else {
    $left = "bed was $($bed.ToString('HH:mm'))"
}

# State file carries the last mode the engine applied.
$statePath = "C:\Users\aware\OneDrive\Desktop\wrproj\nightowl\data\state.json"
$mode = "auto"
if (Test-Path $statePath) {
    try { $mode = (Get-Content $statePath -Raw | ConvertFrom-Json).mode } catch { }
}

Write-Output ("* {0}  |  {1}h awake  |  {2}  |  mode: {3}" -f $phase, $awake, $left, $mode)
