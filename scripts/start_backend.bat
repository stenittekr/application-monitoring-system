@echo off
REM Starts the Flask API (backend/). Creates a venv and installs requirements
REM on first run, then just launches run.py on subsequent runs.

setlocal
cd /d "%~dp0..\backend"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

if not exist ".env" (
    echo No .env found - copying .env.example. Edit backend\.env with your SQL Server details before continuing.
    copy .env.example .env
    pause
)

python run.py
