@echo off
:: Ragnarok - run the app as ONE process (API + web UI). Windows launcher.
:: Double-click for server mode (LAN); this-machine-only: serve.bat local
setlocal
set MODE=%1
if "%MODE%"=="" set MODE=server
powershell -ExecutionPolicy Bypass -File "%~dp0serve.ps1" %MODE%
if errorlevel 1 (
    echo.
    echo Startup failed. See the error message above.
    pause
)
