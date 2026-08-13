from flask import Blueprint, request

from app.auth.decorators import roles_required
from app.extensions import limiter
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
    return success_response({"status": "ok", "next_heartbeat_in": server.heartbeat_interval_seconds})
