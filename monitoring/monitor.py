"""Entry point for the standalone monitoring service.

Runs independently of the Flask web process - start it separately with:

    python monitoring/monitor.py

It keeps running (and keeps checking applications) even if nobody is
logged into the web UI or the Flask API isn't running.
"""
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

# Make both the backend package (for app.*) and the repo root (for monitoring.*)
# importable regardless of the working directory this script is launched from.
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(REPO_ROOT))

from monitoring.config import LOG_DIR, LOG_FILE, POLL_INTERVAL_SECONDS  # noqa: E402


def _setup_logging():
    """Set up rotating file and console logging for the monitoring worker."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=5)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler(sys.stdout)],
    )


def main():
    """Start the standalone monitoring worker: run one cycle immediately, then keep checking on a schedule."""
    _setup_logging()
    logger = logging.getLogger("monitor")

    from app import create_app
    from monitoring.scheduler import build_scheduler
    from monitoring.health_checker import run_monitoring_cycle

    flask_app = create_app()
    logger.info(
        "Monitoring service starting at %s (poll interval=%ss)",
        datetime.now(timezone.utc).isoformat(),
        POLL_INTERVAL_SECONDS,
    )

    # Run one cycle immediately on startup instead of waiting a full interval.
    with flask_app.app_context():
        run_monitoring_cycle()

    scheduler = build_scheduler(flask_app)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Monitoring service shutting down.")


if __name__ == "__main__":
    main()
