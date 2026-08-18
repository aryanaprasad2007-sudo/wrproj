@echo off
REM iAPE morning board -- double-click before the open.
REM
REM Interpreter is pinned to 3.12 by absolute path on purpose. A bare "py"
REM resolves to the 3.14 Install Manager build, which has none of this
REM project's packages and silently killed all ten scheduled tasks for 8 days
REM in August 2026. Do not "simplify" this back to "py".

setlocal
set PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PYEXE%" (
    echo.
    echo   Could not find Python 3.12 at:
    echo   %PYEXE%
    echo.
    echo   Nothing was run. Check the install before trading off this board.
    echo.
    pause
    exit /b 1
)

cd /d "%~dp0backtest"
"%PYEXE%" iape_morning.py --book 75.37 --universe wide %*

echo.
pause
