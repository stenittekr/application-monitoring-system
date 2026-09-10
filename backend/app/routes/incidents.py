from datetime import datetime

from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.auth.decorators import roles_required
from app.extensions import db
from app.models.incident import Incident
from app.models.user import User
from app.services import incident_service
from app.services.audit_service import log_activity
from app.utils.responses import success_response, error_response

bp = Blueprint("incidents", __name__, url_prefix="/api/incidents")


def _current_user():
    """Fetches the User row for the currently authenticated JWT identity."""
    return db.session.get(User, int(get_jwt_identity()))


def _parse_date(value):
    """Parses an ISO 8601 date string, returning None if it is missing or invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@bp.get("")
@jwt_required()
def list_incidents():
    """Returns incidents filtered by application, status, environment, and date range,
    scoped to owned/managed applications only for an APP_OWNER."""
    application_id = request.args.get("application_id", type=int)
    status = request.args.get("status")
    environment = request.args.get("environment")
    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))

    incidents = incident_service.list_incidents(
        application_id, status, environment, date_from, date_to, user=_current_user()
    )
    return success_response([i.to_dict() for i in incidents])


@bp.get("/<int:incident_id>")
@jwt_required()
def get_incident(incident_id):
    """Returns a single incident by its ID."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    if not incident_service.is_authorized_for_incident(_current_user(), incident):
        return error_response("You do not have access to this incident.", "FORBIDDEN", 403)
    return success_response(incident.to_dict())


@bp.post("/<int:incident_id>/acknowledge")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "APP_OWNER")
def acknowledge_incident(incident_id):
    """Marks an incident acknowledged by the current user, halting further escalation."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    if not incident_service.is_authorized_for_incident(_current_user(), incident):
        return error_response("You do not have access to this incident.", "FORBIDDEN", 403)
    if incident.acknowledged_at:
        return error_response("Incident is already acknowledged.", "ALREADY_ACKNOWLEDGED", 409)
    user_id = int(get_jwt_identity())
    incident_service.acknowledge(incident, user_id)
    log_activity(user_id, "INCIDENT_ACKNOWLEDGED", "Incident", incident.id,
                 f"Incident #{incident.id} acknowledged.", request.remote_addr)
    return success_response(incident.to_dict())


@bp.get("/<int:incident_id>/notes")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "APP_OWNER", "AUDITOR")
def list_notes(incident_id):
    """Investigation notes on an incident, oldest first."""
    from app.models.incident_note import IncidentNote

    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    if not incident_service.is_authorized_for_incident(_current_user(), incident):
        return error_response("You do not have access to this incident.", "FORBIDDEN", 403)
    notes = (IncidentNote.query.filter_by(incident_id=incident_id)
             .order_by(IncidentNote.created_at.asc()).all())
    return success_response([n.to_dict() for n in notes])


@bp.post("/<int:incident_id>/notes")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "APP_OWNER")
def add_note(incident_id):
    """Records what someone found or did. Auditors are excluded: read-only."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    if not incident_service.is_authorized_for_incident(_current_user(), incident):
        return error_response("You do not have access to this incident.", "FORBIDDEN", 403)

    note = str((request.get_json(silent=True) or {}).get("note") or "").strip()
    if not note:
        return error_response("A note cannot be empty.", "VALIDATION_ERROR", 422)

    user_id = int(get_jwt_identity())
    row = incident_service.add_note(incident, user_id, note[:2000])
    log_activity(user_id, "INCIDENT_NOTE_ADDED", "Incident", incident.id,
                 f"Note added to incident #{incident.id}.", request.remote_addr)
    return success_response(row.to_dict(), 201)


@bp.post("/<int:incident_id>/resolve")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "APP_OWNER")
def resolve_incident_manually(incident_id):
    """Closes an incident by hand, with a cause.

    Needed where the platform cannot see the recovery itself - a component
    fixed out of band, or a false alarm from a monitoring gap."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    if not incident_service.is_authorized_for_incident(_current_user(), incident):
        return error_response("You do not have access to this incident.", "FORBIDDEN", 403)
    if incident.status == "RESOLVED":
        return error_response("Incident is already resolved.", "ALREADY_RESOLVED", 409)

    data = request.get_json(silent=True) or {}
    user_id = int(get_jwt_identity())
    incident_service.resolve_manually(
        incident, user_id,
        category=str(data.get("category") or "").strip()[:50] or None,
        note=str(data.get("note") or "").strip()[:1000] or None,
    )
    log_activity(user_id, "INCIDENT_RESOLVED", "Incident", incident.id,
                 f"Incident #{incident.id} resolved manually.", request.remote_addr)
    return success_response(incident.to_dict())


@bp.post("/<int:incident_id>/reopen")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR")
def reopen_incident(incident_id):
    """Reopens a resolved incident when the problem was not actually fixed.

    The reopen count is kept: an incident closed and reopened three times is
    telling you something the resolved timestamp alone does not."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    if incident.status != "RESOLVED":
        return error_response("Only a resolved incident can be reopened.", "NOT_RESOLVED", 409)

    reason = str((request.get_json(silent=True) or {}).get("reason") or "").strip()
    if not reason:
        return error_response("A reason is required to reopen an incident.", "VALIDATION_ERROR", 422)

    user_id = int(get_jwt_identity())
    incident_service.reopen(incident, user_id, reason[:1000])
    log_activity(user_id, "INCIDENT_REOPENED", "Incident", incident.id,
                 f"Incident #{incident.id} reopened: {reason[:200]}", request.remote_addr)
    return success_response(incident.to_dict())


@bp.post("/<int:incident_id>/assign")
@roles_required("ADMIN", "IT_MANAGER")
def assign_incident(incident_id):
    """Assigns an incident to a user for investigation."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if not user_id:
        return error_response("user_id is required.", "VALIDATION_ERROR", 422)
    user = db.session.get(User, user_id)
    if not user:
        return error_response("User not found.", "USER_NOT_FOUND", 404)
    incident_service.assign(incident, user_id)
    log_activity(int(get_jwt_identity()), "INCIDENT_ASSIGNED", "Incident", incident.id,
                 f"Incident #{incident.id} assigned to {user.name}.", request.remote_addr)
    return success_response(incident.to_dict())
