@echo off
:: Ragnarok - Windows launcher. Starts the app (API + web UI) and the Bifrost
:: MCP bridge (http://<host>:8765/mcp) together, via serve.ps1.
:: Double-click = server mode (LAN); this-machine-only: serve.bat local
setlocal
set MODE=%1
if "%MODE%"=="" set MODE=server
powershell -ExecutionPolicy Bypass -File "%~dp0serve.ps1" %MODE%
if errorlevel 1 (
    echo.
    echo Startup failed. See the error message above.
    pause
)
