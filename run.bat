@echo off
:: Ragnarok - Windows one-click launcher
:: Double-click this file to start the app.
:: Requires: Python 3.11+  https://www.python.org/downloads/
::           Node.js        https://nodejs.org
::           Git            https://git-scm.com  (needed for the PyPSA dependency)

powershell -ExecutionPolicy Bypass -File "%~dp0run.ps1"
if errorlevel 1 (
    echo.
    echo Startup failed. See the error message above.
    pause
)
