<#
    Launcher.

    `python` on this machine resolves to a WindowsApps shim pointing at 3.14,
    which has none of this project's packages. The working interpreter is the
    3.12 install that opencv / ultralytics / psutil actually live in. Rather
    than rely on PATH order -- which changes whenever anything installs a new
    Python -- this resolves an interpreter by TESTING it for cv2 and uses the
    first one that passes.

    Usage:
        .\run.ps1 validate present 3    measure camera error, 3 min at desk
        .\run.ps1 validate absent 1     measure camera error, 1 min out
        .\run.ps1 validate report       re-score the last saved run
        .\run.ps1 log                   start the mode logger
        .\run.ps1 today                 print today's timeline
        .\run.ps1 screen                one screen-sensor reading
        .\run.ps1 screen watch          screen sensor every 2s
        .\run.ps1 record 30             record 30 min of footage
        .\run.ps1 doctor                show which interpreter is in use

    Override the interpreter by setting $env:WRPROJ_PYTHON to a full path.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "doctor",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-Python {
    $candidates = @()
    if ($env:WRPROJ_PYTHON) { $candidates += $env:WRPROJ_PYTHON }
    $candidates += Join-Path $root ".venv\Scripts\python.exe"
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    $candidates += "C:\Python312\python.exe"

    foreach ($c in $candidates) {
        if (-not (Test-Path $c)) { continue }
        # Presence on disk proves nothing -- the whole bug was an interpreter
        # that exists and runs but has no cv2. Test the import itself.
        & $c -c "import cv2" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    return $null
}

$py = Resolve-Python
if (-not $py) {
    Write-Host "[!] No Python with opencv installed could be found." -ForegroundColor Red
    Write-Host ""
    Write-Host "    Tried:" -ForegroundColor DarkGray
    Write-Host "      `$env:WRPROJ_PYTHON, .venv, Python312, Python313, Python311" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "    Fix by installing the deps into a specific interpreter:"
    Write-Host '      & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pip install -r requirements.txt'
    Write-Host ""
    Write-Host "    Or point at one you already have:"
    Write-Host '      $env:WRPROJ_PYTHON = "C:\path\to\python.exe"'
    exit 1
}

# Friendly name -> script. Keeps the surface small; anything not listed is
# treated as a script name under src/ so nothing is locked out.
$scripts = @{
    "validate" = "validate_camera.py"
    "log"      = "mode_log.py"
    "today"    = "mode_log.py"
    "screen"   = "window_sensor.py"
    "record"   = "record_session.py"
    "analyze"  = "analyze_session.py"
}

if ($Command -eq "doctor") {
    Write-Host "  interpreter : $py"
    & $py -c "import sys, cv2; print('  version     : ' + sys.version.split()[0]); print('  opencv      : ' + cv2.__version__)"
    foreach ($m in @("ultralytics", "psutil", "numpy")) {
        & $py -c "import $m" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  $($m.PadRight(12)): ok"
        } else {
            Write-Host "  $($m.PadRight(12)): MISSING" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Write-Host "  Commands: validate | log | today | screen | record | analyze"
    exit 0
}

if (-not $scripts.ContainsKey($Command)) {
    $maybe = Join-Path $root "src\$Command"
    if (-not $Command.EndsWith(".py")) { $maybe = "$maybe.py" }
    if (Test-Path $maybe) {
        $script = $maybe
    } else {
        Write-Host "[!] Unknown command '$Command'." -ForegroundColor Red
        Write-Host "    Try: validate | log | today | screen | record | analyze | doctor"
        exit 1
    }
} else {
    $script = Join-Path $root "src\$($scripts[$Command])"
}

# `today` is mode_log.py's own subcommand, so pass it through as an argument.
$argv = @()
if ($Command -eq "today") { $argv += "today" }
if ($Rest) { $argv += $Rest }

& $py $script @argv
exit $LASTEXITCODE
