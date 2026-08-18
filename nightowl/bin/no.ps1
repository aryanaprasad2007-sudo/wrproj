<#
    NightOwl CLI - the one entrypoint everything else drives.
    Scheduled tasks, global hotkeys, the Hub dashboard and the `no` shell
    function all route through here.

    Examples:
      no.ps1 status
      no.ps1 mode work
      no.ps1 break eye
      no.ps1 warmer
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("status","mode","screen","warmer","cooler","warmthreset","break",
                 "gamecheck","calendarcheck","hub","sync","launch","steam","nudge","anime","chroma","focus","expsync","help")]
    [string]$Action = "status",

    [Parameter(Position = 1)] [string]$Value = "",
    [Parameter(Position = 2)] [string]$Extra = "",

    # Set by the NightOwl_* scheduled tasks, never by a human. Lets the engine
    # tell "it is genuinely bedtime" apart from "Windows just replayed a run it
    # missed while the machine was off" - see Invoke-NOMode's stale-fire guard.
    [switch]$Scheduled
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $Root "core\NightOwl.psm1") -Force

$cfg = Get-NOConfig

function Get-NOPy {
    $p = (Get-Command py -ErrorAction SilentlyContinue)
    if ($p) { return $p.Source }
    return "python"
}

function Invoke-NOSync {
    $py = Get-NOPy
    $script = Join-Path $Root "python\build_hub.py"
    & $py -3 $script 2>&1 | ForEach-Object { Write-NOLog "sync: $_" }
}

function Invoke-NOExpSync {
    # Solo-Leveling-System is a sibling of nightowl/, both under wrproj/ -
    # regenerates its live dashboard so completed focus blocks and clean
    # wind-down nights show up as EXP without a manual step. Silently does
    # nothing if that project isn't present.
    $bridge = Join-Path (Split-Path -Parent $Root) "Solo-Leveling-System\system_bridge.py"
    if (-not (Test-Path $bridge)) { return }
    $py = Get-NOPy
    & $py -3 $bridge 2>&1 | ForEach-Object { Write-NOLog "expsync: $_" }
}

try {
    switch ($Action) {

        "status" {
            $s = Get-NOStatus
            $sc = Get-NOSchedule
            $bar = ""
            $span = $sc.AwakeSpanMin
            $done = [math]::Max(0, [math]::Min($span, $sc.MinutesAwake))
            $filled = [int](24 * $done / $span)
            for ($i = 0; $i -lt 24; $i++) { if ($i -lt $filled) { $bar += "#" } else { $bar += "." } }
            ""
            "  NightOwl  |  $($s.Now)  |  $($s.Phase.ToUpper())"
            "  [$bar]  $($s.HoursAwake)h awake"
            ""
            "  mode          $($s.Mode)"
            "  screen        $($s.TargetKelvin)K"
            "  bedtime       $($s.Bedtime)   ($($s.MinutesToBed) min)"
            "  game running  $($s.GameRunning)"
            "  idle          $($s.IdleSeconds)s"
            ""
        }

        "mode" {
            if (-not $Value) { throw "mode needs a name: work|game|anime|winddown|sleep|reset|auto" }
            $m = Invoke-NOMode -Mode $Value.ToLower() -Scheduled:$Scheduled
            if ($null -eq $m) { "mode -> skipped (stale scheduled run)" } else { "mode -> $m" }
        }

        "screen" {
            # Anime mode pins a fixed temperature on purpose - don't let the
            # 15-minute sync drag it back onto the curve mid-episode.
            $st = Get-NOStateData
            if ($st.mode -eq "anime") { "screen sync skipped (anime mode holds its own temperature)"; break }
            $r = Sync-NOScreen
            "screen -> $($r.Kelvin)K @ $([math]::Round($r.Brightness*100))%  (curve $($r.CurveKelvin)K, offset $($r.Offset))"
        }

        "warmer" {
            $o = Set-NOWarmthOffset -Delta -300
            $r = Sync-NOScreen
            Show-NONudge -Title "Warmer" -Glyph "-" -Seconds 3 -Message "Screen at $($r.Kelvin)K (bias $o K)."
        }

        "cooler" {
            $o = Set-NOWarmthOffset -Delta 300
            $r = Sync-NOScreen
            Show-NONudge -Title "Cooler" -Glyph "+" -Seconds 3 -Message "Screen at $($r.Kelvin)K (bias $o K)."
        }

        "warmthreset" {
            Set-NOWarmthOffset -Clear | Out-Null
            $r = Sync-NOScreen
            "screen -> $($r.Kelvin)K (bias cleared)"
        }

        "break" {
            $kind = "eye"; if ($Value) { $kind = $Value.ToLower() }
            $st = Get-NOStateData

            # Don't interrupt: away from the desk, mid-game, or in a fullscreen app.
            $idle = Get-NOIdleSeconds
            if ($idle -gt $cfg.idleSkipSeconds) { Write-NOLog "break skipped (idle ${idle}s)"; break }
            if (Test-NOGameRunning)             { Write-NOLog "break skipped (game running)"; break }
            if (Test-NOFullscreen)              { Write-NOLog "break skipped (fullscreen)"; break }
            if ($st.mode -eq "game" -or $st.mode -eq "anime") { Write-NOLog "break skipped (mode $($st.mode))"; break }

            $protected = Test-NOProtectedBlock
            if ($protected) { Write-NOLog "break skipped (protected block: $($protected.title))"; break }

            if ($kind -eq "posture") {
                $msgs = @(
                    "If it's a good moment - stand up, roll your shoulders back, look at the ceiling, one slow breath.",
                    "Hour mark. Sixty seconds out of the chair whenever you can, no rush.",
                    "Worth a stretch and something to drink, if you've got a natural pause."
                )
                Show-NONudge -Title "Stretch break" -Glyph "^" -Seconds 12 -Message ($msgs | Get-Random)
            } else {
                $msgs = @(
                    "Something 20 feet away, 20 seconds. Your eyes have been holding one distance for a while.",
                    "Rest your eyes on the furthest thing in the room for a bit whenever you can.",
                    "Quick one: 20 feet, 20 seconds, and a few deliberate blinks."
                )
                Show-NONudge -Title "Eye break" -Glyph "20" -Seconds 10 -Message ($msgs | Get-Random)
            }

            $st | Add-Member -NotePropertyName lastBreak -NotePropertyValue (Get-Date).ToString("o") -Force
            Save-NOStateData $st
        }

        "gamecheck" {
            $st = Get-NOStateData
            $running = Test-NOGameRunning
            $since = $null
            if ($st.PSObject.Properties.Name -contains 'gameSince' -and $st.gameSince) {
                try { $since = [datetime]::Parse($st.gameSince) } catch { }
            }

            if ($running -and -not $since) {
                $st | Add-Member -NotePropertyName gameSince -NotePropertyValue (Get-Date).ToString("o") -Force
                $st | Add-Member -NotePropertyName gameNudged -NotePropertyValue $false -Force
                Save-NOStateData $st
                Write-NOLog "game session started"
            }
            elseif (-not $running -and $since) {
                $mins = [math]::Round(((Get-Date) - $since).TotalMinutes)
                $st | Add-Member -NotePropertyName gameSince -NotePropertyValue "" -Force
                $st | Add-Member -NotePropertyName lastGameMinutes -NotePropertyValue $mins -Force
                Save-NOStateData $st
                Write-NOLog "game session ended ($mins min)"
            }
            elseif ($running -and $since) {
                $mins = [math]::Round(((Get-Date) - $since).TotalMinutes)
                $nudged = $false
                if ($st.PSObject.Properties.Name -contains 'gameNudged') { $nudged = [bool]$st.gameNudged }
                if ($mins -ge $cfg.gameBudgetMinutes -and -not $nudged -and -not (Test-NOFullscreen)) {
                    $h = [math]::Round($mins / 60, 1)
                    Show-NONudge -Title "$h hours in" -Glyph "G" -Seconds 11 -Message "Past the $($cfg.gameBudgetMinutes)-minute mark you picked. Not a stop sign, and not a problem - just so it's a choice rather than a drift. Carry on if you're enjoying it."
                    $st | Add-Member -NotePropertyName gameNudged -NotePropertyValue $true -Force
                    Save-NOStateData $st
                }
            }
        }

        "calendarcheck" {
            # Prayer Closet blocks are fixed points in the real calendar, not a
            # mode - so this just mutes/restores notifications around them
            # rather than touching power plan, monitor timeout or wallpaper.
            $st = Get-NOStateData
            $quiet = Test-NOQuietBlock
            $wasQuiet = $false
            if ($st.PSObject.Properties.Name -contains 'quietActive') { $wasQuiet = [bool]$st.quietActive }

            if ($quiet -and -not $wasQuiet) {
                $prevNotif = Get-NONotifications
                Set-NONotifications $false
                $st | Add-Member -NotePropertyName quietActive -NotePropertyValue $true -Force
                $st | Add-Member -NotePropertyName quietPrevNotif -NotePropertyValue $prevNotif -Force
                Save-NOStateData $st
                Write-NOLog "quiet hours started ($($quiet.title))"
            }
            elseif (-not $quiet -and $wasQuiet) {
                $restore = $true
                if ($st.PSObject.Properties.Name -contains 'quietPrevNotif') { $restore = [bool]$st.quietPrevNotif }
                Set-NONotifications $restore
                $st | Add-Member -NotePropertyName quietActive -NotePropertyValue $false -Force
                Save-NOStateData $st
                Write-NOLog "quiet hours ended, notifications -> $restore"
            }
        }

        "hub" {
            # The static hub is retired: psychowl (the tracker process at
            # wrproj/src/dashboard.py) serves the live hub plus FocusFlow,
            # Grimoire, the Docket data and the briefs from one origin.
            # If the server is down, start it headless first. pythonw is
            # resolved from the interpreter itself because the pyw shim on
            # PATH is a zero-byte alias that no-ops under Start-Process.
            #  The HTTP ping alone is not enough to decide whether to start one.
            #  A server takes ~3s to come up, so two `no hub` calls inside that
            #  window (double-click, or the Ctrl+Alt+H hotkey repeating) both
            #  see "down" and both launch. That is not a harmless duplicate:
            #  http.server sets allow_reuse_address, so BOTH bind 8787 and
            #  requests land on whichever accepts first, while both processes
            #  claim the camera - and the camera has exactly one owner.
            #  Observed live on 2026-08-17 (pids 14144 + 47692, 1s apart).
            #  So also check for an already-starting process, not just a
            #  already-answering one.
            $hubUrl = "http://127.0.0.1:8787/"
            $up = $false
            try {
                $ping = Invoke-WebRequest -Uri ($hubUrl + "api/psychowl") -UseBasicParsing -TimeoutSec 2
                $up = ($ping.StatusCode -eq 200)
            } catch { $up = $false }

            if (-not $up) {
                $starting = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
                            Where-Object { $_.CommandLine -like "*dashboard.py*" })
                if ($starting) {
                    Write-NOLog "psychowl already starting (pid $($starting[0].ProcessId)) - not launching a second"
                    $up = $true      # let it finish booting; just open the page
                }
            }

            if (-not $up) {
                $py = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
                if ($py) {
                    $pyw = $py.Trim().Replace("python.exe", "pythonw.exe")
                    $dash = Join-Path (Split-Path $Root -Parent) "src\dashboard.py"
                    if ((Test-Path $pyw) -and (Test-Path $dash)) {
                        Start-Process -FilePath $pyw -ArgumentList @($dash) -WindowStyle Hidden
                        Start-Sleep -Seconds 3
                        Write-NOLog "psychowl server started"
                    }
                }
            }
            $brave = $cfg.paths.brave
            if (Test-Path $brave) { Start-Process $brave -ArgumentList @($hubUrl) }
            else { Start-Process $hubUrl }
        }

        "sync" {
            Invoke-NOSync
            "hub rebuilt"
        }

        "launch" {
            $key = $Value.ToLower()
            $p = $cfg.paths.$key
            if (-not $p) { throw "unknown app '$key'" }
            if (-not (Test-Path $p)) { throw "not installed: $p" }
            Start-Process $p
            Write-NOLog "launch $key"
        }

        "steam" {
            if (-not $Value) { throw "steam needs an appid" }
            Start-Process "steam://rungameid/$Value"
            Write-NOLog "steam launch $Value"
        }

        "anime" {
            $op = $Value.ToLower()
            if ($op -notin @("track","untrack","watch","unwatch")) {
                throw "anime needs track|untrack|watch|unwatch <id>"
            }
            if (-not $Extra) { throw "anime $op needs a show id" }
            $py = Get-NOPy
            $s  = Join-Path $Root "python\anime_sync.py"
            & $py -3 $s "--$op" $Extra 2>&1 | ForEach-Object { Write-NOLog "anime: $_" }
            Invoke-NOSync   # rebuild so the reloaded page shows the change
            "anime $op $Extra"
        }

        "chroma" {
            $op = "start"; if ($Value) { $op = $Value.ToLower() }
            $daemonPath = Join-Path $Root "shell\chroma_daemon.ps1"
            $running = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
                       Where-Object { $_.CommandLine -like "*chroma_daemon.ps1*" })

            switch ($op) {
                "start" {
                    if ($running) { "chroma daemon already running (pid $($running[0].ProcessId))"; break }
                    Start-Process powershell.exe -ArgumentList @(
                        "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$daemonPath`""
                    ) -WindowStyle Hidden
                    "chroma daemon started"
                }
                "stop" {
                    if (-not $running) { "chroma daemon not running"; break }
                    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
                    "chroma daemon stopped ($($running.Count) process(es))"
                }
                "status" {
                    if ($running) { "running (pid $($running[0].ProcessId))" } else { "not running" }
                }
                default { throw "chroma needs start|stop|status" }
            }
        }

        "focus" {
            # Logs a completed focus-timer block so the Solo Leveling System
            # bridge can credit real EXP for it. Deliberately dumb here -
            # aggregation/crediting logic lives entirely in that project's own
            # bridge script, not duplicated in NightOwl.
            if ($Value -ne "complete") { throw "focus needs: complete <minutes>" }
            $mins = 0; [int]::TryParse($Extra, [ref]$mins) | Out-Null
            if ($mins -le 0) { throw "focus complete needs a positive minute count" }

            $path = Join-Path $Root "data\focus_sessions.json"
            $raw = $null
            if (Test-Path $path) {
                try { $raw = Get-Content $path -Raw | ConvertFrom-Json } catch { $raw = $null }
            }
            # @(pipeline-result-that-may-already-be-an-array) is a classic PS5.1
            # trap: if ConvertFrom-Json's array comes through the pipe as one
            # object, @() wraps it AGAIN instead of flattening it. Check the
            # type explicitly instead of trusting @() to do the right thing.
            if ($null -eq $raw)              { $list = @() }
            elseif ($raw -is [System.Array]) { $list = $raw }
            else                              { $list = @($raw) }

            $list = @($list) + [pscustomobject]@{
                date        = (Get-Date).ToString("yyyy-MM-dd")
                minutes     = $mins
                completedAt = (Get-Date).ToString("o")
            }
            # ConvertTo-Json separately drops the [ ] wrapper for an exactly-
            # one-element array, which would corrupt the shape on the next
            # read - force it back on.
            $json = $list | ConvertTo-Json -Depth 4
            if ($list.Count -eq 1) { $json = "[$json]" }
            $json | Out-File -FilePath $path -Encoding utf8
            Write-NOLog "focus session logged: ${mins}m"
            Invoke-NOExpSync
            "logged ${mins}m focus session"
        }

        "expsync" {
            Invoke-NOExpSync
        }

        "nudge" {
            $t = "NightOwl"; if ($Value) { $t = $Value }
            $m = ""; if ($Extra) { $m = $Extra }
            Show-NONudge -Title $t -Message $m
        }

        "help" {
            @"
  no status                 where you are in the day
  no mode <name>            work | game | anime | winddown | sleep | reset | auto
  no screen                 re-apply the circadian colour curve
  no warmer / no cooler     bias the screen by 300K (sticks across syncs)
  no warmthreset            drop the bias
  no break [eye|posture]    show a break card (skips if idle/gaming/fullscreen/protected block)
  no gamecheck              track game session length against your budget
  no calendarcheck          enter/exit quiet hours for the active calendar block
  no chroma [start|stop|status]   ambient RGB daemon, follows the screen curve
  no focus complete <min>   log a completed focus block (credits Solo Leveling EXP)
  no expsync                regenerate the Solo Leveling dashboard now
  no hub                    open psychowl (starts its server if down)
  no sync                   rebuild dashboard data only
  no launch <app>           brave vlc steam obsidian vscode notion obs govee ...
  no steam <appid>          launch a Steam game directly
"@
        }
    }
}
catch {
    Write-NOLog "ERROR [$Action $Value]: $($_.Exception.Message)"
    Write-Error $_
    exit 1
}
