from datetime import datetime, timezone

from flask import Blueprint, request
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt_identity, get_jwt,
)

from app.extensions import db, limiter
from app.models.user import User
from app.services import ldap_service
from app.services.audit_service import log_activity
from app.utils.responses import success_response, error_response

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
@limiter.limit("10 per minute")
def login():
    """Authenticates a user by email and password and returns a JWT access token."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return error_response("Email and password are required.", "MISSING_CREDENTIALS", 400)

    user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user:
        return error_response("Invalid email or password.", "INVALID_CREDENTIALS", 401)

    # Local password is checked first so existing/demo accounts are unaffected;
    # LDAP is only a fallback, and only for a user that already exists here -
    # it never creates or promotes an account from AD.
    authenticated = user.check_password(password)
    if not authenticated and ldap_service.is_configured():
        authenticated = ldap_service.verify_credentials(user.email, password)
    if not authenticated:
        return error_response("Invalid email or password.", "INVALID_CREDENTIALS", 401)
    if not user.is_active:
        return error_response("This account has been disabled.", "ACCOUNT_DISABLED", 403)

    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()

    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role, "email": user.email})
    log_activity(user.id, "LOGIN", "User", user.id, f"{user.name} logged in.", request.remote_addr)

    return success_response({"access_token": token, "user": user.to_dict()})


@bp.post("/logout")
@jwt_required()
def logout():
    """Logs the current user's logout action and ends the request."""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if user:
        log_activity(user.id, "LOGOUT", "User", user.id, f"{user.name} logged out.", request.remote_addr)
    return success_response({"message": "Logged out."})


@bp.get("/me")
@jwt_required()
def me():
    """Returns the profile of the currently authenticated user."""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return error_response("User not found.", "USER_NOT_FOUND", 404)
    return success_response(user.to_dict())
