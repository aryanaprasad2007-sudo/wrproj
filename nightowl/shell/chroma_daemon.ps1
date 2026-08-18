<#
    NightOwl ambient lighting daemon.

    Drives keyboard + mouse RGB via the Razer Chroma SDK's local REST API so
    the room follows the same circadian curve as the screen - neutral by day,
    warm at wind-down, a purple-pink accent in anime mode. Runs forever in the
    background; safe to kill and restart any time (re-registers its session).

    The Chroma SDK app-session URI changes every registration and the session
    itself expires without a heartbeat (~15s), so this can't be a one-shot
    script - it has to keep running and re-register if Razer Central restarts.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $Root "core\NightOwl.psm1") -Force -DisableNameChecking

$script:ChromaUri = $null
$script:LastColor = $null

function Connect-NOChroma {
    $body = @{
        title            = "NightOwl"
        description      = "Ambient lighting synced to the circadian screen curve"
        author           = @{ name = "NightOwl"; contact = "n/a" }
        device_supported = @("keyboard", "mouse")
        category         = "application"
    } | ConvertTo-Json

    $resp = Invoke-RestMethod -Uri "http://localhost:54235/razer/chromasdk" `
                -Method Post -Body $body -ContentType "application/json" -TimeoutSec 5
    Write-NOLog "chroma: session registered ($($resp.uri))"
    return $resp.uri
}

function Send-NOChromaHeartbeat {
    param([string]$Uri)
    Invoke-RestMethod -Uri "$Uri/heartbeat" -Method Put -TimeoutSec 5 | Out-Null
}

function Set-NOChromaColor {
    <# Chroma packs color as 0x00BBGGRR - blue high, green mid, red low. #>
    param([string]$Uri, [int]$R, [int]$G, [int]$B)
    $packed = ($B -shl 16) -bor ($G -shl 8) -bor $R
    $body = @{ effect = "CHROMA_STATIC"; param = @{ color = $packed } } | ConvertTo-Json
    Invoke-RestMethod -Uri "$Uri/keyboard" -Method Put -Body $body -ContentType "application/json" -TimeoutSec 5 | Out-Null
    Invoke-RestMethod -Uri "$Uri/mouse"    -Method Put -Body $body -ContentType "application/json" -TimeoutSec 5 | Out-Null
}

function Get-NOAccentColor {
    <#  Anime mode gets a fun purple-pink accent (a "vibe", not photometric
        accuracy - it's the one mode where that fits better than the curve).
        Everything else follows the same Kelvin curve as the screen, so the
        room and the monitor warm up together. #>
    $st = Get-NOStateData
    if ($st.mode -eq "anime") {
        return [pscustomobject]@{ R = 205; G = 110; B = 235 }
    }

    $w = Get-NOAutoWarmth
    $offset = 0
    if ($st.PSObject.Properties.Name -contains 'kelvinOffset') { $offset = [int]$st.kelvinOffset }
    $k = [math]::Max(1800, [math]::Min(6500, $w.Kelvin + $offset))
    $rgb = Get-NOKelvinRgb -Kelvin $k
    return [pscustomobject]@{
        R = [int][math]::Round($rgb.R * 255)
        G = [int][math]::Round($rgb.G * 255)
        B = [int][math]::Round($rgb.B * 255)
    }
}

Write-NOLog "chroma daemon started"

while ($true) {
    try {
        if (-not $script:ChromaUri) { $script:ChromaUri = Connect-NOChroma }
        Send-NOChromaHeartbeat -Uri $script:ChromaUri

        $c = Get-NOAccentColor
        $key = "$($c.R),$($c.G),$($c.B)"
        if ($key -ne $script:LastColor) {
            Set-NOChromaColor -Uri $script:ChromaUri -R $c.R -G $c.G -B $c.B
            $script:LastColor = $key
            Write-NOLog "chroma -> rgb($($c.R),$($c.G),$($c.B))"
        }
    }
    catch {
        Write-NOLog "chroma: lost session, will reconnect ($($_.Exception.Message))"
        $script:ChromaUri = $null   # Chroma Connect probably restarted - re-register next loop
    }
    Start-Sleep -Seconds 5
}
