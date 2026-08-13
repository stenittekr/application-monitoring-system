from datetime import datetime

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.extensions import db
from app.models.incident import Incident
from app.services import incident_service
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
