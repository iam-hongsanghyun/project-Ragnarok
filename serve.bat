@echo off
:: Ragnarok - run the app as ONE process (API + web UI). Windows launcher.
:: Double-click for local mode, or from a terminal: serve.bat server
setlocal
set MODE=%1
if "%MODE%"=="" set MODE=local
powershell -ExecutionPolicy Bypass -File "%~dp0serve.ps1" %MODE%
if errorlevel 1 (
    echo.
    echo Startup failed. See the error message above.
    pause
)
