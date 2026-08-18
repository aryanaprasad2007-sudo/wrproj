@echo off
REM == iAPE news scanner launcher (formerly SWING_PRO) =======================
REM Double-click to run the AI news scanner as a local app.
REM Starts the local server (127.0.0.1:8790) and opens your browser.
REM Close this window to stop the scanner. (If the 05:25 scheduled task already
REM started it hidden, this window will just say "port busy" and exit — the
REM scanner is already up; just open http://127.0.0.1:8790.)
setlocal
title iAPE News Scanner
cd /d "%~dp0backtest"
set PYTHONUTF8=1

REM Pull the Anthropic key straight from the registry so a stale session
REM environment can never hide it (same pattern as the dashboard launcher).
for /f "tokens=1,2,*" %%A in ('reg query "HKCU\Environment" /v ANTHROPIC_API_KEY 2^>nul') do set "ANTHROPIC_API_KEY=%%C"

echo Starting iAPE news scanner on http://127.0.0.1:8790 ...
echo (Keep this window open. Close it to stop the scanner.)
py news_scanner.py
pause
endlocal
