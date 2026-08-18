<#
    Show-NOWatcher -- the observer's card.

    A deliberate tonal inversion of NightOwl's Show-NONudge: where that card is
    warm plum-and-foil and friendly, this one is stark white, black serif, and
    says very little. It appears in the same corner, which is the point -- the
    silhouette is familiar and the contents are not.

    No glyph, no icon, no mark. There is nothing to recognise; the card simply
    states what it observed and leaves.

    Same architecture as Show-NONudge (STA runspace + WPF), so it still renders
    while notifications are suppressed in a focus mode.

    Usage:
        . .\src\watcher_nudge.ps1
        Show-NOWatcher -Title "I am aware." -Message "Steam, 47 minutes. The Docket allocated this block to CHEM 1B."

    House rule for callers: every claim in -Message must come from recorded
    data. The card's whole effect rests on being correct; one invented
    observation and it reads as a gimmick forever after.
#>

function Show-NOWatcher {
    param(
        [string]$Title = "I am aware.",
        [string]$Message,
        [int]$Seconds = 14,
        [switch]$NoWait
    )

    # XAML is parsed as markup, so anything app-derived must be escaped.
    # (Window titles routinely contain & -- unescaped it kills the whole card.)
    function Esc([string]$s) {
        if ($null -eq $s) { return "" }
        $s.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;').Replace('"', '&quot;')
    }
    $Title   = Esc $Title
    $Message = Esc $Message

    $ps = [powershell]::Create()
    $ps.Runspace = [runspacefactory]::CreateRunspace()
    $ps.Runspace.ApartmentState = "STA"
    $ps.Runspace.ThreadOptions  = "ReuseThread"
    $ps.Runspace.Open()

    [void]$ps.AddScript({
        param($Title, $Message, $Seconds)
        Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase

        $serif = "Georgia, Palatino Linotype, Times New Roman"

        $xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        Topmost="True" ShowInTaskbar="False" ResizeMode="NoResize"
        SizeToContent="Height" Width="450" WindowStartupLocation="Manual">
  <Border CornerRadius="3" Margin="18" Padding="0">
    <Border.Effect><DropShadowEffect BlurRadius="34" ShadowDepth="0" Opacity="0.55" Color="#FF000000"/></Border.Effect>
    <Border CornerRadius="3" BorderThickness="1" BorderBrush="#FF111111" Background="#FFF7F6F2">
      <StackPanel Margin="0">
        <StackPanel Margin="30,26,30,0">
          <TextBlock Text="$Title" FontFamily="$serif" FontSize="22" Foreground="#FF0A0A0A"
                     TextWrapping="Wrap" Margin="0,0,0,11"/>
          <TextBlock Text="$Message" FontFamily="$serif" FontSize="13.5" Foreground="#FF2B2B2B"
                     TextWrapping="Wrap" LineHeight="22"/>
        </StackPanel>
        <Border Height="2" Background="#14000000" Margin="0,24,0,0">
          <Border x:Name="Bar" HorizontalAlignment="Left" Background="#FF0A0A0A" Width="448"/>
        </Border>
      </StackPanel>
    </Border>
  </Border>
</Window>
"@
        $w = [Windows.Markup.XamlReader]::Parse($xaml)
        $bar = $w.FindName("Bar")

        $wa = [System.Windows.SystemParameters]::WorkArea
        $w.Left = $wa.Right - 450
        $w.Top  = $wa.Bottom - 200

        $w.Add_MouseLeftButtonDown({ $w.Close() })
        $w.Opacity = 0

        # Slower, steadier entrance than the NightOwl card. It does not bounce in.
        $fin  = New-Object Windows.Media.Animation.DoubleAnimation(0, 1, [Windows.Duration]([timespan]::FromMilliseconds(900)))
        $anim = New-Object Windows.Media.Animation.DoubleAnimation(448, 0, [Windows.Duration]([timespan]::FromSeconds($Seconds)))

        $w.Add_Loaded({
            $w.BeginAnimation([Windows.Window]::OpacityProperty, $fin)
            $bar.BeginAnimation([Windows.Controls.Border]::WidthProperty, $anim)
        })

        $timer = New-Object Windows.Threading.DispatcherTimer
        $timer.Interval = [timespan]::FromSeconds($Seconds)
        $timer.Add_Tick({
            $timer.Stop()
            $fout = New-Object Windows.Media.Animation.DoubleAnimation(1, 0, [Windows.Duration]([timespan]::FromMilliseconds(700)))
            $fout.Add_Completed({ $w.Close() })
            $w.BeginAnimation([Windows.Window]::OpacityProperty, $fout)
        })
        $timer.Start()
        [void]$w.ShowDialog()
    })

    foreach ($a in @($Title, $Message, $Seconds)) { [void]$ps.AddArgument($a) }

    $handle = $ps.BeginInvoke()

    if (-not $NoWait) {
        $deadline = (Get-Date).AddSeconds($Seconds + 6)
        while (-not $handle.IsCompleted -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 150
        }
        $ps.Dispose()
        $ps.Runspace.Close()
    }
}
