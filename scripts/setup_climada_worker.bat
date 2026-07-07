@echo off
rem Double-clickable Windows installer for the CLIMADA worker env.
rem Thin bootstrap: all real logic lives in setup_climada_worker.ps1 (same
rem contract as the macOS/Linux setup_climada_worker.sh). Keeps the console
rem window open at the end so double-click users can read the outcome.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_climada_worker.ps1"
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% neq 0 (
    echo Setup FAILED with exit code %EXITCODE%. See messages above.
) else (
    echo Setup finished successfully.
)
pause
exit /b %EXITCODE%
