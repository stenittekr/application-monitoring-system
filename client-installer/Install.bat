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

REM --- Python -----------------------------------------------------------------
REM Not "is python on PATH". Windows ships an App Execution Alias in
REM %LOCALAPPDATA%\Microsoft\WindowsApps that looks like Python, exits with
REM code 0, and prints an error instead of running - and from an elevated
REM prompt it fails with 0x80070005 because the Store app is per-user. That
REM stub passed a naive check on AMS-IT-312 and every later step quietly did
REM nothing. So: find a real interpreter, prove it runs, and then use its full
REM path rather than trusting PATH again.
set "PY="
REM Globbed, not a version list: this missed C:\Python314 when the list stopped
REM at 313. Only all-users locations - a Python under a user profile cannot be
REM read by the LocalSystem service that has to run the agent, so finding one
REM there is worse than finding none.
for /d %%d in ("C:\Python3*") do (
    if not defined PY if exist "%%~d\python.exe" set "PY=%%~d\python.exe"
)
if not defined PY for /d %%d in ("C:\Program Files\Python3*") do (
    if not defined PY if exist "%%~d\python.exe" set "PY=%%~d\python.exe"
)

REM Prove it: the stub returns 0, so the only reliable test is whether the
REM expected output actually comes back.
REM
REM Via a temp file, not for/f. `for /f ... in ('"!PY!" -c "print(1)"')`
REM breaks on the nested quotes and reports failure on a machine that has a
REM perfectly good Python - which is exactly how this check first went wrong.
set "PYOK="
set "PROBE=%TEMP%\probe-python.txt"
if defined PY (
    "!PY!" -c "print(4567)" > "!PROBE!" 2>nul
    if exist "!PROBE!" (
        set /p PROBED=<"!PROBE!"
        if "!PROBED!"=="4567" set "PYOK=1"
        del "!PROBE!" >nul 2>&1
    )
)

if not defined PYOK (
    if exist "%~dp0python-setup.exe" (
        echo  [..] No usable Python found - installing it. This takes a few minutes ...
        echo %TIME%  installing bundled python >> "%LOG%"
        "%~dp0python-setup.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_doc=0 Include_tcltk=0
        set "PY="
        for /d %%d in ("C:\Program Files\Python3*") do (
            if not defined PY if exist "%%~d\python.exe" set "PY=%%~d\python.exe"
        )
        if defined PY (
            "!PY!" -c "print(4567)" > "!PROBE!" 2>nul
            if exist "!PROBE!" (
                set /p PROBED=<"!PROBE!"
                if "!PROBED!"=="4567" set "PYOK=1"
                del "!PROBE!" >nul 2>&1
            )
        )
    )
)

if not defined PYOK (
    echo  [X] No working Python on this machine.
    echo.
    echo      A Microsoft Store stub named python.exe does not count - it
    echo      cannot run elevated. Install Python 3.10+ from python.org,
    echo      ticking "Add python.exe to PATH", then run this again.
    echo %TIME%  no usable python >> "%LOG%"
    goto :fail
)
"!PY!" --version > "!PROBE!" 2>&1
set /p PYVER=<"!PROBE!"
del "!PROBE!" >nul 2>&1
echo  [OK] !PYVER!
echo  [OK] using !PY!
echo %TIME%  python: !PY! >> "%LOG%"

if not exist "agent.py" (
    echo  [X] agent.py is not in this folder. Copy the whole folder, not just this file.
    goto :fail
)
for /f "tokens=3 delims== " %%v in ('findstr /c:"AGENT_VERSION =" agent.py') do echo  [OK] agent %%v

set "TOKEN=%~1"
if "%TOKEN%"=="" (
    echo.
    echo  A token is needed once, to enrol this machine.
    echo  Get one from the platform: Servers -^> "Add a machine" -^> Copy.
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
"!PY!" -m pip install --no-user --find-links "%~dp0wheels" -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo  [X] pip install failed. Check this machine can reach the package index,
    echo      or install psutil/requests/pywin32 by hand and re-run.
    goto :fail
)

echo  Enrolling ...
echo %TIME%  enrol >> "%LOG%"
"!PY!" agent.py enroll --admin-token "!TOKEN!" --api "http://%PLATFORM%/api" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo  [X] Enrolment failed.
    echo      Either the token expired - log in again for a fresh one -
    echo      or this machine cannot reach %PLATFORM%.
    goto :fail
)
REM Belt and braces: enrolment writing the config is the proof it worked.
if not exist "C:\ProgramData\AMNS-Agent\config.json" (
    echo  [X] Enrolment reported success but wrote no configuration.
    echo      See %LOG%
    goto :fail
)

echo  Registering the Windows service ...
echo %TIME%  service install >> "%LOG%"
"!PY!" agent_service.py --startup auto install >> "%LOG%" 2>&1
"!PY!" agent_service.py start >> "%LOG%" 2>&1
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
