from datetime import datetime

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.extensions import db
from app.models.maintenance_window import MaintenanceWindow
from app.auth.decorators import roles_required
from app.services.audit_service import log_activity
from app.utils.responses import success_response, error_response

bp = Blueprint("maintenance_windows", __name__, url_prefix="/api/maintenance-windows")


@bp.get("")
@roles_required("ADMIN", "IT_MANAGER")
def list_windows():
    """Returns all maintenance windows, most recent first."""
    rows = MaintenanceWindow.query.order_by(MaintenanceWindow.starts_at.desc()).all()
    return success_response([r.to_dict() for r in rows])


@bp.post("")
@roles_required("ADMIN", "IT_MANAGER")
def create_window():
    """Creates a new scheduled maintenance window."""
    data = request.get_json(silent=True) or {}
    try:
        starts_at = datetime.fromisoformat(data["starts_at"])
        ends_at = datetime.fromisoformat(data["ends_at"])
    except (KeyError, ValueError):
        return error_response("starts_at and ends_at are required, ISO 8601 datetimes.", "VALIDATION_ERROR", 422)
    if ends_at <= starts_at:
        return error_response("ends_at must be after starts_at.", "VALIDATION_ERROR", 422)

    window = MaintenanceWindow(
        application_id=data.get("application_id") or None,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=(data.get("reason") or "").strip() or None,
        created_by=int(get_jwt_identity()),
    )
    db.session.add(window)
    db.session.commit()
    log_activity(
        window.created_by, "MAINTENANCE_WINDOW_CREATED", "MaintenanceWindow", window.id,
        f"Scheduled maintenance for {window.to_dict()['application_name']} "
        f"from {starts_at.isoformat()} to {ends_at.isoformat()}.",
        request.remote_addr,
    )
    return success_response(window.to_dict(), 201)


@bp.delete("/<int:window_id>")
@roles_required("ADMIN", "IT_MANAGER")
def delete_window(window_id):
    """Cancels (deletes) a scheduled maintenance window."""
    window = db.session.get(MaintenanceWindow, window_id)
    if not window:
        return error_response("Maintenance window not found.", "NOT_FOUND", 404)
    description = f"Cancelled maintenance window for {window.to_dict()['application_name']}."
    db.session.delete(window)
    db.session.commit()
    log_activity(int(get_jwt_identity()), "MAINTENANCE_WINDOW_CANCELLED", "MaintenanceWindow", window_id,
                 description, request.remote_addr)
    return success_response({"message": "Maintenance window cancelled."})
