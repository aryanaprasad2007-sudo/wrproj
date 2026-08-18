// Compiled protocol-handler stub for nightowl:// links.
//
// Why this exists: Windows Explorer's association resolver (the path Chromium
// browsers use for external-protocol launches, distinct from plain
// ShellExecute) truncates any "shell\open\command" value that names an
// explicit interpreter plus a separate quoted script path plus %1 - and even
// a bare quoted ".vbs" target plus %1 still breaks, because resolving a .vbs
// requires a second association hop (.vbs -> wscript.exe) that reproduces the
// same corruption. A single native .exe as the sole quoted target, with %1 as
// the only other token, is the one shape that survives both hops because
// there's no second hop to get wrong.
//
// Build: csc.exe /nologo /target:winexe /out:nourl.exe nourl_launcher.cs
using System;
using System.Diagnostics;

class NightOwlLauncher
{
    static void Main(string[] args)
    {
        if (args.Length == 0) return;

        string binDir = AppDomain.CurrentDomain.BaseDirectory;
        string script = System.IO.Path.Combine(binDir, "nohandler.ps1");

        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \""
                        + script + "\" \"" + args[0] + "\"",
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        Process.Start(psi);
    }
}
