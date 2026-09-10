@echo off
REM ===========================================================================
REM  Centralized Monitoring Agent - one-file installer
REM
REM  Right-click this file and choose "Run as administrator", or from a script:
REM      install-agent.bat <admin-token> [platform-host]
REM
REM  Does everything: downloads the agent, installs dependencies, enrols this
REM  machine, registers the Windows service with crash recovery, and verifies.
REM  Safe to re-run - re-enrolling rotates this machine's token.
REM ===========================================================================
setlocal EnableDelayedExpansion

set "PLATFORM=%~2"
if "%PLATFORM%"=="" set "PLATFORM=FUJALW-LAP-STENITTE:5000"
set "SRC=http://%PLATFORM%/downloads"
set "TARGET=C:\AMNSAgent"

echo.
echo  Centralized Monitoring Agent installer
echo  Platform: %PLATFORM%
echo  ---------------------------------------------------------------

REM --- must be elevated: registering a service is not a user-level action ---
net session >nul 2>&1
if errorlevel 1 (
    echo  [X] Not running as Administrator.
    echo      Right-click this file and choose "Run as administrator".
    goto :fail
)

REM --- Python must be present and on PATH ---
python --version >nul 2>&1
if errorlevel 1 (
    echo  [X] Python is not installed, or not on PATH.
    echo      Install Python 3.10 or later, ticking "Add python.exe to PATH".
    goto :fail
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  [OK] %%v

REM --- token: argument for scripted installs, prompt for a person ---
set "TOKEN=%~1"
if "%TOKEN%"=="" (
    echo.
    echo  An admin token is needed to enrol this machine.
    echo  Get one: log in to the platform as ADMIN, press F12,
    echo  Application -^> Local Storage -^> copy "access_token".
    echo.
    set /p "TOKEN=Paste the admin token: "
)
if "!TOKEN!"=="" (
    echo  [X] No token given - cannot enrol.
    goto :fail
)

REM --- download ---
if not exist "%TARGET%" mkdir "%TARGET%"
cd /d "%TARGET%"
echo.
echo  Downloading from %SRC% ...
for %%f in (agent.py agent_config.py agent_service.py requirements.txt) do (
    curl.exe -sf -o "%%f" "%SRC%/%%f"
    if errorlevel 1 (
        echo  [X] Could not download %%f from %SRC%
        echo      Check the platform is running and reachable by name from here.
        goto :fail
    )
)
REM A 404 page saves as a small HTML file and looks like a successful download
REM until the service will not start. Checked here instead.
findstr /c:"AGENT_VERSION" agent.py >nul
if errorlevel 1 (
    echo  [X] agent.py is not the agent - the download returned an error page.
    goto :fail
)
for /f "tokens=3 delims== " %%v in ('findstr /c:"AGENT_VERSION =" agent.py') do echo  [OK] agent %%v

REM --- dependencies ---
REM --no-user matters: without it pip installs into the calling profile, the
REM service runs as LocalSystem, cannot see them, and dies on start while the
REM install reports success.
echo  Installing dependencies ...
python -m pip install --quiet --no-user -r requirements.txt
if errorlevel 1 (
    echo  [X] pip install failed.
    goto :fail
)

REM --- enrol ---
echo  Enrolling this machine ...
python agent.py enroll --admin-token "!TOKEN!" --api "http://%PLATFORM%/api"
if errorlevel 1 (
    echo  [X] Enrolment failed - the token may be expired. Log in again for a fresh one.
    goto :fail
)

REM --- service, with recovery so a crash does not leave this machine blind ---
echo  Registering the Windows service ...
python agent_service.py --startup auto install >nul 2>&1
python agent_service.py start >nul 2>&1
sc.exe failure AMNSAgent reset= 86400 actions= restart/60000/restart/60000/restart/60000 >nul

REM --- verify: the service must actually be running, not merely installed ---
timeout /t 5 /nobreak >nul
sc.exe query AMNSAgent | findstr /c:"RUNNING" >nul
if errorlevel 1 (
    echo.
    echo  [X] The service was installed but is not running.
    echo      Check the Windows Event Log, Application, for "AMNS Agent crashed".
    goto :fail
)

echo.
echo  ---------------------------------------------------------------
echo   Done. %COMPUTERNAME% is now monitored.
echo   It appears on the platform's Servers page within a minute.
echo  ---------------------------------------------------------------
echo.
pause
exit /b 0

:fail
echo.
echo  Installation did not complete. Nothing was left running.
echo.
pause
exit /b 1
