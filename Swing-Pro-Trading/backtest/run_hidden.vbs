' run_hidden.vbs - launches a command with NO console window (window style 0).
' Used by the SwingPro_* scheduled tasks so the every-minute trader tick doesn't
' flash cmd windows on screen. Usage: wscript.exe run_hidden.vbs "<full command>"
'
' ---------------------------------------------------------------------------
' 2026-08-12 - INTERPRETER PINNING
'
' The first standalone `py` / `python` / `pythonw` token in the command is
' rewritten to an absolute Python 3.12 path before the command is run.
'
' WHY: on ~2026-08-04 a Python 3.14 install (via the new Python Install
' Manager) silently became the `py` launcher's default. 3.14 has NONE of this
' project's packages, so every scheduled task died on `import numpy` for 8
' days - forward_trader, daily_signals, cockpit, mr_forward, switch_shadow,
' flow capture and the news scanner all crashed on their first import while
' Task Scheduler still reported success, because this script deliberately
' detaches (sh.Run ..., False) and so swallows the exit code.
'
' WHY HERE and not in the ten task definitions: this file is the single
' chokepoint every SwingPro_* task passes through, so one edit fixes all of
' them at once - and the tasks were registered from an elevated session, so
' their definitions cannot be edited from an ordinary shell anyway.
'
' WHY NOT the PYTHON_MANAGER_DEFAULT env var: MEASURED 2026-08-12, do not
' retry. In the clean environment Task Scheduler builds for each launch, the
' Install Manager cannot read unmanaged installs, so it fails to resolve the
' tag "3.12" and exits 0x00000001 WITHOUT RUNNING ANYTHING AT ALL - strictly
' worse than the import crash, and just as silent. Setting that variable also
' makes a bare `py` in a clean environment extract a fresh 132 MB 3.14 runtime
' into the current working directory. Do not "simplify" this back to an env
' var or to a PATH change.
'
' FAIL-SAFE: if the pinned interpreter is missing, the command is passed
' through completely untouched - this script can never make things worse than
' the stock behaviour.
' ---------------------------------------------------------------------------

Option Explicit
Dim sh, fso, re, cmd, i, pin, m

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

cmd = ""
For i = 0 To WScript.Arguments.Count - 1
    If i > 0 Then cmd = cmd & " "
    cmd = cmd & WScript.Arguments(i)
Next

' Resolve the pinned interpreter. Prefer the expanded env var; fall back to the
' literal path if LOCALAPPDATA is absent from the launch environment.
pin = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\python.exe")
If InStr(pin, "%") > 0 Then
    pin = "C:\Users\aware\AppData\Local\Programs\Python\Python312\python.exe"
End If
If Not fso.FileExists(pin) Then
    pin = "C:\Users\aware\AppData\Local\Programs\Python\Python312\python.exe"
End If

If fso.FileExists(pin) Then
    Set re = New RegExp
    ' group 1 = leading boundary, 2 = interpreter token,
    ' group 3 = an optional pre-existing "-3.12" flag (absorbed), 4 = trailing space
    re.Pattern    = "(^|\s)(py|python|pythonw)(\s+-3\.12)?(\s)"
    re.IgnoreCase = True
    re.Global     = False          ' first occurrence only
    If re.Test(cmd) Then
        Set m = re.Execute(cmd)(0)
        cmd = Left(cmd, m.FirstIndex) & m.SubMatches(0) & _
              Chr(34) & pin & Chr(34) & m.SubMatches(3) & _
              Mid(cmd, m.FirstIndex + m.Length + 1)
    End If
End If

sh.Run cmd, 0, False
