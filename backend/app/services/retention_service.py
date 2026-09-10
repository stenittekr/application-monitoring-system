"""Deletes data older than its configured retention (§17).

Nothing was ever purged, so health checks, incidents, changes and notifications
grew without limit on a SQLite file in a synced folder.

Retention is per data type because the reasons differ: health checks are bulk
and lose value in weeks, incidents feed management reporting for years, and
audit records are tamper-evidence (§18) and are not touched here at all.

A setting of 0 means keep forever, which is also what an unset setting means -
so a table nobody has configured is never at risk.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.health_check import HealthCheck
from app.models.incident import Incident
from app.models.notification import Notification
from app.models.server_change import ServerChange
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

LAST_PURGE_SETTING = "last_purge_at"

# (model, timestamp column, setting key, default days)
RULES = (
    (HealthCheck, HealthCheck.checked_at, "retention_health_checks_days", 90),
    (Incident, Incident.started_at, "retention_incidents_days", 730),
    (ServerChange, ServerChange.detected_at, "retention_server_changes_days", 365),
    (Notification, Notification.created_at, "retention_notifications_days", 180),
)


def _days(key, default):
    row = SystemSetting.query.filter_by(setting_key=key).first()
    try:
        return int(row.setting_value) if row and row.setting_value else default
    except ValueError:
        return default


def purge_expired():
    """Deletes expired rows. Returns {table: rows_deleted}."""
    deleted = {}
    for model, column, key, default in RULES:
        days = _days(key, default)
        if days <= 0:
            continue  # keep forever
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = model.query.filter(column < cutoff)
        if model is Incident:
            # An open incident is current, however old it is. Deleting one would
            # remove the outage from the dashboard while it is still happening.
            query = query.filter(Incident.status != "OPEN")
        count = query.delete(synchronize_session=False)
        if count:
            deleted[model.__tablename__] = count
    db.session.commit()
    if deleted:
        logger.info("Retention purge removed %s", deleted)
    return deleted


def purge_if_due(now, min_hours=24):
    """Runs the purge at most once a day. Returns the result, or None if not due."""
    row = SystemSetting.query.filter_by(setting_key=LAST_PURGE_SETTING).first()
    if row and row.setting_value:
        try:
            last = datetime.fromisoformat(row.setting_value)
            last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            if now - last < timedelta(hours=min_hours):
                return None
        except ValueError:
            pass  # unreadable stamp: purge and rewrite it
    result = purge_expired()
    if row:
        row.setting_value = now.isoformat()
    else:
        db.session.add(SystemSetting(setting_key=LAST_PURGE_SETTING,
                                     setting_value=now.isoformat()))
    db.session.commit()
    return result
