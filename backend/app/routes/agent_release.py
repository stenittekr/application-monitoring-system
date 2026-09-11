from flask import Blueprint, Response, request

from app.services import server_service
from app.utils.responses import error_response, success_response

bp = Blueprint("agent_release", __name__, url_prefix="/api/agent")


def _authenticate_agent():
    """Server_id + its own secret token, the same as a heartbeat - an agent is
    not a logged-in user, so this isn't a JWT. Returns (server, None) or
    (None, error_response) to return directly."""
    server_id = request.args.get("server_id")
    token = request.headers.get("X-Agent-Token")
    if not server_id or not token:
        return None, error_response("server_id and X-Agent-Token header are required.", "MISSING_CREDENTIALS", 400)

    server = server_service.get_server(server_id)
    if not server or not server_service.verify_token(server, token):
        return None, error_response("Invalid server_id or token.", "INVALID_AGENT_TOKEN", 401)
    return server, None


@bp.get("/download")
def download():
    """Serves the current agent.py to an agent that was told to UPDATE. Not a
    secret, but only an enrolled machine gets to ask for it."""
    server, err = _authenticate_agent()
    if err:
        return err

    _, _, content = server_service.current_agent_release()
    return Response(content, mimetype="text/x-python")


# A phone camera photo is comfortably under this; anything larger is not a
# screenshot and not worth this platform holding.
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024


@bp.post("/screenshot")
def upload_screenshot():
    """Accepts the screenshot an agent took because it was told to - phase 1
    of on-demand remote support (see server_service.AGENT_COMMANDS)."""
    server, err = _authenticate_agent()
    if err:
        return err

    image = request.get_data()
    if not image:
        return error_response("No image data in request body.", "VALIDATION_ERROR", 422)
    if len(image) > MAX_SCREENSHOT_BYTES:
        return error_response("Image too large.", "VALIDATION_ERROR", 422)

    server_service.save_screenshot(server, image)
    return success_response({"status": "ok"})
