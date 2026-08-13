"""Standalone-worker configuration. Reads the same .env as the Flask backend
so both processes agree on DB/SMTP/monitoring settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
load_dotenv(BACKEND_DIR / ".env")

# How often the scheduler wakes up to check which applications are due for a
# health check. Individual applications are only actually checked once their
# own monitoring_interval has elapsed since their last check.
POLL_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL", 30))

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "monitor.log"
