import logging
from pathlib import Path

from flask import Flask
from flask_jwt_extended import JWTManager

from app.config import Config
from app.extensions import db, jwt, bcrypt, cors, limiter
from app.utils.responses import error_response

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


def create_app(config_object=Config):
    """Builds and configures the Flask application: extensions, blueprints, and error handlers."""
    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
    app.config.from_object(config_object)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db.init_app(app)
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
