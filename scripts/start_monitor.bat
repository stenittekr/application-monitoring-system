@echo off
REM Starts the standalone monitoring worker (monitoring/monitor.py). Uses the
REM same virtual environment and backend/.env as the Flask API - run
REM start_backend.bat at least once first so both exist.

setlocal
cd /d "%~dp0.."

if not exist "backend\.venv" (
    echo backend\.venv not found - run scripts\start_backend.bat first to set it up.
    exit /b 1
)

call backend\.venv\Scripts\activate.bat
python monitoring\monitor.py
