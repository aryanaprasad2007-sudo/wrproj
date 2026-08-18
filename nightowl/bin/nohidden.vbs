' Runs no.ps1 with no console window.
'   wscript.exe nohidden.vbs break eye
' Used by the scheduled tasks so a nudge never flashes a black box first.
Option Explicit
Dim sh, fso, binDir, ps, cmd, i

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
binDir  = fso.GetParentFolderName(WScript.ScriptFullName)
ps      = binDir & "\no.ps1"

' Same "yyyy-MM-dd HH:mm:ss" shape Write-NOLog uses, so one tail reads cleanly.
Function Pad2(n)
  Pad2 = Right("0" & n, 2)
End Function

Sub NOLog(msg)
  Dim d, stamp, f
  d = Now
  stamp = Year(d) & "-" & Pad2(Month(d)) & "-" & Pad2(Day(d)) & " " & _
          Pad2(Hour(d)) & ":" & Pad2(Minute(d)) & ":" & Pad2(Second(d))
  On Error Resume Next
  Set f = fso.OpenTextFile(fso.GetParentFolderName(binDir) & "\logs\nightowl.log", 8, True)
  f.WriteLine stamp & "  " & msg
  f.Close
  On Error GoTo 0
End Sub

' A missing no.ps1 used to launch anyway and vanish - sh.Run reports nothing and
' the task still exits 0. Leave a trace instead of failing invisibly.
If Not fso.FileExists(ps) Then
  NOLog "launcher ERROR: no.ps1 not found at " & ps
  WScript.Quit 1
End If

' A no-argument call is almost always a caller that lost its verb, not a real
' request - no.ps1 would quietly default to "status" and look like a success.
If WScript.Arguments.Count = 0 Then
  NOLog "launcher WARN: invoked with no action - caller dropped its arguments"
End If

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps & """"
For i = 0 To WScript.Arguments.Count - 1
  cmd = cmd & " """ & WScript.Arguments(i) & """"
Next

sh.Run cmd, 0, False
