"""Incident lifecycle: creation, dedup (one active incident per app or server), resolution."""
from datetime import datetime, timezone

from app.extensions import db
from app.models.incident import Incident


def get_active_incident(application_id=None, server_id=None):
    """Returns the most recent OPEN incident for an application or server, if any."""
    query = Incident.query.filter_by(status="OPEN")
    if application_id:
        query = query.filter_by(application_id=application_id)
    if server_id:
        query = query.filter_by(server_id=server_id)
    return query.order_by(Incident.started_at.desc()).first()


def open_incident(entity, detected_at, reason, http_status_code=None, error_message=None, is_server=False):
    """Creates a new incident for an application or server, only if one isn't already open."""
    # The caller only calls this on a DOWN transition, so in practice there should
    # never be an existing OPEN incident here - this guard is a second line of
    # defense against a duplicate incident/email if two monitor cycles ever overlap.
    existing = get_active_incident(server_id=entity.id) if is_server else get_active_incident(application_id=entity.id)
    if existing:
        return existing, False

    incident = Incident(
        application_id=None if is_server else entity.id,
        server_id=entity.id if is_server else None,
        status="OPEN",
        started_at=detected_at,
        detected_at=detected_at,
        reason=reason,
        http_status_code=http_status_code,
        error_message=error_message,
    )
    db.session.add(incident)
    db.session.commit()
    return incident, True


def resolve_incident(incident, resolved_at):
    """Marks an incident RESOLVED and records how long the outage lasted."""
    incident.status = "RESOLVED"
    incident.resolved_at = resolved_at
    started = incident.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    resolved = resolved_at if resolved_at.tzinfo else resolved_at.replace(tzinfo=timezone.utc)
    incident.duration_seconds = int((resolved - started).total_seconds())
    incident.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return incident


def acknowledge(incident, user_id):
    """Marks an incident acknowledged by a human - stops it from escalating further."""
    incident.acknowledged_at = datetime.now(timezone.utc)
    incident.acknowledged_by_id = user_id
    db.session.commit()
    return incident


def assign(incident, user_id):
    """Assigns an incident to a user for investigation."""
    incident.assigned_to_id = user_id
    db.session.commit()
    return incident


def list_incidents(application_id=None, status=None, environment=None, date_from=None, date_to=None):
    """Returns incidents matching the given filters, newest first."""
    from app.models.application import Application

    query = Incident.query.outerjoin(Application, Incident.application_id == Application.id)
    if application_id:
        query = query.filter(Incident.application_id == application_id)
    if status:
        query = query.filter(Incident.status == status)
    if environment:
        query = query.filter(Application.environment == environment)
    if date_from:
        query = query.filter(Incident.started_at >= date_from)
    if date_to:
        query = query.filter(Incident.started_at <= date_to)
    return query.order_by(Incident.started_at.desc()).all()
