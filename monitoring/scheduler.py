"""APScheduler wiring for the standalone monitoring worker."""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from monitoring.config import POLL_INTERVAL_SECONDS
from monitoring.health_checker import run_monitoring_cycle

logger = logging.getLogger("monitor.scheduler")


def build_scheduler(flask_app):
    """Create a blocking scheduler that runs the monitoring cycle on a fixed interval."""
    scheduler = BlockingScheduler(timezone="UTC")

    def job():
        # Each cycle needs its own Flask application context to use the
        # SQLAlchemy session/models outside of an HTTP request.
        with flask_app.app_context():
            run_monitoring_cycle()

    # max_instances=1 (the APScheduler default) prevents a second cycle from
    # starting while a slow one is still running, so we never double-check
    # the same application concurrently.
    scheduler.add_job(
        job,
        "interval",
        seconds=POLL_INTERVAL_SECONDS,
        id="monitoring_cycle",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
