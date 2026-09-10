@echo off
REM ==========================================================================
REM Creates ApplicationMonitoringDB and runs every migration in database/,
REM in filename order. Safe to re-run: each script guards its own changes.
REM
REM Requires sqlcmd (installed with SQL Server, SSMS, or the sqlcmd utility).
REM ==========================================================================

setlocal enabledelayedexpansion

set /p SQLSERVER="SQL Server instance (e.g. localhost or localhost\SQLEXPRESS): "
set /p SQLUSER="SQL login (leave blank to use Windows auth): "

set DBDIR=%~dp0..\database

if "%SQLUSER%"=="" (
    set AUTHARGS=-E
) else (
    set /p SQLPASS="Password: "
    set AUTHARGS=-U !SQLUSER! -P !SQLPASS!
)

echo.
echo Creating the database if it does not exist...
sqlcmd -S %SQLSERVER% %AUTHARGS% -b -i "%DBDIR%\001_create_database.sql" || goto :error

REM Everything after 001 runs inside the database. Sorted so 002 precedes 010.
for /f "delims=" %%F in ('dir /b /on "%DBDIR%\*.sql"') do (
    if /i not "%%F"=="001_create_database.sql" (
        echo Running %%F ...
        sqlcmd -S %SQLSERVER% %AUTHARGS% -b -d ApplicationMonitoringDB -i "%DBDIR%\%%F" || goto :error
    )
)

echo.
echo Database ready. Seed logins created by 004 ^(change these immediately^):
echo    admin@example.com / Admin@123
goto :eof

:error
echo.
echo FAILED - see the sqlcmd output above. Nothing after the failing script ran.
exit /b 1
