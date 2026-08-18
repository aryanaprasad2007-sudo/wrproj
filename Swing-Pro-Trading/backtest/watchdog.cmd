@echo off
REM iAPE watchdog launcher.
REM
REM The .cmd wrapper is NOT optional: .ps1 files will not execute on this
REM machine (CurrentUser execution policy is Undefined -> falls back to
REM Restricted). Passing -ExecutionPolicy Bypass on the command line is the
REM supported override and does not change any machine setting.
REM
REM Usage:  watchdog.cmd
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0watchdog.ps1" %*
