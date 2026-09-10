from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.extensions import db, limiter
from app.models.user import User
from app.models.health_check import HealthCheck
from app.models.incident import Incident
from app.auth.decorators import roles_required
from app.services import application_service, monitoring_service, maintenance_service
from app.services.audit_service import log_activity
from app.utils.responses import success_response, error_response
from app.utils.validators import validate_application_payload

bp = Blueprint("applications", __name__, url_prefix="/api/applications")


def _current_user():
    """Fetches the User row for the currently authenticated JWT identity."""
    return db.session.get(User, int(get_jwt_identity()))


def _forbidden_response():
    """Standard 403 for an APP_OWNER reaching outside their own applications."""
    return error_response("You do not have access to this application.", "FORBIDDEN", 403)


@bp.get("")
@jwt_required()
def list_applications():
    """Returns the list of applications visible to the current user, flagged with maintenance status."""
    user = _current_user()
    apps = application_service.list_applications(user)
    maintenance_ids, maintenance_global = maintenance_service.active_application_ids()
    data = []
    for a in apps:
        d = a.to_dict()
        d["in_maintenance"] = maintenance_global or a.id in maintenance_ids
        data.append(d)
    return success_response(data)


@bp.post("")
@roles_required("ADMIN", "IT_MANAGER")
def create_application():
    """Creates a new monitored application from the request payload."""
    data = request.get_json(silent=True) or {}
    errors = validate_application_payload(data)
    if errors:
        return error_response("; ".join(errors), "VALIDATION_ERROR", 422)

    defaults = {
        "interval": current_app.config["MONITOR_INTERVAL"],
        "timeout": current_app.config["DEFAULT_TIMEOUT"],
        "retry_count": current_app.config["DEFAULT_RETRY_COUNT"],
        "retry_delay": current_app.config["DEFAULT_RETRY_DELAY"],
    }
    app_row = application_service.create_application(data, defaults)
    user = _current_user()
    log_activity(user.id, "APPLICATION_CREATED", "Application", app_row.id,
                 f"{user.name} created application {app_row.name}.", request.remote_addr)
    return success_response(app_row.to_dict(), 201)


@bp.get("/<int:application_id>")
@jwt_required()
def get_application(application_id):
    """Returns a single application by its ID."""
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    if not application_service.is_authorized_for_application(_current_user(), app_row):
        return _forbidden_response()
    return success_response(app_row.to_dict())


@bp.put("/<int:application_id>")
@jwt_required()
def update_application(application_id):
    """Updates an existing application's fields and logs any monitoring interval change.
    ADMIN/IT_MANAGER can update any application; APP_OWNER only their own."""
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    user = _current_user()
    if user.role not in ("ADMIN", "IT_MANAGER") and not application_service.is_authorized_for_application(user, app_row):
        return _forbidden_response()

    data = request.get_json(silent=True) or {}
    errors = validate_application_payload(data, partial=True)
    if errors:
        return error_response("; ".join(errors), "VALIDATION_ERROR", 422)

    before_interval = app_row.monitoring_interval
    application_service.update_application(app_row, data, int(get_jwt_identity()))
    description = f"{user.name} updated application {app_row.name}."
    if "monitoring_interval" in data and int(data["monitoring_interval"]) != before_interval:
        description = (
            f"{user.name} changed {app_row.name} monitoring interval "
            f"from {before_interval}s to {app_row.monitoring_interval}s."
        )
    log_activity(user.id, "APPLICATION_UPDATED", "Application", app_row.id, description, request.remote_addr)
    return success_response(app_row.to_dict())


@bp.delete("/<int:application_id>")
@roles_required("ADMIN", "IT_MANAGER")
def delete_application(application_id):
    """Soft-deletes (deactivates) an application."""
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    application_service.soft_delete_application(app_row)
    user = _current_user()
    log_activity(user.id, "APPLICATION_DISABLED", "Application", app_row.id,
                 f"{user.name} deactivated application {app_row.name}.", request.remote_addr)
    return success_response({"message": "Application deactivated."})


@bp.post("/<int:application_id>/check")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "APP_OWNER")
def run_manual_check(application_id):
    """Runs an on-demand health check for the given application - matches the
    doc's "on-demand diagnostics" permission for Operator/App Owner/Manager."""
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    user = _current_user()
    if not application_service.is_authorized_for_application(user, app_row):
        return _forbidden_response()

    health_check = monitoring_service.run_health_check(app_row)
    log_activity(user.id, "MANUAL_HEALTH_CHECK", "Application", app_row.id,
                 f"{user.name} ran a manual health check on {app_row.name}.", request.remote_addr)
    return success_response({"application": app_row.to_dict(), "health_check": health_check.to_dict()})


@bp.post("/<int:application_id>/enable-monitoring")
@roles_required("ADMIN", "IT_MANAGER")
def enable_monitoring(application_id):
    """Turns monitoring on for the given application."""
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    application_service.set_monitoring_enabled(app_row, True)
    user = _current_user()
    log_activity(user.id, "MONITORING_ENABLED", "Application", app_row.id,
                 f"{user.name} enabled monitoring for {app_row.name}.", request.remote_addr)
    return success_response(app_row.to_dict())


@bp.post("/<int:application_id>/disable-monitoring")
@roles_required("ADMIN", "IT_MANAGER")
def disable_monitoring(application_id):
    """Turns monitoring off for the given application."""
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    application_service.set_monitoring_enabled(app_row, False)
    user = _current_user()
    log_activity(user.id, "MONITORING_DISABLED", "Application", app_row.id,
                 f"{user.name} disabled monitoring for {app_row.name}.", request.remote_addr)
    return success_response(app_row.to_dict())


@bp.get("/<int:application_id>/health-checks")
@jwt_required()
def get_health_checks(application_id):
    """Returns the recent health check history for an application."""
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    if not application_service.is_authorized_for_application(_current_user(), app_row):
        return _forbidden_response()
    limit = min(int(request.args.get("limit", 100)), 1000)
    checks = (
        HealthCheck.query.filter_by(application_id=application_id)
        .order_by(HealthCheck.checked_at.desc())
        .limit(limit)
        .all()
    )
    return success_response([c.to_dict() for c in checks])


@bp.get("/<int:application_id>/incidents")
@jwt_required()
def get_application_incidents(application_id):
    """Returns the incidents recorded for an application."""
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    if not application_service.is_authorized_for_application(_current_user(), app_row):
        return _forbidden_response()
    incidents = (
        Incident.query.filter_by(application_id=application_id)
        .order_by(Incident.started_at.desc())
        .all()
    )
    return success_response([i.to_dict() for i in incidents])


@bp.get("/<int:application_id>/diagnose")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR", "APP_OWNER")
@limiter.limit("20 per minute")
def diagnose_application(application_id):
    """Why this application is not working, step by step (§19 diagnostics).

    On demand rather than on the cycle: it makes up to four live probes, and
    nobody needs that every 60 seconds for every application. Rate limited for
    the same reason - it is the one read endpoint that reaches outward, and a
    page refreshing in a loop must not turn into a probe storm.
    """
    from app.services import diagnose_service, server_service

    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    server = (server_service.get_server(app_row.hosted_on_server_id)
              if app_row.hosted_on_server_id else None)
    return success_response(diagnose_service.diagnose(app_row, server))


@bp.get("/<int:application_id>/versions")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR", "APP_OWNER")
def application_versions(application_id):
    """Every stored version of this application's monitoring profile (FR-019)."""
    from app.models.application_version import ApplicationVersion

    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)
    rows = (ApplicationVersion.query
            .filter_by(application_id=application_id)
            .order_by(ApplicationVersion.version.desc())
            .all())
    return success_response([r.to_dict() for r in rows])


@bp.post("/<int:application_id>/rollback/<int:version>")
@roles_required("ADMIN", "IT_MANAGER")
def rollback_application(application_id, version):
    """Restores a previous version of the profile (FR-019, §19 configuration error).

    Restricted to ADMIN and IT_MANAGER: §18 requires approval for configuration
    changes, and a rollback is a configuration change like any other - arguably
    the one most likely to be reached for in a hurry.
    """
    app_row = application_service.get_application(application_id)
    if not app_row:
        return error_response("Application not found.", "APPLICATION_NOT_FOUND", 404)

    actor_id = int(get_jwt_identity())
    restored, error = application_service.rollback_application(app_row, version, actor_id)
    if error:
        return error_response(error, "VERSION_NOT_FOUND", 404)

    log_activity(actor_id, "APPLICATION_ROLLED_BACK", "Application", app_row.id,
                 f"Restored {app_row.name} to version {version}.")
    return success_response(restored.to_dict())
