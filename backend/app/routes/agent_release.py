from flask import Blueprint, Response, request

from app.services import server_service
from app.utils.responses import error_response

bp = Blueprint("agent_release", __name__, url_prefix="/api/agent")


@bp.get("/download")
def download():
    """Serves the current agent.py to an agent that was told to UPDATE.

    Authenticated the same way as a heartbeat (server_id + its own secret
    token, not a user JWT) - an agent is not a logged-in user, and this file
    is not a secret, but only an enrolled machine gets to ask for it."""
    server_id = request.args.get("server_id")
    token = request.headers.get("X-Agent-Token")
    if not server_id or not token:
        return error_response("server_id and X-Agent-Token header are required.", "MISSING_CREDENTIALS", 400)

    server = server_service.get_server(server_id)
    if not server or not server_service.verify_token(server, token):
        return error_response("Invalid server_id or token.", "INVALID_AGENT_TOKEN", 401)

    _, _, content = server_service.current_agent_release()
    return Response(content, mimetype="text/x-python")
