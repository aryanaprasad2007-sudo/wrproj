# NightOwl - core engine
# Screen warmth, focus modes, nudges, and machine state for a late-night desk setup.

$script:NORoot   = Split-Path -Parent $PSScriptRoot
$script:NOConfig = Join-Path $script:NORoot "config.json"
$script:NOState  = Join-Path $script:NORoot "data\state.json"
$script:NOLog    = Join-Path $script:NORoot "logs\nightowl.log"

# ============================================================== native =====

if (-not ("NONative" -as [type])) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class NONative {
  [StructLayout(LayoutKind.Sequential)]
  public struct RAMP {
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=256)] public UInt16[] Red;
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=256)] public UInt16[] Green;
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=256)] public UInt16[] Blue;
  }
  [StructLayout(LayoutKind.Sequential)]
  public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left, Top, Right, Bottom; }

  [DllImport("gdi32.dll")]  public static extern bool SetDeviceGammaRamp(IntPtr hdc, ref RAMP r);
  [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr h);
  [DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr h, IntPtr dc);
  [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO p);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll", CharSet=CharSet.Auto)]
  public static extern bool SystemParametersInfo(int a, int u, string p, int w);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);

  public static bool ApplyGamma(double mr, double mg, double mb, double bright) {
    IntPtr dc = GetDC(IntPtr.Zero);
    RAMP r = new RAMP();
    r.Red = new UInt16[256]; r.Green = new UInt16[256]; r.Blue = new UInt16[256];
    for (int i = 0; i < 256; i++) {
      double v = i * 256.0 * bright;
      r.Red[i]   = (UInt16)Math.Max(0, Math.Min(65535, v * mr));
      r.Green[i] = (UInt16)Math.Max(0, Math.Min(65535, v * mg));
      r.Blue[i]  = (UInt16)Math.Max(0, Math.Min(65535, v * mb));
    }
    bool ok = SetDeviceGammaRamp(dc, ref r);
    ReleaseDC(IntPtr.Zero, dc);
    return ok;
  }
  public static uint IdleMs() {
    LASTINPUTINFO li = new LASTINPUTINFO();
    li.cbSize = (uint)Marshal.SizeOf(li);
    GetLastInputInfo(ref li);
    return (uint)Environment.TickCount - li.dwTime;
  }
  public static bool ForegroundIsFullscreen() {
    IntPtr h = GetForegroundWindow();
    if (h == IntPtr.Zero) return false;
    RECT r;
    if (!GetWindowRect(h, out r)) return false;
    int sw = GetSystemMetrics(0), sh = GetSystemMetrics(1);
    return (r.Right - r.Left) >= sw && (r.Bottom - r.Top) >= sh;
  }
}
"@
}

# ============================================================== config =====

function Get-NOConfig {
    if (Test-Path $script:NOConfig) {
        return (Get-Content $script:NOConfig -Raw | ConvertFrom-Json)
    }
    throw "NightOwl config missing at $script:NOConfig"
}

function Get-NOStateData {
    if (Test-Path $script:NOState) {
        try { return (Get-Content $script:NOState -Raw | ConvertFrom-Json) } catch { }
    }
    return [pscustomobject]@{ mode = "auto"; modeSince = ""; lastBreak = ""; sessions = @() }
}

function Save-NOStateData {
    param($State)
    $dir = Split-Path -Parent $script:NOState
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $State | ConvertTo-Json -Depth 6 | Out-File -FilePath $script:NOState -Encoding utf8
}

function Write-NOLog {
    param([string]$Message)
    $dir = Split-Path -Parent $script:NOLog
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message" | Add-Content -Path $script:NOLog -Encoding utf8
}

# ========================================================= time / phase =====

function ConvertTo-NOTimeToday {
    # "01:30" -> DateTime today at that time
    param([string]$Hhmm)
    $p = $Hhmm.Split(":")
    return (Get-Date -Hour ([int]$p[0]) -Minute ([int]$p[1]) -Second 0 -Millisecond 0)
}

function Get-NOSchedule {
    <#  Returns the current awake window as absolute DateTimes.

        The window runs wake -> next wake, with bedtime sitting *inside* it after
        midnight. Anchoring on wake (not on the calendar day) is what keeps 2am
        reading as "past bedtime, still up" instead of rolling forward a day and
        claiming you're asleep. #>
    param([datetime]$Now = (Get-Date))

    $c   = Get-NOConfig
    $now = $Now

    $wp   = $c.wake.Split(":")
    $wake = $now.Date.AddHours([int]$wp[0]).AddMinutes([int]$wp[1])
    if ($now -lt $wake) { $wake = $wake.AddDays(-1) }   # still inside yesterday's waking window

    $bp  = $c.bedtime.Split(":")
    $bed = $wake.Date.AddHours([int]$bp[0]).AddMinutes([int]$bp[1])
    if ($bed -le $wake) { $bed = $bed.AddDays(1) }      # bedtime is past midnight

    $windDown = $bed.AddMinutes(-1 * $c.windDownMinutes)
    [pscustomobject]@{
        Wake            = $wake
        WindDown        = $windDown
        Bed             = $bed
        Now             = $now
        MinutesToBed    = [math]::Round(($bed - $now).TotalMinutes)
        MinutesAwake    = [math]::Round(($now - $wake).TotalMinutes)
        AwakeSpanMin    = [math]::Round(($bed - $wake).TotalMinutes)
    }
}

function Get-NODayPhase {
    param([datetime]$Now = (Get-Date))
    $s = Get-NOSchedule -Now $Now
    if ($s.Now -ge $s.Bed)              { return "PastBedtime" }
    if ($s.Now -ge $s.WindDown)         { return "WindDown" }
    if ($s.Now -lt $s.Wake.AddHours(2)) { return "Morning" }
    if ($s.Now -ge $s.Bed.AddHours(-5)) { return "Evening" }
    return "Day"
}

# ================================================================ screen =====

function Get-NOKelvinRgb {
    <# Tanner Helland blackbody approximation -> 0..1 channel multipliers #>
    param([int]$Kelvin)
    $t = $Kelvin / 100.0
    if ($t -le 66) { $r = 255 } else { $r = 329.698727446 * [math]::Pow($t - 60, -0.1332047592) }
    if ($t -le 66) { $g = 99.4708025861 * [math]::Log($t) - 161.1195681661 }
    else           { $g = 288.1221695283 * [math]::Pow($t - 60, -0.0755148492) }
    if ($t -ge 66)     { $b = 255 }
    elseif ($t -le 19) { $b = 0 }
    else               { $b = 138.5177312231 * [math]::Log($t - 10) - 305.0447927307 }

    $cl = { param($x) [math]::Max(0, [math]::Min(255, $x)) / 255.0 }
    [pscustomobject]@{ R = (& $cl $r); G = (& $cl $g); B = (& $cl $b) }
}

function Set-NOScreen {
    <# Apply a colour temperature and brightness to the whole display via gamma ramp. #>
    param(
        [int]$Kelvin = 6500,
        [double]$Brightness = 1.0
    )
    $m = Get-NOKelvinRgb -Kelvin $Kelvin
    $ok = [NONative]::ApplyGamma($m.R, $m.G, $m.B, $Brightness)
    if ($ok) { Write-NOLog "screen -> ${Kelvin}K @ $([math]::Round($Brightness*100))%" }
    return $ok
}

function Reset-NOScreen { [NONative]::ApplyGamma(1.0, 1.0, 1.0, 1.0) | Out-Null }

function Get-NOAutoWarmth {
    <# Piecewise curve: neutral through the working day, warming into the night. #>
    param([datetime]$Now = (Get-Date))
    $c = Get-NOConfig
    $s = Get-NOSchedule -Now $Now
    $now = $s.Now

    $pts = @(
        @{ At = $s.Wake;                  K = $c.warmth.dayKelvin;   B = 1.00 },
        @{ At = $s.Bed.AddHours(-6);      K = $c.warmth.dayKelvin;   B = 1.00 },
        @{ At = $s.Bed.AddHours(-4);      K = $c.warmth.eveKelvin;   B = 0.97 },
        @{ At = $s.WindDown;              K = $c.warmth.nightKelvin; B = 0.92 },
        @{ At = $s.Bed;                   K = $c.warmth.lateKelvin;  B = 0.82 },
        @{ At = $s.Bed.AddHours(2);       K = $c.warmth.lateKelvin;  B = 0.72 }
    )

    if ($now -le $pts[0].At)                { return [pscustomobject]@{ Kelvin = $pts[0].K; Brightness = $pts[0].B } }
    if ($now -ge $pts[$pts.Count-1].At)     { $l = $pts[$pts.Count-1]; return [pscustomobject]@{ Kelvin = $l.K; Brightness = $l.B } }

    for ($i = 0; $i -lt $pts.Count - 1; $i++) {
        $a = $pts[$i]; $b = $pts[$i+1]
        if ($now -ge $a.At -and $now -lt $b.At) {
            $span = ($b.At - $a.At).TotalSeconds
            if ($span -le 0) { continue }
            $f = ($now - $a.At).TotalSeconds / $span
            return [pscustomobject]@{
                Kelvin     = [int]($a.K + ($b.K - $a.K) * $f)
                Brightness = [double]($a.B + ($b.B - $a.B) * $f)
            }
        }
    }
    return [pscustomobject]@{ Kelvin = $c.warmth.dayKelvin; Brightness = 1.0 }
}

function Set-NOWarmthOffset {
    <# Manual bias on top of the curve, so a hotkey nudge survives the next sync. #>
    param([int]$Delta, [switch]$Clear)
    $st  = Get-NOStateData
    $cur = 0
    if ($st.PSObject.Properties.Name -contains 'kelvinOffset') { $cur = [int]$st.kelvinOffset }
    $new = 0
    if (-not $Clear) { $new = [math]::Max(-2500, [math]::Min(1500, $cur + $Delta)) }
    $st | Add-Member -NotePropertyName kelvinOffset -NotePropertyValue $new -Force
    Save-NOStateData $st
    return $new
}

function Sync-NOScreen {
    <# Nudge the display toward wherever the circadian curve says it should be. #>
    param([datetime]$Now = (Get-Date))
    $st  = Get-NOStateData
    $off = 0
    if ($st.PSObject.Properties.Name -contains 'kelvinOffset') { $off = [int]$st.kelvinOffset }

    $w = Get-NOAutoWarmth -Now $Now
    $k = [math]::Max(1800, [math]::Min(6500, $w.Kelvin + $off))
    Set-NOScreen -Kelvin $k -Brightness $w.Brightness | Out-Null
    return [pscustomobject]@{ Kelvin = $k; Brightness = $w.Brightness; Offset = $off; CurveKelvin = $w.Kelvin }
}

# =========================================================== system knobs =====

function Set-NONotifications {
    param([bool]$Enabled)
    $v = 0; if ($Enabled) { $v = 1 }
    $k1 = "HKCU:\Software\Microsoft\Windows\CurrentVersion\PushNotifications"
    $k2 = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
    foreach ($k in @($k1, $k2)) { if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null } }
    Set-ItemProperty -Path $k1 -Name "ToastEnabled" -Value $v -Type DWord -Force
    Set-ItemProperty -Path $k2 -Name "NOC_GLOBAL_SETTING_TOASTS_ENABLED" -Value $v -Type DWord -Force
    Write-NOLog "notifications -> $Enabled"
}

function Get-NONotifications {
    $k1 = "HKCU:\Software\Microsoft\Windows\CurrentVersion\PushNotifications"
    $v = (Get-ItemProperty -Path $k1 -Name "ToastEnabled" -ErrorAction SilentlyContinue).ToastEnabled
    if ($null -eq $v) { return $true }   # key absent -> Windows default is on
    return [bool]$v
}

function Set-NOPowerPlan {
    param([ValidateSet("Balanced","HighPerformance","PowerSaver")][string]$Plan)
    $g = @{
        Balanced        = "381b4222-f694-41f0-9685-ff5bb260df2e"
        HighPerformance = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
        PowerSaver      = "a1841308-3541-4fab-bc81-f71556f20b4a"
    }[$Plan]
    powercfg /setactive $g 2>$null
    Write-NOLog "power plan -> $Plan"
}

function Set-NOMonitorTimeout {
    param([int]$Minutes)
    powercfg /change monitor-timeout-ac $Minutes 2>$null
    Write-NOLog "monitor timeout -> $Minutes min"
}

function Set-NOGameMode {
    param([bool]$Enabled)
    $k = "HKCU:\Software\Microsoft\GameBar"
    if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null }
    $v = 0; if ($Enabled) { $v = 1 }
    Set-ItemProperty -Path $k -Name "AutoGameModeEnabled" -Value $v -Type DWord -Force
    Write-NOLog "game mode -> $Enabled"
}

function Set-NOWallpaperEngine {
    <#  Drives the running Wallpaper Engine instance. The control command has to
        come from the same build that's running (this machine runs the 32-bit
        one), so resolve the exe from the live process rather than from config. #>
    param([ValidateSet("pause","play","mute","unmute","stop")][string]$Action)

    $proc = Get-Process -Name "wallpaper32","wallpaper64" -ErrorAction SilentlyContinue |
            Where-Object { $_.Path } | Select-Object -First 1
    if (-not $proc) { return $false }        # not running - nothing to control

    Start-Process -FilePath $proc.Path -ArgumentList @("-control", $Action) -WindowStyle Hidden
    Write-NOLog "wallpaper engine ($($proc.ProcessName)) -> $Action"
    return $true
}

function Get-NOIdleSeconds { return [math]::Round([NONative]::IdleMs() / 1000) }
function Test-NOFullscreen { return [NONative]::ForegroundIsFullscreen() }

function Test-NOGameRunning {
    $c = Get-NOConfig
    foreach ($n in $c.gameProcesses) {
        if (Get-Process -Name $n -ErrorAction SilentlyContinue) { return $true }
    }
    return $false
}

# ====================================================== calendar aware =====

function Get-NOActiveCalendarEvent {
    <#  Whatever calendar.json says is happening right now, or $null.
        calendar.json is only as fresh as the last time /nightowl ran (no
        credentials for an unattended pull) - this degrades gracefully to
        "no event known" rather than erroring when it's missing or stale. #>
    param([datetime]$Now = (Get-Date))
    $path = Join-Path $script:NORoot "data\calendar.json"
    if (-not (Test-Path $path)) { return $null }
    try { $cal = Get-Content $path -Raw | ConvertFrom-Json } catch { return $null }
    if (-not $cal.events) { return $null }

    #  Degrading to "no event known" is the right behaviour, but it is also
    #  indistinguishable from "genuinely nothing on right now" - which is how
    #  this went unnoticed from 2026-08-04 to 2026-08-17. Every event in the
    #  cache had passed, so protected blocks and quiet hours were both
    #  effectively switched off for thirteen days and nothing said so.
    #  Say so now. The behaviour is unchanged; only the silence is fixed.
    if ($cal.fetchedAt) {
        try {
            $age = ($Now - [datetime]::Parse($cal.fetchedAt, $null,
                     [System.Globalization.DateTimeStyles]::RoundtripKind)).TotalHours
            if ($age -gt 24) {
                Write-NOLog ("WARN calendar.json is {0:N0}h old - protected blocks and quiet hours cannot fire. Run /nightowl to refresh." -f $age)
                return $null
            }
        } catch { }
    }

    foreach ($e in $cal.events) {
        if ($e.allDay) { continue }
        try {
            $s = [datetime]::Parse($e.start, $null, [System.Globalization.DateTimeStyles]::RoundtripKind)
            $en = [datetime]::Parse($e.end, $null, [System.Globalization.DateTimeStyles]::RoundtripKind)
        } catch { continue }
        if ($Now -ge $s -and $Now -lt $en) { return $e }
    }
    return $null
}

function Test-NOProtectedBlock {
    <#  Is a calendar block that already has its own designed break structure
        (Deep Work, Homework - both literally say "protected block, do not
        move" in their own descriptions) active right now? A generic nudge
        popping up mid-block would just be noise on top of a block he already
        built breaks into. #>
    param([datetime]$Now = (Get-Date))
    $c = Get-NOConfig
    $kw = $c.calendarAwareness.protectedBlockKeywords
    if (-not $kw) { return $null }
    $e = Get-NOActiveCalendarEvent -Now $Now
    if (-not $e) { return $null }
    foreach ($k in $kw) {
        if ($e.title -like "*$k*") { return $e }
    }
    return $null
}

function Test-NOQuietBlock {
    <# Is a quiet-hours calendar block (Prayer Closet) active right now? #>
    param([datetime]$Now = (Get-Date))
    $c = Get-NOConfig
    $kw = $c.calendarAwareness.quietBlockKeywords
    if (-not $kw) { return $null }
    $e = Get-NOActiveCalendarEvent -Now $Now
    if (-not $e) { return $null }
    foreach ($k in $kw) {
        if ($e.title -like "*$k*") { return $e }
    }
    return $null
}

# ================================================================ nudges =====

function Show-NONudge {
    <# A styled, self-dismissing corner card. Deliberately not a Windows toast,
       so it still appears while notifications are suppressed in a focus mode. #>
    param(
        [string]$Title,
        [string]$Message,
        [string]$Glyph = "*",
        [int]$Seconds = 9,
        [ValidateSet("auto","day","night")][string]$Theme = "auto",
        [switch]$NoWait
    )

    if ($Theme -eq "auto") {
        $ph = Get-NODayPhase
        if ($ph -eq "WindDown" -or $ph -eq "PastBedtime" -or $ph -eq "Asleep") { $Theme = "night" } else { $Theme = "day" }
    }

    if ($Theme -eq "night") {
        $bg1="#FF2A1E36"; $bg2="#FF1E1526"; $fg="#FFF6E9F5"; $sub="#FFC8AFD8"; $accent="#FFE9A8D8"; $accent2="#FFB98CE8"
    } else {
        $bg1="#FFFFF4FA"; $bg2="#FFF2E9FF"; $fg="#FF3A2647"; $sub="#FF6C5480"; $accent="#FFE0509F"; $accent2="#FF8B5CF6"
    }

    $ps = [powershell]::Create()
    $ps.Runspace = [runspacefactory]::CreateRunspace()
    $ps.Runspace.ApartmentState = "STA"
    $ps.Runspace.ThreadOptions  = "ReuseThread"
    $ps.Runspace.Open()

    [void]$ps.AddScript({
        param($Title,$Message,$Glyph,$Seconds,$bg1,$bg2,$fg,$sub,$accent,$accent2)
        Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase

        $xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        Topmost="True" ShowInTaskbar="False" ResizeMode="NoResize"
        SizeToContent="Height" Width="420" WindowStartupLocation="Manual">
  <Border CornerRadius="20" Margin="18" Padding="0">
    <Border.Effect><DropShadowEffect BlurRadius="28" ShadowDepth="6" Opacity="0.35" Color="#FF2A1E36"/></Border.Effect>
    <Border CornerRadius="20" BorderThickness="2">
      <Border.BorderBrush>
        <LinearGradientBrush StartPoint="0,0" EndPoint="1,1">
          <GradientStop Color="$accent" Offset="0"/><GradientStop Color="$accent2" Offset="1"/>
        </LinearGradientBrush>
      </Border.BorderBrush>
      <Border.Background>
        <LinearGradientBrush StartPoint="0,0" EndPoint="1,1">
          <GradientStop Color="$bg1" Offset="0"/><GradientStop Color="$bg2" Offset="1"/>
        </LinearGradientBrush>
      </Border.Background>
      <StackPanel Margin="24,20,24,20">
        <StackPanel Orientation="Horizontal" Margin="0,0,0,10">
          <Border Width="40" Height="40" CornerRadius="12" Margin="0,0,14,0">
            <Border.Background>
              <LinearGradientBrush StartPoint="0,0" EndPoint="1,1">
                <GradientStop Color="$accent" Offset="0"/><GradientStop Color="$accent2" Offset="1"/>
              </LinearGradientBrush>
            </Border.Background>
            <TextBlock Text="$Glyph" FontSize="20" Foreground="White" FontWeight="Bold"
                       HorizontalAlignment="Center" VerticalAlignment="Center"/>
          </Border>
          <TextBlock Text="$Title" FontFamily="Segoe UI Semibold" FontSize="19" Foreground="$fg"
                     VerticalAlignment="Center" TextWrapping="Wrap" Width="310"/>
        </StackPanel>
        <TextBlock Text="$Message" FontFamily="Segoe UI" FontSize="14.5" Foreground="$sub"
                   TextWrapping="Wrap" LineHeight="21" Margin="0,0,0,14"/>
        <Border Height="4" CornerRadius="2" Background="#22000000">
          <Border x:Name="Bar" HorizontalAlignment="Left" CornerRadius="2" Width="372">
            <Border.Background>
              <LinearGradientBrush StartPoint="0,0" EndPoint="1,0">
                <GradientStop Color="$accent" Offset="0"/><GradientStop Color="$accent2" Offset="1"/>
              </LinearGradientBrush>
            </Border.Background>
          </Border>
        </Border>
      </StackPanel>
    </Border>
  </Border>
</Window>
"@
        $w = [Windows.Markup.XamlReader]::Parse($xaml)
        $bar = $w.FindName("Bar")

        $wa = [System.Windows.SystemParameters]::WorkArea
        $w.Left = $wa.Right - 420
        $w.Top  = $wa.Bottom - 190

        $w.Add_MouseLeftButtonDown({ $w.Close() })
        $w.Opacity = 0

        $fin = New-Object Windows.Media.Animation.DoubleAnimation(0, 1, [Windows.Duration]([timespan]::FromMilliseconds(280)))
        $slide = New-Object Windows.Media.Animation.DoubleAnimation(($wa.Bottom - 150), ($wa.Bottom - 190), [Windows.Duration]([timespan]::FromMilliseconds(340)))
        $barAnim = New-Object Windows.Media.Animation.DoubleAnimation(372, 0, [Windows.Duration]([timespan]::FromSeconds($Seconds)))

        $w.Add_Loaded({
            $w.BeginAnimation([Windows.Window]::OpacityProperty, $fin)
            $w.BeginAnimation([Windows.Window]::TopProperty, $slide)
            $bar.BeginAnimation([Windows.Controls.Border]::WidthProperty, $barAnim)
        })

        $timer = New-Object Windows.Threading.DispatcherTimer
        $timer.Interval = [timespan]::FromSeconds($Seconds)
        $timer.Add_Tick({
            $timer.Stop()
            $fout = New-Object Windows.Media.Animation.DoubleAnimation(1, 0, [Windows.Duration]([timespan]::FromMilliseconds(320)))
            $fout.Add_Completed({ $w.Close() })
            $w.BeginAnimation([Windows.Window]::OpacityProperty, $fout)
        })
        $timer.Start()
        [void]$w.ShowDialog()
    })

    foreach ($a in @($Title, $Message, $Glyph, $Seconds, $bg1, $bg2, $fg, $sub, $accent, $accent2)) {
        [void]$ps.AddArgument($a)
    }

    $handle = $ps.BeginInvoke()
    Write-NOLog "nudge: $Title"

    # The card lives in a background runspace, so a scheduled task that returned
    # immediately would kill it mid-animation. Block unless the caller opts out.
    if (-not $NoWait) {
        $deadline = (Get-Date).AddSeconds($Seconds + 6)
        while (-not $handle.IsCompleted -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 150
        }
        $ps.Dispose()
        $ps.Runspace.Close()
    }
}

# ================================================================= modes =====

function Invoke-NOMode {
    <#  -Scheduled marks a call that came from a Windows scheduled task rather
        than from Ari. It enables the stale-fire guard below.

        Why that guard exists: the NightOwl_* tasks are registered with
        StartWhenAvailable, so if the machine was off overnight Task Scheduler
        replays every missed run the moment it boots. On 2026-08-17 that fired
        WindDown (00:30) and Bedtime (01:30) back-to-back at 10:59 AM - which
        dimmed the screen to 2500K, dropped the machine to PowerSaver, left
        state.json reading "sleep" for the rest of the day, and popped a card
        telling him he was up past bedtime. In the late morning. Because the PC
        had been off.

        A time-of-day mode is only meaningful at that time of day, so a
        scheduled call now checks that the clock still agrees before it changes
        anything. Manual calls are never blocked - if Ari asks for wind-down at
        noon, he gets wind-down at noon. #>
    param(
        [ValidateSet("work","game","anime","winddown","sleep","reset","auto")]
        [string]$Mode,
        [switch]$Quiet,
        [switch]$Scheduled
    )

    $c = Get-NOConfig
    if ($Mode -eq "auto") {
        switch (Get-NODayPhase) {
            "WindDown"    { $Mode = "winddown" }
            "PastBedtime" { $Mode = "sleep" }
            "Asleep"      { $Mode = "sleep" }
            default       { $Mode = "work" }
        }
    }

    if ($Scheduled) {
        $phase = Get-NODayPhase
        $expected = @{
            winddown = @("WindDown")
            sleep    = @("PastBedtime", "Asleep")
        }[$Mode]
        if ($expected -and $phase -notin $expected) {
            Write-NOLog "SKIPPED stale scheduled '$Mode' (phase is $phase - missed run replayed on boot)"
            return $null
        }
    }

    switch ($Mode) {
        "work" {
            Sync-NOScreen | Out-Null
            Set-NONotifications $false
            Set-NOPowerPlan "HighPerformance"
            Set-NOMonitorTimeout 15
            Set-NOWallpaperEngine "pause" | Out-Null
            if (-not $Quiet) { Show-NONudge -Title "Work mode" -Glyph "W" -Message "Notifications are off and the GPU is free. Eye-break nudges every $($c.eyeBreakMinutes) min." }
        }
        "game" {
            Sync-NOScreen | Out-Null
            Set-NONotifications $false
            Set-NOPowerPlan "HighPerformance"
            Set-NOMonitorTimeout 30
            Set-NOGameMode $true
            Set-NOWallpaperEngine "stop" | Out-Null
            if (-not $Quiet) { Show-NONudge -Title "Game mode" -Glyph "G" -Message "Game Mode on, wallpaper stopped, notifications silenced. Break nudges are paused while you play." }
        }
        "anime" {
            Set-NOScreen -Kelvin $c.warmth.animeKelvin -Brightness 0.96 | Out-Null
            Set-NONotifications $false
            Set-NOPowerPlan "Balanced"
            Set-NOMonitorTimeout 0          # never blank the screen mid-episode
            Set-NOWallpaperEngine "stop" | Out-Null
            if (-not $Quiet) { Show-NONudge -Title "Anime mode" -Glyph "A" -Message "Screen set to $($c.warmth.animeKelvin)K, display sleep disabled, notifications off. Enjoy." }
        }
        "winddown" {
            Set-NOScreen -Kelvin $c.warmth.nightKelvin -Brightness 0.88 | Out-Null
            Set-NONotifications $true
            Set-NOPowerPlan "Balanced"
            Set-NOMonitorTimeout 10
            Set-NOGameMode $false
            Set-NOWallpaperEngine "play" | Out-Null
            $s = Get-NOSchedule
            if (-not $Quiet) { Show-NONudge -Title "Wind-down" -Glyph "~" -Seconds 14 -Message "About $($s.MinutesToBed) min until bed. Screen's warming to $($c.warmth.nightKelvin)K. Nice moment to set things down - whatever's open is allowed to stay open." }
        }
        "sleep" {
            Set-NOScreen -Kelvin $c.warmth.lateKelvin -Brightness 0.7 | Out-Null
            Set-NOPowerPlan "PowerSaver"
            Set-NOMonitorTimeout 5
            Set-NOGameMode $false
            if (-not $Quiet) { Show-NONudge -Title "Late one" -Glyph "~" -Seconds 16 -Message "It's past $($c.bedtime), so the screen's gone dim and warm. No judgement if you're still up - it'll all still be here at $($c.wake)." }
        }
        "reset" {
            Reset-NOScreen
            Set-NONotifications $true
            Set-NOPowerPlan "Balanced"
            Set-NOMonitorTimeout 15
            Set-NOGameMode $false
            Set-NOWallpaperEngine "play" | Out-Null
            if (-not $Quiet) { Show-NONudge -Title "Reset" -Glyph "R" -Message "Screen, power plan and notifications are back to Windows defaults." }
        }
    }

    $st = Get-NOStateData
    $st.mode = $Mode
    $st.modeSince = (Get-Date).ToString("o")
    Save-NOStateData $st
    Write-NOLog "MODE -> $Mode"
    return $Mode
}

function Get-NOStatus {
    $s  = Get-NOSchedule
    $st = Get-NOStateData
    $w  = Get-NOAutoWarmth
    [pscustomobject]@{
        Mode          = $st.mode
        Phase         = Get-NODayPhase
        Now           = $s.Now.ToString("HH:mm")
        Bedtime       = $s.Bed.ToString("HH:mm")
        MinutesToBed  = $s.MinutesToBed
        HoursAwake    = [math]::Round($s.MinutesAwake / 60, 1)
        TargetKelvin  = $w.Kelvin
        IdleSeconds   = Get-NOIdleSeconds
        GameRunning   = Test-NOGameRunning
    }
}

Export-ModuleMember -Function *-NO*, Invoke-NOMode, ConvertTo-NOTimeToday
