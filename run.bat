@echo off
rem Ragnarok - Windows one-click launcher (DEV mode: live reload, ports 3000 + 8000).
rem Double-click this file to start the app. Logs: logs\run.log (launcher) and
rem logs\backend.log (the backend). Always waits for a key at the end.
rem Requires: Python 3.11+  https://www.python.org/downloads/
rem           Node.js       https://nodejs.org
setlocal
cd /d "%~dp0" || (echo Cannot open the Ragnarok folder: "%~dp0" & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo Ragnarok stopped. Launcher log: "%~dp0logs\run.log"
) else (
  echo Ragnarok failed with exit code %RC%. Read the ERROR line above. Full log: "%~dp0logs\run.log"
)
pause
exit /b %RC%
