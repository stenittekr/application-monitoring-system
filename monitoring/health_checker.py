"""Finds applications due for a check and runs them, isolating per-app failures
so one bad application (or one bad check) never stops the monitoring cycle."""
import logging
from datetime import datetime, timedelta, timezone

from monitoring.config import POLL_INTERVAL_SECONDS

from app.extensions import db
from app.models.application import Application
from app.models.system_setting import SystemSetting
from app.services.monitoring_service import run_health_check, apply_transition_from
from app.services import capacity_service, retention_service
from app.services.notification_service import (retry_failed_notifications, check_escalations,
                                                 send_daily_digest)
from app.services.server_service import check_missed_heartbeats

logger = logging.getLogger("monitor.health_checker")

# If this share of checked targets fails in a single cycle, the monitor is the
# more likely fault. Needs a minimum sample: with one application, "all of them
# failed" is just that application being down.
BLIND_FAILURE_RATIO = 0.8
BLIND_MINIMUM_TARGETS = 3

# A cycle arriving this many times later than scheduled means the monitor was
# not running - suspended laptop, stopped service, restarted host. Everything it
# then observes describes its own absence, not the estate's health.
BLIND_GAP_MULTIPLIER = 4
LAST_CYCLE_SETTING = "last_monitoring_cycle_at"


def _previous_cycle_gap_seconds(now):
    """Seconds since the last completed cycle, or None if unknown (first run)."""
    row = SystemSetting.query.filter_by(setting_key=LAST_CYCLE_SETTING).first()
    if not row or not row.setting_value:
        return None
    try:
        previous = datetime.fromisoformat(row.setting_value)
    except ValueError:
        return None
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    return (now - previous).total_seconds()


def _record_cycle(now):
    """Stamps this cycle so the next one can measure the gap."""
    row = SystemSetting.query.filter_by(setting_key=LAST_CYCLE_SETTING).first()
    if row:
        row.setting_value = now.isoformat()
    else:
        db.session.add(SystemSetting(setting_key=LAST_CYCLE_SETTING, setting_value=now.isoformat()))
    db.session.commit()


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

    # A gap means this process was not running. Whatever the checks below say,
    # they describe the monitor's own absence, so nothing is believed this cycle.
    gap = _previous_cycle_gap_seconds(now)
    stalled = gap is not None and gap > POLL_INTERVAL_SECONDS * BLIND_GAP_MULTIPLIER

    # Results are collected first and judged second. Opening incidents inline
    # would mean the first failure has already emailed before we notice that
    # every other target failed in the same instant.
    due = [a for a in applications if _is_due(a, now)]
    checked = []
    for application in due:
        try:
            checked.append((application, run_health_check(application, apply_transition=False)))
        except Exception:
            db.session.rollback()
            logger.exception("Health check failed unexpectedly for application id=%s", application.id)

    failed = [hc for _, hc in checked if not hc.success]
    mass_failure = (
        len(checked) >= BLIND_MINIMUM_TARGETS
        and len(failed) >= len(checked) * BLIND_FAILURE_RATIO
    )
    blind = stalled or mass_failure

    if blind:
        reason = (f"no cycle for {gap:.0f}s (interval {POLL_INTERVAL_SECONDS}s)" if stalled
                  else f"{len(failed)}/{len(checked)} targets failed at once")
        # Results are still recorded - the evidence is kept. Only the conclusion
        # is withheld, because the conclusion would be about the wrong machine.
        logger.error("MONITORING GAP - %s. Results recorded; no incidents opened or alerts sent "
                      "this cycle. Investigate this host's connectivity, not the targets.", reason)
    else:
        for application, health_check in checked:
            try:
                apply_transition_from(application, health_check)
            except Exception:
                db.session.rollback()
                logger.exception("Could not apply status transition for application id=%s", application.id)

    try:
        # Same reasoning for agents: a monitor that was asleep sees every agent
        # as silent, and would raise an unreachable incident for all of them.
        check_missed_heartbeats(suppress_incidents=blind)
    except Exception:
        db.session.rollback()
        logger.exception("Failed while checking server heartbeats")

    try:
        _record_cycle(now)
    except Exception:
        db.session.rollback()
        logger.exception("Could not record cycle timestamp")

    try:
        for server in list_servers():
            capacity_service.record_disk_reading(server, now)
    except Exception:
        db.session.rollback()
        logger.exception("Could not record capacity readings")

    try:
        retention_service.purge_if_due(now)
    except Exception:
        db.session.rollback()
        logger.exception("Retention purge failed")

    try:
        retry_failed_notifications()
    except Exception:
        db.session.rollback()
        logger.exception("Failed while retrying pending email notifications")

    try:
        send_daily_digest(now)
    except Exception:
        db.session.rollback()
        logger.exception("Could not send the daily digest")

    try:
        check_escalations()
    except Exception:
        db.session.rollback()
        logger.exception("Failed while checking incident escalations")

    if due:
        logger.info("Checked %d application(s) this cycle.", len(due))
