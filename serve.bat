@echo off
rem Ragnarok - Windows launcher. Starts the app (API + web UI) and the MCP bridge
rem (http://<host>:8765/mcp) together, via serve.ps1.
rem Double-click = server mode (LAN). This-machine-only: serve.bat local
rem Always runs from this file's own folder, and always waits for a key at the end,
rem so the message about what happened stays on screen.
setlocal
cd /d "%~dp0" || (echo Cannot open the Ragnarok folder: "%~dp0" & pause & exit /b 1)
set "MODE=%~1"
if "%MODE%"=="" set "MODE=server"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve.ps1" %MODE%
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo Ragnarok stopped. Server log: "%~dp0logs\serve.log"
) else (
  echo Ragnarok failed with exit code %RC%. Read the ERROR line above. Full log: "%~dp0logs\serve.log"
)
pause
exit /b %RC%
