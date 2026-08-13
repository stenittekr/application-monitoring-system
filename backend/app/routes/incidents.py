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
    """Returns incidents filtered by application, status, environment, and date range."""
    application_id = request.args.get("application_id", type=int)
    status = request.args.get("status")
    environment = request.args.get("environment")
    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))

    incidents = incident_service.list_incidents(application_id, status, environment, date_from, date_to)
    return success_response([i.to_dict() for i in incidents])


@bp.get("/<int:incident_id>")
@jwt_required()
def get_incident(incident_id):
    """Returns a single incident by its ID."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    return success_response(incident.to_dict())


@bp.post("/<int:incident_id>/acknowledge")
@roles_required("ADMIN", "MANAGER")
def acknowledge_incident(incident_id):
    """Marks an incident acknowledged by the current user, halting further escalation."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        return error_response("Incident not found.", "INCIDENT_NOT_FOUND", 404)
    if incident.acknowledged_at:
        return error_response("Incident is already acknowledged.", "ALREADY_ACKNOWLEDGED", 409)
    user_id = int(get_jwt_identity())
    incident_service.acknowledge(incident, user_id)
    log_activity(user_id, "INCIDENT_ACKNOWLEDGED", "Incident", incident.id,
                 f"Incident #{incident.id} acknowledged.", request.remote_addr)
    return success_response(incident.to_dict())


@bp.post("/<int:incident_id>/assign")
@roles_required("ADMIN", "MANAGER")
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
