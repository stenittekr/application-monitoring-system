@echo off
REM Runs the four SQL scripts in database/ against a SQL Server instance using sqlcmd.
REM Requires the sqlcmd utility (installed with SQL Server / SSMS / the "sqlcmd utility" package).

setlocal

set /p SQLSERVER="SQL Server instance (e.g. localhost or localhost\SQLEXPRESS): "
set /p SQLUSER="SQL login (leave blank to use Windows auth): "

set DBDIR=%~dp0..\database

if "%SQLUSER%"=="" (
    set AUTHARGS=-E
) else (
    set /p SQLPASS="Password: "
    set AUTHARGS=-U %SQLUSER% -P %SQLPASS%
)

echo.
echo Running 001_create_database.sql ...
sqlcmd -S %SQLSERVER% %AUTHARGS% -i "%DBDIR%\001_create_database.sql" || goto :error

echo Running 002_create_tables.sql ...
sqlcmd -S %SQLSERVER% %AUTHARGS% -d ApplicationMonitoringDB -i "%DBDIR%\002_create_tables.sql" || goto :error

echo Running 003_create_indexes.sql ...
sqlcmd -S %SQLSERVER% %AUTHARGS% -d ApplicationMonitoringDB -i "%DBDIR%\003_create_indexes.sql" || goto :error

echo Running 004_create_seed_data.sql ...
sqlcmd -S %SQLSERVER% %AUTHARGS% -d ApplicationMonitoringDB -i "%DBDIR%\004_create_seed_data.sql" || goto :error

echo.
echo Database setup complete. Default seed accounts (change these passwords):
echo   admin@example.com   / Admin@123
echo   manager@example.com / Manager@123
echo   viewer@example.com  / Viewer@123
goto :eof

:error
echo.
echo Database setup FAILED. Check the sqlcmd output above.
exit /b 1
