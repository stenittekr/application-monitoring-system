@echo off
REM ===========================================================================
REM  Centralized Monitoring Agent - offline installer
REM
REM  Copy this whole folder to the machine, then right-click Install.bat and
REM  choose "Run as administrator".
REM
REM  Everything installs from the files beside this one - nothing is downloaded,
REM  so no machine needs to reach a download server to be set up.
REM
REM  Scripted (GPO, SCCM, a loop over hostnames):
REM      Install.bat <admin-token> <platform-host:port>
REM ===========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- keep a record ----------------------------------------------------------
REM The window closing with nothing on screen has happened, and left nothing to
REM look at. Everything from here is echoed to a log beside this file, so a
REM failed install can be diagnosed after the fact instead of re-run blind.
set "LOG=%~dp0install-log.txt"
echo ============================================================ >> "%LOG%"
echo %DATE% %TIME%  %COMPUTERNAME%  install started >> "%LOG%"

REM Where the agent will report to. Set PLATFORM once, here, before sharing this
REM folder - then whoever runs it does not have to know or type it.
set "PLATFORM=%~2"
if "%PLATFORM%"=="" set "PLATFORM=AWGTC-PORTAL-QAS:5000"

set "TARGET=C:\AMNSAgent"

echo.
echo  Centralized Monitoring Agent
echo  Installing on %COMPUTERNAME%, reporting to %PLATFORM%
echo  ---------------------------------------------------------------

net session >nul 2>&1
if errorlevel 1 (
    echo  [X] Not running as Administrator.
    echo      Right-click Install.bat and choose "Run as administrator".
    goto :fail
)

REM --- Python, installed silently if this folder carries the installer --------
REM A normal user's PC does not have Python, and telling 200 people to install
REM it first is how a rollout stalls. Drop the official installer into this
REM folder as python-setup.exe and the agent brings its own runtime.
python --version >nul 2>&1
if errorlevel 1 (
    if exist "%~dp0python-setup.exe" (
        echo  [..] Python not found - installing it, this takes a few minutes ...
        REM InstallAllUsers so the LocalSystem service can see it; PrependPath
        REM so "python" resolves; Test/Doc/tcltk skipped, nothing here needs them.
        "%~dp0python-setup.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_doc=0 Include_tcltk=0
        REM PrependPath only affects new processes, so this one has to be told.
        for /d %%d in ("C:\Program Files\Python3*") do set "PATH=%%d;%%d\Scripts;!PATH!"
        python --version >nul 2>&1
        if errorlevel 1 (
            echo  [X] Python installed but is still not on PATH.
            echo      Restart this machine and run Install.bat again.
            goto :fail
        )
    ) else (
        echo  [X] Python is not installed on this machine.
        echo.
        echo      Either install Python 3.10+ from python.org, ticking
        echo      "Add python.exe to PATH" - or ask IT for the installer
        echo      package that includes it.
        goto :fail
    )
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  [OK] %%v

if not exist "agent.py" (
    echo  [X] agent.py is not in this folder. Copy the whole folder, not just this file.
    goto :fail
)
for /f "tokens=3 delims== " %%v in ('findstr /c:"AGENT_VERSION =" agent.py') do echo  [OK] agent %%v

set "TOKEN=%~1"
if "%TOKEN%"=="" (
    echo.
    echo  An admin token is needed once, to enrol this machine.
    echo  Get one: log in to the platform as ADMIN, press F12,
    echo  Application -^> Local Storage -^> copy "access_token".
    echo.
    set /p "TOKEN=Paste the admin token: "
)
if "!TOKEN!"=="" (
    echo  [X] No token given - cannot enrol.
    goto :fail
)

REM --- copy the agent somewhere permanent -------------------------------------
REM Not run from the shared folder: that folder is a copy someone made, and the
REM service would break the day it is deleted.
if not exist "%TARGET%" mkdir "%TARGET%"
copy /y agent.py agent_config.py agent_service.py requirements.txt "%TARGET%" >nul
cd /d "%TARGET%"

REM --- dependencies -----------------------------------------------------------
REM --no-user is not optional: without it pip installs into the calling profile,
REM the service runs as LocalSystem, cannot see them, and dies on start while
REM the install reports success.
echo  Installing dependencies ...
echo %TIME%  pip install >> "%LOG%"
REM --find-links prefers wheels shipped beside this file and is harmless when
REM there are none. That is the escape hatch for a machine whose proxy blocks
REM PyPI: run  pip download -r requirements.txt -d wheels  somewhere that can
REM reach it, drop the folder in here, and the install needs no internet.
python -m pip install --no-user --find-links "%~dp0wheels" -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo  [X] pip install failed. Check this machine can reach the package index,
    echo      or install psutil/requests/pywin32 by hand and re-run.
    goto :fail
)

echo  Enrolling ...
echo %TIME%  enrol >> "%LOG%"
python agent.py enroll --admin-token "!TOKEN!" --api "http://%PLATFORM%/api" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo  [X] Enrolment failed.
    echo      Either the token expired - log in again for a fresh one -
    echo      or this machine cannot reach %PLATFORM%.
    goto :fail
)

echo  Registering the Windows service ...
echo %TIME%  service install >> "%LOG%"
python agent_service.py --startup auto install >> "%LOG%" 2>&1
python agent_service.py start >> "%LOG%" 2>&1
REM Three restarts a minute apart. Without this a crashed agent stays crashed,
REM and the machine is unmonitored until somebody notices.
sc.exe failure AMNSAgent reset= 86400 actions= restart/60000/restart/60000/restart/60000 >nul

timeout /t 5 /nobreak >nul
sc.exe query AMNSAgent | findstr /c:"RUNNING" >nul
if errorlevel 1 (
    echo.
    echo  [X] The service installed but is not running.
    echo      Windows Event Log, Application, look for "AMNS Agent crashed".
    goto :fail
)

echo.
echo  ---------------------------------------------------------------
echo   Done. %COMPUTERNAME% is monitored and will start itself after a reboot.
echo   It appears on the Servers page within a minute.
echo  ---------------------------------------------------------------
echo.
echo %DATE% %TIME%  SUCCESS >> "%LOG%"
pause
exit /b 0

:fail
echo.
echo  Installation did not complete. Nothing was left running.
echo  A log was written to: %LOG%
echo.
echo %DATE% %TIME%  FAILED >> "%LOG%"
pause
exit /b 1
