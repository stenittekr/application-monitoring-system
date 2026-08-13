"""Re-exports incident lifecycle logic for the standalone worker.

Kept as its own module (per the monitoring/ service layout) but backed by
app.services.incident_service so the API and the worker never disagree on
what counts as an open incident.
"""
from app.services.incident_service import (
    get_active_incident,
    open_incident,
    resolve_incident,
    list_incidents,
)

__all__ = ["get_active_incident", "open_incident", "resolve_incident", "list_incidents"]
