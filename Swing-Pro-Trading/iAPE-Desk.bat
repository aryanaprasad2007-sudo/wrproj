@echo off
REM iAPE Desk - Robinhood Agentic account.
REM Scans the validated daily engine, writes the ticket book + desk page,
REM and opens it. Places NO orders: this script has no broker credentials
REM and no path to the account. Orders happen only in chat, per-trade
REM confirmed, through the Robinhood MCP connector.
setlocal
set PYTHONUTF8=1
cd /d "%~dp0backtest"

REM Book size defaults to the last value saved in cache/rh_desk_settings.json.
REM Pass a fresh one from get_portfolio:  iAPE-Desk.bat 225.37
if "%~1"=="" (
  py rh_desk.py --open
) else (
  py rh_desk.py --book %1 --open
)

if errorlevel 1 (
  echo.
  echo Desk scan FAILED - see the error above.
  echo Common causes: Alpaca data keys missing from the registry, or no network.
)
echo.
pause
