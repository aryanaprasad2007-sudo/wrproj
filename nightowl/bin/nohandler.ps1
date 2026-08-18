<#
    Handles nightowl:// URLs fired from the Hub dashboard.

      nightowl://mode/work          -> no.ps1 mode work
      nightowl://break/eye          -> no.ps1 break eye
      nightowl://anime/watch/178025 -> no.ps1 anime watch 178025
      nightowl://warmer             -> no.ps1 warmer

    Registered under HKCU only, so it needs no elevation and uninstalls cleanly.
#>
param([Parameter(Position = 0)][string]$Url)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $Root "core\NightOwl.psm1") -Force

try {
    if (-not $Url) { exit 0 }

    # Browsers hand us "nightowl://mode/work/" - strip scheme, slashes, query.
    $path = $Url -replace '^\s*nightowl:(//)?', ''
    $path = ($path -split '[?#]')[0].Trim().Trim('/')
    $path = [uri]::UnescapeDataString($path)

    $parts = @($path -split '/' | Where-Object { $_ -ne "" })
    if ($parts.Count -eq 0) { exit 0 }

    $action = $parts[0].ToLower()
    $value  = ""
    $extra  = ""
    if ($parts.Count -ge 2) { $value = $parts[1] }
    if ($parts.Count -ge 3) { $extra = $parts[2] }

    Write-NOLog "uri: $Url -> $action '$value' '$extra'"

    & (Join-Path $PSScriptRoot "no.ps1") $action $value $extra
}
catch {
    Write-NOLog "URI ERROR [$Url]: $($_.Exception.Message)"
    exit 1
}
