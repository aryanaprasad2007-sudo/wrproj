# Kills any leftover instances from a prior run before starting fresh
Get-Process powershell -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowTitle -like "SYSTEM::*" -or $_.MainWindowTitle -eq "safe uwu"
} | Stop-Process -Force -ErrorAction SilentlyContinue

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

Add-Type -AssemblyName System.Windows.Forms
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$screenW = $bounds.Width
$screenH = $bounds.Height

$dir = "C:\Users\aware\OneDrive\Desktop\wrproj\hackerscreen"

# 3x2 grid for the hacker windows
$cols = 3
$rows = 2
$cellW = [int]($screenW / $cols)
$cellH = [int]($screenH / $rows)

function Start-Positioned($scriptPath, $x, $y, $w, $h) {
    $p = Start-Process powershell.exe -ArgumentList "-NoLogo","-NoExit","-ExecutionPolicy","Bypass","-File","$scriptPath" -PassThru
    $tries = 0
    while ($p.MainWindowHandle -eq 0 -and $tries -lt 40) {
        Start-Sleep -Milliseconds 100
        $p.Refresh()
        $tries++
    }
    if ($p.MainWindowHandle -ne 0) {
        [Win32]::MoveWindow($p.MainWindowHandle, $x, $y, $w, $h, $true) | Out-Null
    }
    return $p
}

# hacker windows fill the grid
for ($r = 0; $r -lt $rows; $r++) {
    for ($c = 0; $c -lt $cols; $c++) {
        Start-Positioned "$dir\hack.ps1" ($c * $cellW) ($r * $cellH) $cellW $cellH | Out-Null
    }
}

# cute pink window, large, centered on top of everything
$cuteW = [int]($screenW * 0.5)
$cuteH = [int]($screenH * 0.5)
$cuteX = [int](($screenW - $cuteW) / 2)
$cuteY = [int](($screenH - $cuteH) / 2)
$cuteProc = Start-Positioned "$dir\cute.ps1" $cuteX $cuteY $cuteW $cuteH
if ($cuteProc.MainWindowHandle -ne 0) {
    [Win32]::SetForegroundWindow($cuteProc.MainWindowHandle) | Out-Null
}
