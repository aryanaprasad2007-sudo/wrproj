# Generates the PWA icon set. Re-run with:
#   powershell -ExecutionPolicy Bypass -File tools\make_icons.ps1
Add-Type -AssemblyName System.Drawing

$OutDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'icons'
New-Item -ItemType Directory -Force $OutDir | Out-Null

function New-RoundedPath([single]$x, [single]$y, [single]$w, [single]$h, [single]$r) {
  $p = New-Object System.Drawing.Drawing2D.GraphicsPath
  $d = $r * 2
  if ($d -le 0) { $p.AddRectangle((New-Object System.Drawing.RectangleF($x, $y, $w, $h))); return $p }
  $p.AddArc($x, $y, $d, $d, 180, 90)
  $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
  $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
  $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
  $p.CloseFigure()
  return $p
}

function C([string]$hex, [int]$a = 255) {
  $c = [System.Drawing.ColorTranslator]::FromHtml($hex)
  return [System.Drawing.Color]::FromArgb($a, $c.R, $c.G, $c.B)
}

function Write-Icon([int]$size, [string]$file, [bool]$maskable) {
  $bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  $g.Clear([System.Drawing.Color]::Transparent)

  # --- background plate -----------------------------------------------------
  # Maskable icons get squared corners: the OS applies its own mask, and any
  # transparency inside the safe zone shows up as a chipped edge.
  $radius = if ($maskable) { 0 } else { $size * 0.225 }
  $plate = New-RoundedPath 0 0 $size $size $radius
  $rect = New-Object System.Drawing.RectangleF(0, 0, $size, $size)
  $bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush($rect, (C '#2c1b52'), (C '#150c28'), 55.0)
  $g.FillPath($bg, $plate)

  # violet bloom in the upper-left, echoing the app's aurora
  $glowPath = New-Object System.Drawing.Drawing2D.GraphicsPath
  $glowPath.AddEllipse(-$size * 0.35, -$size * 0.45, $size * 1.25, $size * 1.2)
  $glow = New-Object System.Drawing.Drawing2D.PathGradientBrush($glowPath)
  $glow.CenterColor = C '#8b5cf6' 150
  $glow.SurroundColors = @((C '#8b5cf6' 0))
  $g.SetClip($plate)
  $g.FillPath($glow, $glowPath)
  $g.ResetClip()

  # --- calendar glyph -------------------------------------------------------
  # 60% of the canvas on maskable so it stays inside the 80% safe circle.
  $scale = if ($maskable) { 0.60 } else { 0.72 }
  $gs = $size * $scale
  $ox = ($size - $gs) / 2.0
  $oy = ($size - $gs) / 2.0 + $gs * 0.045

  # hanger rings
  $ringW = $gs * 0.085
  $ringH = $gs * 0.19
  $ringY = $oy - $ringH * 0.55
  $ringBrush = New-Object System.Drawing.SolidBrush((C '#c9b3ff'))
  foreach ($fx in @(0.255, 0.66)) {
    $rp = New-RoundedPath ($ox + $gs * $fx) $ringY $ringW $ringH ($ringW / 2)
    $g.FillPath($ringBrush, $rp)
  }

  # body
  $bodyY = $oy + $gs * 0.09
  $bodyH = $gs * 0.87
  $bodyR = $gs * 0.15
  $body = New-RoundedPath $ox $bodyY $gs $bodyH $bodyR
  $bodyRect = New-Object System.Drawing.RectangleF($ox, $bodyY, $gs, $bodyH)
  $bodyBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush($bodyRect, (C '#efe8ff'), (C '#c9b3ff'), 70.0)
  $g.FillPath($bodyBrush, $body)

  # header band, clipped to the rounded top
  $g.SetClip($body)
  $bandH = $bodyH * 0.26
  $bandRect = New-Object System.Drawing.RectangleF($ox, $bodyY, $gs, $bandH)
  $bandBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush($bandRect, (C '#8b5cf6'), (C '#7c3aed'), 0.0)
  $g.FillRectangle($bandBrush, $bandRect)
  $g.ResetClip()

  # date cells — bottom-right one is gold, the spotlight colour
  $cols = 3; $rows = 2
  $padX = $gs * 0.135
  $gridW = $gs - $padX * 2
  $cellW = $gridW / ($cols + ($cols - 1) * 0.42)
  $gapX = $cellW * 0.42
  $cellH = $cellW * 0.74
  $gridTop = $bodyY + $bandH + ($bodyH - $bandH - ($cellH * $rows + $cellH * 0.55)) / 2
  $gapY = $cellH * 0.55
  $dim = New-Object System.Drawing.SolidBrush((C '#2b1b4f' 92))
  $gold = New-Object System.Drawing.SolidBrush((C '#ffd580'))
  $goldGlow = New-Object System.Drawing.SolidBrush((C '#f0b445' 70))

  for ($r = 0; $r -lt $rows; $r++) {
    for ($c = 0; $c -lt $cols; $c++) {
      $cx = $ox + $padX + $c * ($cellW + $gapX)
      $cy = $gridTop + $r * ($cellH + $gapY)
      $isGold = ($r -eq 1 -and $c -eq 1)
      if ($isGold) {
        $halo = New-RoundedPath ($cx - $cellW * 0.16) ($cy - $cellW * 0.16) ($cellW * 1.32) ($cellH + $cellW * 0.32) ($cellH * 0.55)
        $g.FillPath($goldGlow, $halo)
      }
      $cell = New-RoundedPath $cx $cy $cellW $cellH ($cellH * 0.36)
      $g.FillPath(($(if ($isGold) { $gold } else { $dim })), $cell)
    }
  }

  $g.Dispose()
  $path = Join-Path $OutDir $file
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Output ("{0,-30} {1} bytes" -f $file, (Get-Item $path).Length)
}

Write-Icon 192 'icon-192.png' $false
Write-Icon 512 'icon-512.png' $false
Write-Icon 512 'icon-maskable-512.png' $true
Write-Icon 180 'apple-touch-icon-180.png' $false
Write-Icon 1024 'icon-1024.png' $false
