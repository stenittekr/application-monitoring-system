"""Writes activity/audit log entries. Never raises - logging must not break requests."""
import json
import logging

from app.extensions import db
from app.models.activity_log import ActivityLog

logger = logging.getLogger(__name__)


def log_activity(user_id, action, entity_type=None, entity_id=None, description=None,
                  ip_address=None, metadata=None):
    """Writes one audit log entry, swallowing any error so logging never breaks the caller's request."""
    try:
        entry = ActivityLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            ip_address=ip_address,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to write activity log for action=%s", action)
