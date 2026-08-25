"""Incident lifecycle: creation, dedup (one active incident per app or server), resolution."""
from datetime import datetime, timezone

from app.extensions import db
from app.models.incident import Incident


def get_active_incident(application_id=None, server_id=None, kind="REACHABILITY"):
    """Returns the most recent OPEN incident of this kind for an application or server."""
    query = Incident.query.filter_by(status="OPEN", kind=kind)
    if application_id:
        query = query.filter_by(application_id=application_id)
    if server_id:
        query = query.filter_by(server_id=server_id)
    return query.order_by(Incident.started_at.desc()).first()


def add_note(incident, user_id, note):
    """Appends an investigation note. Append-only by design - see the model."""
    from app.models.incident_note import IncidentNote

    row = IncidentNote(incident_id=incident.id, user_id=user_id, note=note)
    db.session.add(row)
    db.session.commit()
    return row


def resolve_manually(incident, user_id, category=None, note=None):
    """Closes an incident by hand, recording who and why."""
    resolve_incident(incident, datetime.now(timezone.utc))
    incident.resolved_by_id = user_id
    incident.resolution_category = category
    incident.resolution_note = note
    db.session.commit()
    return incident


def reopen(incident, user_id, reason):
    """Reopens a resolved incident, keeping the original detection time.

    started_at and detected_at are deliberately untouched: the outage began
    when it began, and rewriting that would corrupt every availability figure
    the incident feeds."""
    incident.status = "OPEN"
    incident.resolved_at = None
    incident.duration_seconds = None
    incident.resolved_by_id = None
    incident.reopened_count = (incident.reopened_count or 0) + 1
    # Allow the recovery email to fire again if it recovers a second time.
    incident.recovery_notification_sent = False
    db.session.commit()
    add_note(incident, user_id, f"Reopened: {reason}")
    return incident


def open_incident(entity, detected_at, reason, http_status_code=None, error_message=None,
                  is_server=False, kind="REACHABILITY"):
    """Creates a new incident for an application or server, only if one isn't already open."""
    # The caller only calls this on a DOWN transition, so in practice there should
    # never be an existing OPEN incident here - this guard is a second line of
    # defense against a duplicate incident/email if two monitor cycles ever overlap.
    existing = (get_active_incident(server_id=entity.id, kind=kind) if is_server
                else get_active_incident(application_id=entity.id, kind=kind))
    if existing:
        return existing, False

    incident = Incident(
        application_id=None if is_server else entity.id,
        server_id=entity.id if is_server else None,
        status="OPEN",
        kind=kind,
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


def list_incidents(application_id=None, status=None, environment=None, date_from=None, date_to=None, user=None):
    """Returns incidents matching the given filters, newest first. An APP_OWNER
    only ever sees incidents for applications they own/manage, and never
    server incidents (out of that role's scope per the requirements doc)."""
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
    if user is not None and user.role == "APP_OWNER":
        query = query.filter(
            Incident.server_id.is_(None),
            db.or_(Application.owner_email == user.email, Application.manager_email == user.email),
        )
    return query.order_by(Incident.started_at.desc()).all()


def is_authorized_for_incident(user, incident):
    """Every role except APP_OWNER can see/act on any incident; an
    Application Owner is restricted to incidents on applications they own or
    manage, and never server incidents."""
    if user.role != "APP_OWNER":
        return True
    if incident.server_id is not None:
        return False
    from app.models.application import Application
    app_row = db.session.get(Application, incident.application_id)
    return bool(app_row) and (app_row.owner_email == user.email or app_row.manager_email == user.email)
