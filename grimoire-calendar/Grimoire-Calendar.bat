@echo off
REM Grimoire Calendar — launcher.
REM Starts the local server (which also proxies the iCal feeds past CORS) and
REM opens the app in its own window. Close the window this opens to stop it.

cd /d "%~dp0"
title Grimoire Calendar
py -3 tools\serve.py %*
