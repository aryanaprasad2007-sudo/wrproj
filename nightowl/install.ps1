<#
    NightOwl installer.

    Registers the nightowl:// protocol, the scheduled tasks, shortcuts and the
    shell profile. Everything lands under HKCU and the user's own task folder,
    so no elevation is needed and uninstall.ps1 reverses all of it.
#>
[CmdletBinding()]
param([switch]$SkipTasks, [switch]$SkipShortcuts, [switch]$SkipProfile)

$ErrorActionPreference = "Stop"

# Every task and shortcut below bakes an absolute path into a command line that
# Task Scheduler / Explorer will replay long after this script exits. An empty
# $Root silently interpolates to "" and yields "\nohidden.vbs", which wscript
# resolves against the current drive root as C:\nohidden.vbs - a Windows Script
# Host error box on every click, with nothing to trace it back to. Fail here
# instead, where the cause is still visible.
$Root = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Root)) {
    throw "`$PSScriptRoot is empty - run install.ps1 as a file (.\install.ps1), not dot-sourced or pasted into a console."
}
$Bin = Join-Path $Root "bin"
$Vbs = Join-Path $Bin "nohidden.vbs"
if (-not (Test-Path $Vbs)) { throw "silent launcher missing: $Vbs" }

function Say { param($m, $c = "Gray") Write-Host "  $m" -ForegroundColor $c }

Write-Host ""
Write-Host "  NightOwl installer" -ForegroundColor Magenta
Write-Host "  $Root" -ForegroundColor DarkGray
Write-Host ""

foreach ($d in @("data", "logs", "hub")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
}

# ---------------------------------------------------------- URL protocol ----

Write-Host "  URL protocol" -ForegroundColor Cyan

# Chromium's external-protocol launch goes through Shell.Application COM
# automation, which resolves "shell\open\command" via the same association
# API Explorer uses. That resolver silently drops every argument once the
# command has more than two tokens (an explicit interpreter + a static quoted
# path + %1) - and even a single quoted ".vbs" target + %1 still breaks,
# because resolving a .vbs requires a second hop (.vbs -> wscript.exe) that
# reproduces the same corruption. A compiled, argument-free .exe as the sole
# quoted target is the one shape that survives: one hop, two tokens.
$cscCandidates = @(
    "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
$csc = $cscCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$stubSrc = Join-Path $Bin "nourl_launcher.cs"
$stubExe = Join-Path $Bin "nourl.exe"
if ($csc -and (Test-Path $stubSrc)) {
    & $csc /nologo /target:winexe /out:$stubExe $stubSrc | Out-Null
    Say "compiled nourl.exe" "Green"
} elseif (-not (Test-Path $stubExe)) {
    throw "csc.exe not found and nourl.exe does not already exist - cannot register the protocol handler."
}

$proto = "HKCU:\Software\Classes\nightowl"
New-Item -Path $proto -Force | Out-Null
Set-ItemProperty -Path $proto -Name "(Default)"   -Value "URL:NightOwl Protocol"
Set-ItemProperty -Path $proto -Name "URL Protocol" -Value ""
$cmdKey = Join-Path $proto "shell\open\command"
New-Item -Path $cmdKey -Force | Out-Null
$launch = "`"$stubExe`" `"%1`""
Set-ItemProperty -Path $cmdKey -Name "(Default)" -Value $launch
Say "nightowl:// -> $stubExe" "Green"

# ------------------------------------------------------- scheduled tasks ----

if (-not $SkipTasks) {
    Write-Host ""
    Write-Host "  Scheduled tasks" -ForegroundColor Cyan

    $cfg     = Get-Content (Join-Path $Root "config.json") -Raw | ConvertFrom-Json
    $wakeP   = $cfg.wake.Split(":")
    $bedP    = $cfg.bedtime.Split(":")
    $today   = (Get-Date).Date
    $wakeAt  = $today.AddHours([int]$wakeP[0]).AddMinutes([int]$wakeP[1])
    $bedAt   = $today.AddHours([int]$bedP[0]).AddMinutes([int]$bedP[1])
    $windAt  = $bedAt.AddMinutes(-1 * $cfg.windDownMinutes)

    #  StartWhenAvailable is deliberately OFF for everything that talks to Ari
    #  or changes the machine's mode.
    #
    #  It means "if the scheduled start was missed, run it as soon as you can."
    #  For a task that says something, that is exactly wrong. On 2026-08-17 the
    #  PC was off overnight and booted at 10:55; Task Scheduler then replayed
    #  the whole missed night at 10:59 - WindDown (00:30) and Bedtime (01:30)
    #  fired back to back in the late morning, dimming the screen to 2500K,
    #  dropping to PowerSaver, pinning state.json at "sleep" for the rest of the
    #  day, and showing a card telling him he was up past bedtime.
    #
    #  It also silently doubles the repeating tasks: the replayed instance
    #  carries its own copy of the repetition block, so it runs in parallel with
    #  the real schedule, phase-shifted. That is why the log showed two screen
    #  syncs 45s apart and two eye-break cards ~3 min apart, all afternoon.
    #
    #  A missed break is simply a break that no longer applies. Skipping it is
    #  the correct behaviour, not a loss.
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew

    #  Data-refresh tasks are the exception: they say nothing and touch no
    #  mode, so running them late is strictly better than skipping them.
    $settingsCatchUp = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew

    function Add-NOTask {
        # NOT $Args - that is an automatic variable (the unbound-argument array).
        # A parameter of that name binds without complaint but reads back empty,
        # so every task registered as a bare "no.ps1" with the verb stripped,
        # which no.ps1 then defaults to the harmless read-only "status". Result:
        # eleven tasks reporting exit 0 while doing nothing at all.
        param($Name, $LaunchArgs, $Trigger, $Desc, $TaskSettings = $null)
        if (-not $TaskSettings) { $TaskSettings = $settings }
        $action = New-ScheduledTaskAction -Execute "wscript.exe" `
                    -Argument "`"$Vbs`" $LaunchArgs"
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger `
            -Settings $TaskSettings -Description $Desc -Force | Out-Null
        Say "$Name" "Green"
    }

    function New-NORepeatingTrigger {
        <#  A daily trigger carrying a repetition block. Task Scheduler rejects
            an unbounded duration, so the window is renewed every day instead -
            23h55m from wake covers the whole cycle including the small hours. #>
        param([datetime]$At, [int]$IntervalMinutes)
        $t = New-ScheduledTaskTrigger -Daily -At $At
        $t.Repetition = (New-ScheduledTaskTrigger -Once -At $At `
                            -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
                            -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 55)).Repetition
        return $t
    }

    Add-NOTask "NightOwl_Screen" "screen" `
        (New-NORepeatingTrigger -At $wakeAt -IntervalMinutes 15) `
        "Re-apply the circadian colour curve to the display."

    Add-NOTask "NightOwl_EyeBreak" "break eye" `
        (New-NORepeatingTrigger -At $wakeAt.AddMinutes(12) -IntervalMinutes $cfg.eyeBreakMinutes) `
        "20-20-20 eye break. Skips when idle, gaming, fullscreen, or a protected calendar block."

    Add-NOTask "NightOwl_CalendarCheck" "calendarcheck" `
        (New-NORepeatingTrigger -At $wakeAt -IntervalMinutes 10) `
        "Auto-mute notifications during quiet-hours calendar blocks (Prayer Closet) and restore after."

    Add-NOTask "NightOwl_Posture" "break posture" `
        (New-NORepeatingTrigger -At $wakeAt.AddMinutes(35) -IntervalMinutes $cfg.postureBreakMinutes) `
        "Hourly stand-up reminder. Same skip rules as the eye break."

    Add-NOTask "NightOwl_GameCheck" "gamecheck" `
        (New-NORepeatingTrigger -At $wakeAt -IntervalMinutes 15) `
        "Track game session length against the configured budget."

    # -Scheduled lets the engine drop a run the clock no longer agrees with,
    # so a replayed overnight task can never announce bedtime at 11 AM.
    Add-NOTask "NightOwl_WindDown" "mode winddown -Scheduled" `
        (New-ScheduledTaskTrigger -Daily -At $windAt) `
        "Warm and dim the screen, restore notifications, start the wind-down."

    Add-NOTask "NightOwl_Bedtime" "mode sleep -Scheduled" `
        (New-ScheduledTaskTrigger -Daily -At $bedAt) `
        "Gentle late-night card and deep dim."

    Add-NOTask "NightOwl_AnimeSync" "sync" `
        (New-ScheduledTaskTrigger -Daily -At $wakeAt.AddMinutes(90)) `
        "Refresh the anime season cache and rebuild the Hub." $settingsCatchUp

    Add-NOTask "NightOwl_ExpSync" "expsync" `
        (New-ScheduledTaskTrigger -Daily -At $wakeAt.AddMinutes(20)) `
        "Regenerate the Solo Leveling dashboard - picks up last night's clean-wind-down bonus." $settingsCatchUp

    # The Chroma daemon is a long-running loop, not a periodic check - launched
    # once at logon rather than re-triggered on a schedule.
    Add-NOTask "NightOwl_ChromaStart" "chroma start" `
        (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME") `
        "Start the ambient RGB lighting daemon (keyboard/mouse follow the screen curve)."

    # Scoped to this user - an unscoped AtLogOn trigger means "any user" and
    # needs elevation to register.
    Add-NOTask "NightOwl_Logon" "mode auto" `
        (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME") `
        "Put the machine into the right mode for the time of day at logon."
}

# ------------------------------------------------------------- shortcuts ----

if (-not $SkipShortcuts) {
    Write-Host ""
    Write-Host "  Shortcuts" -ForegroundColor Cyan
    $sh = New-Object -ComObject WScript.Shell

    function Add-NOShortcut {
        param($Path, $LaunchArgs, $Desc, $IconIndex = 0)   # see Add-NOTask re: $Args
        $lnk = $sh.CreateShortcut($Path)
        $lnk.TargetPath       = "wscript.exe"
        $lnk.Arguments        = "`"$Vbs`" $LaunchArgs"
        $lnk.WorkingDirectory = $Root
        $lnk.Description      = $Desc
        $lnk.IconLocation     = "$env:SystemRoot\System32\imageres.dll,$IconIndex"
        $lnk.Save()
    }

    $desktop = [Environment]::GetFolderPath("Desktop")
    Add-NOShortcut (Join-Path $desktop "NightOwl Hub.lnk") "hub" "Open the NightOwl dashboard" 76
    Say "Desktop: NightOwl Hub" "Green"

    $startDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\NightOwl"
    New-Item -ItemType Directory -Force -Path $startDir | Out-Null
    Add-NOShortcut (Join-Path $startDir "NightOwl Hub.lnk")   "hub"            "Open the dashboard"  76
    Add-NOShortcut (Join-Path $startDir "Work mode.lnk")      "mode work"      "Quiet + fast"        104
    Add-NOShortcut (Join-Path $startDir "Game mode.lnk")      "mode game"      "Game Mode on"        15
    Add-NOShortcut (Join-Path $startDir "Anime mode.lnk")     "mode anime"     "No screen sleep"     171
    Add-NOShortcut (Join-Path $startDir "Wind-down.lnk")      "mode winddown"  "Warm + dim"          228
    Add-NOShortcut (Join-Path $startDir "Reset.lnk")          "mode reset"     "Back to defaults"    98
    Say "Start Menu: NightOwl (6 entries)" "Green"
}

# --------------------------------------------------------------- profile ----

if (-not $SkipProfile) {
    Write-Host ""
    Write-Host "  Shell profile" -ForegroundColor Cyan
    $profileSrc = Join-Path $Root "shell\profile-snippet.ps1"
    $marker     = "# --- NightOwl ---"
    $profileDir = Split-Path -Parent $PROFILE
    if (-not (Test-Path $profileDir)) { New-Item -ItemType Directory -Force -Path $profileDir | Out-Null }
    if (-not (Test-Path $PROFILE))    { New-Item -ItemType File -Force -Path $PROFILE | Out-Null }

    $current = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
    if ($current -and $current.Contains($marker)) {
        Say "already present in $PROFILE" "DarkGray"
    } else {
        Add-Content -Path $PROFILE -Value "`r`n$marker`r`n. `"$profileSrc`"`r`n# --- /NightOwl ---`r`n" -Encoding utf8
        Say "added to $PROFILE" "Green"
    }
}

# ------------------------------------------------------------ first build ----

Write-Host ""
Write-Host "  First build" -ForegroundColor Cyan
& (Join-Path $Bin "no.ps1") sync | ForEach-Object { Say $_ }

Write-Host ""
Write-Host "  Done." -ForegroundColor Magenta
Write-Host "  Open the dashboard from the desktop shortcut, or run: no hub" -ForegroundColor DarkGray
Write-Host ""
