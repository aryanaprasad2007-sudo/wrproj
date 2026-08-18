$Host.UI.RawUI.WindowTitle = "safe uwu"
$esc = [char]27
$pink = "$esc[38;5;218m"
$pinkBright = "$esc[38;5;213m"
$reset = "$esc[0m"

# --- make the console font big ---
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public class ConsoleFont {
    [StructLayout(LayoutKind.Sequential)]
    public struct COORD {
        public short X;
        public short Y;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CONSOLE_FONT_INFO_EX {
        public uint cbSize;
        public uint nFont;
        public COORD dwFontSize;
        public uint FontFamily;
        public uint FontWeight;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string FaceName;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetCurrentConsoleFontEx(IntPtr hConsoleOutput, bool bMaximumWindow, ref CONSOLE_FONT_INFO_EX lpConsoleCurrentFontEx);

    public static void SetBig(string face, short size) {
        IntPtr handle = GetStdHandle(-11);
        CONSOLE_FONT_INFO_EX info = new CONSOLE_FONT_INFO_EX();
        info.cbSize = (uint)Marshal.SizeOf(info);
        info.FontFamily = 54;
        info.FaceName = face;
        info.dwFontSize = new COORD { X = 0, Y = size };
        SetCurrentConsoleFontEx(handle, false, ref info);
    }
}
"@

try { [ConsoleFont]::SetBig("Consolas", 36) } catch {}

try {
    $Host.UI.RawUI.BackgroundColor = "Black"
    $Host.UI.RawUI.ForegroundColor = "Magenta"
    $Host.UI.RawUI.WindowSize = New-Object System.Management.Automation.Host.Size(40, 14)
    $Host.UI.RawUI.BufferSize = New-Object System.Management.Automation.Host.Size(40, 200)
    Clear-Host
} catch {}

$messages = @(
    "(^_^) this pc is safe!",
    "( o w o ) nothing bad here~",
    "*:. o(>w<)o .:* all clear!",
    "(^-^)/ <3 totally safe, promise!",
    "no scary stuff, only vibes uwu",
    "(^_^) 100% safe to look at",
    "*:.o nyaa~ everything's fine o.:*",
    "(-_-) zzz... safe & sound",
    "keep scrolling, it's all good! :3"
)

while ($true) {
    $color = if ((Get-Random -Maximum 2) -eq 0) { $pink } else { $pinkBright }
    $msg = $messages[(Get-Random -Maximum $messages.Count)]
    Write-Host ""
    Write-Host "$color$msg$reset"
    Start-Sleep -Milliseconds (Get-Random -Minimum 700 -Maximum 1500)
}
