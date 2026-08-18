@echo off
REM == iAPE dashboard launcher (formerly SWING_PRO) ==========================
REM Double-click to run the control dashboard as a local app.
REM Starts the local server (127.0.0.1:8788) and opens your browser.
REM Close this window to stop the dashboard.
setlocal
title iAPE Dashboard
cd /d "%~dp0backtest"
set PYTHONUTF8=1

REM Self-correct the Webull keys straight from the registry, so a stale
REM session environment (e.g. after an API-key rotation) can never cause the
REM "auth failed (401)" on the real-money panel. Registry is the source of truth.
for /f "tokens=1,2,*" %%A in ('reg query "HKCU\Environment" /v WEBULL_APP_KEY 2^>nul')       do set "WEBULL_APP_KEY=%%C"
for /f "tokens=1,2,*" %%A in ('reg query "HKCU\Environment" /v WEBULL_APP_SECRET 2^>nul')    do set "WEBULL_APP_SECRET=%%C"
for /f "tokens=1,2,*" %%A in ('reg query "HKCU\Environment" /v WEBULL_UAT_APP_KEY 2^>nul')   do set "WEBULL_UAT_APP_KEY=%%C"
for /f "tokens=1,2,*" %%A in ('reg query "HKCU\Environment" /v WEBULL_UAT_APP_SECRET 2^>nul') do set "WEBULL_UAT_APP_SECRET=%%C"

echo Starting iAPE dashboard on http://127.0.0.1:8788 ...
echo (Keep this window open. Close it to stop the dashboard.)
py dashboard.py
pause
endlocal
