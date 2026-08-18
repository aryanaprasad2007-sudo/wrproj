<#
    Reverses everything install.ps1 did, and puts the display, power plan and
    notification settings back to Windows defaults.

    The nightowl folder itself is left alone - delete it by hand if you want it gone.
#>
[CmdletBinding()]
param([switch]$KeepFolder = $true)

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot

function Say { param($m, $c = "Gray") Write-Host "  $m" -ForegroundColor $c }

Write-Host ""
Write-Host "  NightOwl uninstaller" -ForegroundColor Magenta
Write-Host ""

# ------------------------------------------------------------------ tasks ----
Write-Host "  Scheduled tasks" -ForegroundColor Cyan
$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like "NightOwl_*" }
if ($tasks) {
    foreach ($t in $tasks) {
        Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
        Say "removed $($t.TaskName)" "Green"
    }
} else { Say "none found" "DarkGray" }

# --------------------------------------------------------------- protocol ----
Write-Host ""
Write-Host "  URL protocol" -ForegroundColor Cyan
$proto = "HKCU:\Software\Classes\nightowl"
if (Test-Path $proto) {
    Remove-Item -Path $proto -Recurse -Force
    Say "removed nightowl://" "Green"
} else { Say "not registered" "DarkGray" }

# -------------------------------------------------------------- shortcuts ----
Write-Host ""
Write-Host "  Shortcuts" -ForegroundColor Cyan
$desktopLnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "NightOwl Hub.lnk"
if (Test-Path $desktopLnk) { Remove-Item $desktopLnk -Force; Say "removed desktop shortcut" "Green" }
$startDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\NightOwl"
if (Test-Path $startDir) { Remove-Item $startDir -Recurse -Force; Say "removed Start Menu folder" "Green" }

# ---------------------------------------------------------------- profile ----
Write-Host ""
Write-Host "  Shell profile" -ForegroundColor Cyan
if (Test-Path $PROFILE) {
    $lines = Get-Content $PROFILE
    $out = @(); $skip = $false; $found = $false
    foreach ($l in $lines) {
        if ($l -match '^\s*#\s*---\s*NightOwl\s*---')  { $skip = $true; $found = $true; continue }
        if ($l -match '^\s*#\s*---\s*/NightOwl\s*---') { $skip = $false; continue }
        if (-not $skip) { $out += $l }
    }
    if ($found) {
        Set-Content -Path $PROFILE -Value $out -Encoding utf8
        Say "removed NightOwl block from $PROFILE" "Green"
    } else { Say "no NightOwl block found" "DarkGray" }
}

# ------------------------------------------------------ restore the system ----
Write-Host ""
Write-Host "  Restoring Windows defaults" -ForegroundColor Cyan
try {
    Import-Module (Join-Path $Root "core\NightOwl.psm1") -Force -DisableNameChecking
    Reset-NOScreen
    Set-NONotifications $true
    Set-NOPowerPlan "Balanced"
    Set-NOMonitorTimeout 15
    Set-NOGameMode $false
    Say "screen gamma, notifications, power plan, Game Mode restored" "Green"
} catch {
    Say "could not import module - resetting gamma directly" "Yellow"
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class NOReset {
  [StructLayout(LayoutKind.Sequential)]
  public struct RAMP {
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=256)] public UInt16[] Red;
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=256)] public UInt16[] Green;
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=256)] public UInt16[] Blue;
  }
  [DllImport("gdi32.dll")]  public static extern bool SetDeviceGammaRamp(IntPtr hdc, ref RAMP r);
  [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr h);
  public static void Flat() {
    RAMP r = new RAMP();
    r.Red = new UInt16[256]; r.Green = new UInt16[256]; r.Blue = new UInt16[256];
    for (int i=0;i<256;i++){ UInt16 v=(UInt16)Math.Min(65535, i*256); r.Red[i]=v; r.Green[i]=v; r.Blue[i]=v; }
    SetDeviceGammaRamp(GetDC(IntPtr.Zero), ref r);
  }
}
"@
    [NOReset]::Flat()
}

# ------------------------------------------------------------ AutoHotkey ----
Write-Host ""
Write-Host "  Hotkeys" -ForegroundColor Cyan
Get-Process AutoHotkey* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$startup = [Environment]::GetFolderPath("Startup")
$ahkLnk = Join-Path $startup "NightOwl Hotkeys.lnk"
if (Test-Path $ahkLnk) { Remove-Item $ahkLnk -Force; Say "removed hotkey autostart" "Green" }
else { Say "no hotkey autostart found" "DarkGray" }

# ------------------------------------------------------------- Chroma ----
Write-Host ""
Write-Host "  Ambient lighting" -ForegroundColor Cyan
$chromaProcs = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
                 Where-Object { $_.CommandLine -like "*chroma_daemon.ps1*" })
if ($chromaProcs) {
    $chromaProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Say "stopped chroma daemon ($($chromaProcs.Count) process(es))" "Green"
} else { Say "chroma daemon not running" "DarkGray" }

Write-Host ""
Write-Host "  Done. The nightowl folder is still at:" -ForegroundColor Magenta
Write-Host "  $Root" -ForegroundColor DarkGray
Write-Host "  PowerToys and AutoHotkey were installed separately - remove them via Settings > Apps if you want." -ForegroundColor DarkGray
Write-Host ""
