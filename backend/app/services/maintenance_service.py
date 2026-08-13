"""Maintenance windows suppress incidents/alerts for a planned outage
without touching the health-check pipeline itself - checks still run and
record real results, they just don't open an incident or notify anyone."""
from datetime import datetime, timezone

from app.models.maintenance_window import MaintenanceWindow


def _active_windows():
    """Returns all maintenance windows that are currently active (started, not yet ended)."""
    now = datetime.now(timezone.utc)
    return MaintenanceWindow.query.filter(
        MaintenanceWindow.starts_at <= now, MaintenanceWindow.ends_at >= now
    ).all()


def is_in_maintenance(application_id):
    """Checks whether an application is covered by an active global or app-specific maintenance window."""
    return any(
        w.application_id is None or w.application_id == application_id
        for w in _active_windows()
    )


def active_application_ids():
    """Returns (ids, global_active) - ids of applications under an active
    app-specific window, and whether an active global (all-apps) window exists."""
    windows = _active_windows()
    global_active = any(w.application_id is None for w in windows)
    ids = {w.application_id for w in windows if w.application_id is not None}
    return ids, global_active
