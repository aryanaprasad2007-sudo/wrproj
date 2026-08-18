# NightOwl shell integration - dot-sourced from the PowerShell profile.
# Kept deliberately cheap: no network, no module import until you actually
# call something, so shell startup stays instant.

$Global:NightOwlRoot = "C:\Users\aware\OneDrive\Desktop\wrproj\nightowl"

function no {
    <#  .SYNOPSIS  NightOwl control. Run `no help` for the verb list. #>
    & (Join-Path $Global:NightOwlRoot "bin\no.ps1") @args
}

function work     { no mode work }
function game     { no mode game }
function anime    { no mode anime }
function winddown { no mode winddown }
function hub      { no hub }
function warmer   { no warmer }
function cooler   { no cooler }
function chroma   { no chroma @args }

function bedtime {
    <# How long until bed, in one line. #>
    Import-Module (Join-Path $Global:NightOwlRoot "core\NightOwl.psm1") -Force -DisableNameChecking
    $s = Get-NOSchedule
    if ($s.MinutesToBed -lt 0) {
        Write-Host ("  {0} past bedtime." -f ([timespan]::FromMinutes(-$s.MinutesToBed).ToString("h\hmm\m"))) -ForegroundColor Yellow
    } else {
        Write-Host ("  {0} until bed ({1})." -f ([timespan]::FromMinutes($s.MinutesToBed).ToString("h\hmm\m")), $s.Bed.ToString("HH:mm")) -ForegroundColor Magenta
    }
}

# One quiet line at shell start so the clock is always in view.
function Show-NightOwlLine {
    $cfgPath = Join-Path $Global:NightOwlRoot "config.json"
    if (-not (Test-Path $cfgPath)) { return }
    $c = Get-Content $cfgPath -Raw | ConvertFrom-Json

    $now  = Get-Date
    $wp   = $c.wake.Split(":")
    $wake = $now.Date.AddHours([int]$wp[0]).AddMinutes([int]$wp[1])
    if ($now -lt $wake) { $wake = $wake.AddDays(-1) }
    $bp  = $c.bedtime.Split(":")
    $bed = $wake.Date.AddHours([int]$bp[0]).AddMinutes([int]$bp[1])
    if ($bed -le $wake) { $bed = $bed.AddDays(1) }

    $toBed = [math]::Round(($bed - $now).TotalMinutes)
    $awake = [math]::Round(($now - $wake).TotalMinutes / 60, 1)

    if ($toBed -lt 0) {
        $col = "Yellow"; $tail = "{0}h past bedtime" -f ([math]::Round(-$toBed / 60, 1))
    } elseif ($toBed -lt 90) {
        $col = "Magenta"; $tail = "{0}m to bed" -f $toBed
    } else {
        $col = "DarkGray"; $tail = "{0}h to bed" -f ([math]::Round($toBed / 60, 1))
    }

    Write-Host ""
    Write-Host ("  night owl  ") -NoNewline -ForegroundColor Magenta
    Write-Host ("{0}h awake  |  {1}" -f $awake, $tail) -ForegroundColor $col
    Write-Host ""
}

Show-NightOwlLine
