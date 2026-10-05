@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ============================================================
rem  RadarScope - server start script (Windows)
rem
rem  Usage:
rem    start_server.bat              LAN default: select NIC, 0.0.0.0:8125
rem    start_server.bat lan 9000     LAN, custom port
rem    start_server.bat local        local: 127.0.0.1:8125, auto-open browser
rem    start_server.bat local 9000   local, custom port
rem
rem  Python resolution order:
rem    1) RADAR_PYTHON env var
rem    2) <repo>\env\python.exe       (packaged conda-pack layout)
rem    3) python on PATH
rem
rem  The RadarScope Server window streams boot info and access logs live;
rem  closing that window stops the service; logs also go to logs\server.log.
rem ============================================================
cd /d "%~dp0.."

set "MODE=%~1"
if "%MODE%"=="" set "MODE=lan"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8125"

if /i "%MODE%"=="local" (
    set "HOST=127.0.0.1"
    set "OPEN=--open"
) else (
    set "HOST=0.0.0.0"
    set "OPEN="
)

if defined RADAR_PYTHON set "PY=%RADAR_PYTHON%"
rem Accept both env layouts: standard venv puts the interpreter in Scripts\,
rem conda / conda-pack puts it at the env root. setup_env.bat creates the
rem former, but a pre-built conda env may be dropped in as the latter.
if not defined PY if exist "env\Scripts\python.exe" set "PY=%CD%\env\Scripts\python.exe"
if not defined PY if exist "env\python.exe" set "PY=%CD%\env\python.exe"
if not defined PY (
    echo.
    echo   [ERROR] Python environment not found.
    echo   Looked for: %CD%\env\Scripts\python.exe
    echo              %CD%\env\python.exe
    echo   This package ships without a Python environment.
    echo   First-time setup: run setup_env.bat in the package root - it creates
    echo   the dedicated venv here and installs all dependencies.
    echo   Or set RADAR_PYTHON to an existing interpreter with the deps installed.
    echo.
    pause
    exit /b 1
)

if not exist logs mkdir logs

set "BIND_IP=%HOST%"
if /i "%MODE%"=="lan" goto :pick_nic
goto :start

rem ------------------------------------------------------------
rem  LAN mode: list all IPv4 NICs, user picks the one to bind
rem ------------------------------------------------------------
:pick_nic
cls
echo ============================================================
echo   RadarScope - select the NIC to bind
echo ============================================================
echo.
set "IDX=0"
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /c:IPv4') do (
    set /a IDX+=1
    echo    !IDX!.  %%i
)
echo.
set "CH="
set /p "CH=Pick a NIC number [1-!IDX!], Enter=bind all (0.0.0.0): "
if "!CH!"=="" goto :start
set "N=0"
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /c:IPv4') do (
    set /a N+=1
    if "!N!"=="!CH!" set "BIND_IP=%%i"
)
cls

:start
rem The unquoted launch form cannot handle a python path with spaces.
echo "%PY%"| findstr /C:" " >nul
if errorlevel 1 goto :no_space
echo.
echo   [ERROR] Python path contains spaces; this launch mode does not support it.
echo   Move RadarScope to a path without spaces (e.g. D:\RADAR-Desktop) and retry.
echo.
pause
exit /b 1

:no_space
echo ============================================================
echo   RadarScope - starting service
echo ============================================================
echo   Mode    : %MODE%
echo   Bind    : %BIND_IP%:%PORT%
echo   Python  : %PY%
echo   Log     : live in server window + logs\server.log
echo ------------------------------------------------------------
if /i "%MODE%"=="lan" echo   [WARNING] LAN mode has NO authentication. Use only on a trusted network.
echo.
echo   [RADAR] opening the server window (title "RadarScope Server")...
echo   [RADAR] weights load takes ~10-30s; then open http://%BIND_IP%:%PORT%/
echo   [RADAR] to stop: close the RadarScope Server window, or run stop_server.bat
echo.
start "RadarScope Server" cmd /k "set PYTHONIOENCODING=gbk & %PY% -u service.py --host %BIND_IP% --port %PORT% %OPEN%"
rem 服务窗口已拉起，本窗口自动关闭（服务信息与日志都在 RadarScope Server 窗口中）
exit /b 0
