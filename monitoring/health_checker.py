"""Finds applications due for a check and runs them, isolating per-app failures
so one bad application (or one bad check) never stops the monitoring cycle."""
import logging
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.application import Application
from app.services.monitoring_service import run_health_check
from app.services.notification_service import retry_failed_notifications
from app.services.server_service import check_missed_heartbeats

logger = logging.getLogger("monitor.health_checker")


def _is_due(application, now):
    """Return True if enough time has passed since the application's last check."""
    if application.last_checked_at is None:
        return True
    last_checked = application.last_checked_at
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)
    return now - last_checked >= timedelta(seconds=application.monitoring_interval)


def run_monitoring_cycle():
    """One pass: check every due application, then retry any failed emails.
    Safe to call repeatedly; each app is independent so partial failures
    (a bad URL, a DB hiccup) don't block the rest of the fleet."""
    now = datetime.now(timezone.utc)
    try:
        applications = Application.query.filter(
            Application.monitoring_enabled.is_(True),
            Application.deleted_at.is_(None),
        ).all()
    except Exception:
        logger.exception("Could not query applications - is SQL Server reachable?")
        return

    due = [a for a in applications if _is_due(a, now)]
    for application in due:
        try:
            run_health_check(application)
        except Exception:
            db.session.rollback()
            logger.exception("Health check failed unexpectedly for application id=%s", application.id)

    try:
        check_missed_heartbeats()
    except Exception:
        db.session.rollback()
        logger.exception("Failed while checking server heartbeats")

    try:
        retry_failed_notifications()
    except Exception:
        db.session.rollback()
        logger.exception("Failed while retrying pending email notifications")

    if due:
        logger.info("Checked %d application(s) this cycle.", len(due))
