from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.auth.decorators import roles_required
from app.services.audit_service import log_activity
from app.extensions import db, limiter
from app.services import server_service
from app.utils.responses import success_response, error_response

bp = Blueprint("servers", __name__, url_prefix="/api/servers")

# Servers are out of scope for APP_OWNER per the requirements doc - that role
# is restricted to its own applications, not infrastructure.
VIEW_ROLES = ("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR")


@bp.get("")
@roles_required(*VIEW_ROLES)
def list_servers():
    """Returns every enrolled server, for the dashboard."""
    return success_response([s.to_dict() for s in server_service.list_servers()])


@bp.get("/<int:server_id>")
@roles_required(*VIEW_ROLES)
def get_server(server_id):
    """Returns a single server's detail."""
    server = server_service.get_server(server_id)
    if not server:
        return error_response("Server not found.", "SERVER_NOT_FOUND", 404)
    return success_response(server.to_dict())


@bp.post("/enroll")
@roles_required("ADMIN")
def enroll():
    """Registers a new agent/server and returns its id + one-time secret token."""
    data = request.get_json(silent=True) or {}
    if not (data.get("hostname") or "").strip():
        return error_response("hostname is required.", "VALIDATION_ERROR", 422)
    server, token = server_service.enroll(data)
    payload = server.to_dict()
    payload["token"] = token  # only ever shown once, at enrollment
    return success_response(payload, 201)


@bp.get("/<int:server_id>/changes")
@roles_required(*VIEW_ROLES)
def list_changes(server_id):
    """Inventory changes detected on this server, newest first (FR-006)."""
    from app.models.server_change import ServerChange

    rows = (ServerChange.query.filter_by(server_id=server_id)
            .order_by(ServerChange.detected_at.desc()).limit(200).all())
    return success_response([r.to_dict() for r in rows])


@bp.put("/<int:server_id>/expected")
@roles_required("ADMIN", "IT_MANAGER")
def set_expected_components(server_id):
    """Sets which services and processes this server must be running.

    Restricted to ADMIN/IT_MANAGER: the requirements are explicit that discovery
    results are candidates and an authorised user decides what is monitored."""
    server = server_service.get_server(server_id)
    if not server:
        return error_response("Server not found.", "SERVER_NOT_FOUND", 404)

    data = request.get_json(silent=True) or {}
    services = data.get("services")
    processes = data.get("processes")
    if not isinstance(services, list) or not isinstance(processes, list):
        return error_response("services and processes must both be lists.", "VALIDATION_ERROR", 422)

    server = server_service.set_expected_components(server, services, processes)
    log_activity(int(get_jwt_identity()), "SERVER_COMPONENTS_UPDATED", "Server", server.id,
                 f"{len(services)} service(s), {len(processes)} process(es)")
    return success_response(server.to_dict())


@bp.post("/heartbeat")
@limiter.limit("120 per minute")
def heartbeat():
    """Accepts a periodic heartbeat from an enrolled agent, authenticated by its
    own secret token (not a user JWT - the agent isn't a logged-in user)."""
    data = request.get_json(silent=True) or {}
    server_id = data.get("server_id")
    token = request.headers.get("X-Agent-Token")
    if not server_id or not token:
        return error_response("server_id and X-Agent-Token header are required.", "MISSING_CREDENTIALS", 400)

    server = server_service.get_server(server_id)
    if not server or not server_service.verify_token(server, token):
        return error_response("Invalid server_id or token.", "INVALID_AGENT_TOKEN", 401)

    server_service.record_heartbeat(server, data)
    command = server_service.next_agent_command(server, data.get("agent_version"))
    return success_response({
        "status": "ok",
        "next_heartbeat_in": server.heartbeat_interval_seconds,
        "command": command,
    })


@bp.post("/<int:server_id>/agent-command")
@roles_required("ADMIN")
def send_agent_command(server_id):
    """Queues RESTART, SCREENSHOT, or RESTART_SERVICE for this server's agent,
    applied on its next check-in - phase 1 of on-demand remote support:
    a small, specific, logged set of actions, not an open "run anything"
    channel. An outright crash already recovers on its own (the service's own
    configured recovery) and a version behind what the platform ships
    auto-updates regardless of anyone clicking anything."""
    server = server_service.get_server(server_id)
    if not server:
        return error_response("Server not found.", "SERVER_NOT_FOUND", 404)

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").upper()
    if action not in server_service.AGENT_COMMANDS:
        return error_response(f"action must be one of {server_service.AGENT_COMMANDS}.",
                               "VALIDATION_ERROR", 422)

    params = {}
    if action == "RESTART_SERVICE":
        service_name = (data.get("service_name") or "").strip()
        if not service_name:
            return error_response("service_name is required for RESTART_SERVICE.",
                                   "VALIDATION_ERROR", 422)
        params = {"service_name": service_name}

    server_service.request_agent_command(server, action, params)
    detail = f"Queued {action} for {server.hostname}, applied on its next check-in."
    if params:
        detail += f" ({params})"
    log_activity(int(get_jwt_identity()), "AGENT_COMMAND_QUEUED", "Server", server.id, detail,
                 request.remote_addr)
    return success_response(server.to_dict())


@bp.get("/<int:server_id>/screenshot")
@roles_required(*VIEW_ROLES)
def get_screenshot(server_id):
    """Serves the most recent screenshot taken of this server, if any."""
    from flask import send_file

    server = server_service.get_server(server_id)
    if not server or not server.last_screenshot_at:
        return error_response("No screenshot has been taken of this server yet.",
                               "SCREENSHOT_NOT_FOUND", 404)
    path = server_service.screenshot_path(server.id)
    if not path.exists():
        return error_response("No screenshot has been taken of this server yet.",
                               "SCREENSHOT_NOT_FOUND", 404)
    return send_file(path, mimetype="image/png", max_age=0)


@bp.put("/<int:server_id>/alert-scope")
@roles_required("ADMIN", "IT_MANAGER")
def set_alert_scope(server_id):
    """Marks a server as monitoring infrastructure, so its alerts stop at its owner.

    The machine running the monitoring platform generates incidents about
    itself - resource spikes, missed heartbeats when it is moved - which are
    real, worth recording, and of no interest to the people who need to hear
    about production.
    """
    server = server_service.get_server(server_id)
    if not server:
        return error_response("Server not found.", "SERVER_NOT_FOUND", 404)

    from app.models.server import Server

    scope = str((request.get_json(silent=True) or {}).get("alert_scope") or "").upper()
    if scope not in Server.ALERT_SCOPES:
        return error_response(f"alert_scope must be one of {Server.ALERT_SCOPES}.",
                              "VALIDATION_ERROR", 422)

    server.alert_scope = scope
    db.session.commit()
    log_activity(int(get_jwt_identity()), "SERVER_ALERT_SCOPE_CHANGED", "Server", server.id,
                 {"ALL": "everyone", "OWNER": "owner only", "NONE": "nobody"}[scope])
    return success_response(server.to_dict())


@bp.get("/<int:server_id>/capacity")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR", "APP_OWNER")
def server_capacity(server_id):
    """Disk growth rate and days until full (§8 growth trend, §19 disk fills rapidly).

    Returns null when there is not enough history to say. A percentage tells you
    a disk is 84% full; it cannot tell you whether that took two years or two
    days, and only one of those needs doing something about this week.
    """
    from app.services import capacity_service

    server = server_service.get_server(server_id)
    if not server:
        return error_response("Server not found.", "SERVER_NOT_FOUND", 404)
    return success_response({"server_id": server.id,
                             "forecast": capacity_service.disk_forecast(server),
                             "history": capacity_service.disk_history(server)})
