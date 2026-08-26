import logging
from pathlib import Path


from flask import Flask
from flask_jwt_extended import JWTManager

from app.config import Config
from app.extensions import db, jwt, bcrypt, cors, limiter
from app.utils.responses import error_response

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


def _tune_sqlite(app):
    """Makes SQLite survive several processes talking to it at once.

    The platform, the monitoring worker and every agent heartbeat write to the
    same file. Stock SQLite serialises writers behind a 5-second timeout and
    blocks readers while a write is in flight, which surfaces as
    "database is locked" on ordinary page loads.

    WAL lets readers carry on during a write, and a longer busy timeout lets a
    blocked writer wait its turn instead of failing. This is a mitigation, not a
    cure - the real fix is SQL Server, which is what production is meant to use.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    if not str(app.config.get("SQLALCHEMY_DATABASE_URI", "")).startswith("sqlite"):
        return

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        """Applied per connection - SQLite settings do not persist across them."""
        try:
            cursor = dbapi_connection.cursor()
            # WAL is a property of the database file and sticks; set anyway so a
            # fresh file gets it too. Harmless to repeat.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")   # wait 15s, don't fail at once
            cursor.execute("PRAGMA synchronous=NORMAL")   # safe under WAL, far fewer fsyncs
            cursor.close()
        except Exception:  # pragma: no cover - never let tuning break startup
            pass


def create_app(config_object=Config):
    """Builds and configures the Flask application: extensions, blueprints, and error handlers."""
    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
    app.config.from_object(config_object)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db.init_app(app)
    _tune_sqlite(app)

    # Secrets must not reach the log files either (requirements §14/§18).
    from app.utils.redaction import RedactingFilter
    root_logger = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root_logger.filters):
        root_logger.addFilter(RedactingFilter())
    jwt.init_app(app)
    bcrypt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})
    limiter.init_app(app)

    _register_jwt_handlers(jwt)
    _register_blueprints(app)
    _register_error_handlers(app)

    @app.after_request
    def set_secure_headers(response):
        """Adds standard security-related headers to every outgoing response."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/health")
    def health():
        """Returns a simple OK payload used for health-check pings on the API itself."""
        return {"success": True, "data": {"status": "ok"}}

    def _first_line(text):
        """The summary line of a docstring, or an empty string."""
        return (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""

    @app.get("/api")
    def api_index():
        """Lists the API's own routes.

        FR-022 asks for a documented API. Browsing to /api previously returned
        "Resource not found", which is technically correct - it is a prefix, not
        a route - and useless to anyone trying to find their way around.

        Built from the URL map rather than a hand-written list, so it cannot
        drift out of date as endpoints are added.
        """
        routes = []
        for rule in app.url_map.iter_rules():
            if not str(rule).startswith("/api/"):
                continue
            methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
            routes.append({
                "path": str(rule),
                "methods": methods,
                "description": _first_line(app.view_functions[rule.endpoint].__doc__),
            })
        routes.sort(key=lambda r: r["path"])
        return {
            "success": True,
            "data": {
                "name": "Centralized Server & Application Monitoring Platform API",
                "authentication": "Bearer JWT from POST /api/auth/login, except "
                                  "/api/servers/heartbeat which uses the X-Agent-Token header.",
                "endpoint_count": len(routes),
                "endpoints": routes,
            },
        }

    @app.get("/")
    def index():
        """Serves the frontend's index.html for the root route."""
        return app.send_static_file("index.html")

    return app


def _register_blueprints(app):
    """Registers all API route blueprints on the app."""
    from app.routes import auth, applications, incidents, health_checks
    from app.routes import reports, activity_logs, users, settings, maintenance_windows, servers

    app.register_blueprint(auth.bp)
    app.register_blueprint(applications.bp)
    app.register_blueprint(incidents.bp)
    app.register_blueprint(health_checks.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(activity_logs.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(maintenance_windows.bp)
    app.register_blueprint(servers.bp)


def _register_jwt_handlers(jwt_manager: JWTManager):
    """Registers JSON error responses for missing, invalid, and expired JWTs."""

    @jwt_manager.unauthorized_loader
    def missing_token(reason):
        """Returns a 401 JSON error when no auth token was provided."""
        return error_response("Authentication required.", "UNAUTHORIZED", 401)

    @jwt_manager.invalid_token_loader
    def invalid_token(reason):
        """Returns a 401 JSON error when the auth token is invalid."""
        return error_response("Invalid authentication token.", "INVALID_TOKEN", 401)

    @jwt_manager.expired_token_loader
    def expired_token(header, payload):
        """Returns a 401 JSON error when the auth token has expired."""
        return error_response("Session expired, please log in again.", "TOKEN_EXPIRED", 401)


def _register_error_handlers(app):
    """Registers JSON error responses for common HTTP errors and unhandled exceptions."""

    @app.errorhandler(404)
    def not_found(err):
        """Returns a 404 JSON error for unmatched routes."""
        return error_response("Resource not found.", "NOT_FOUND", 404)

    @app.errorhandler(405)
    def method_not_allowed(err):
        """Returns a 405 JSON error when the HTTP method isn't allowed for the route."""
        return error_response("Method not allowed.", "METHOD_NOT_ALLOWED", 405)

    @app.errorhandler(Exception)
    def unhandled_exception(err):
        """Logs any unhandled exception and returns a generic 500 JSON error."""
        app.logger.exception("Unhandled exception")
        return error_response("An unexpected error occurred.", "INTERNAL_ERROR", 500)
