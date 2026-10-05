@echo off
setlocal EnableExtensions
rem ============================================================
rem  RadarScope - server stop script (Windows)
rem  Usage: stop_server.bat [port]   (default 8125)
rem ============================================================
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8125"

set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    set "FOUND=1"
    echo [RADAR] stopping PID %%p on port %PORT%
    taskkill /PID %%p /F >nul 2>&1
)
if not defined FOUND echo [RADAR] no server is listening on port %PORT%.
endlocal
