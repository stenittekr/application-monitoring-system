import secrets

from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.extensions import db
from app.models.user import User, ROLES
from app.auth.decorators import roles_required
from app.services.audit_service import log_activity
from app.utils.responses import success_response, error_response
from app.utils.validators import is_valid_email, is_strong_password

bp = Blueprint("users", __name__, url_prefix="/api/users")


@bp.get("")
@roles_required("ADMIN", "IT_MANAGER")
def list_users():
    """Returns all users ordered by name - IT_MANAGER needs this to assign incidents."""
    users = User.query.order_by(User.name.asc()).all()
    return success_response([u.to_dict() for u in users])


@bp.post("")
@roles_required("ADMIN")
def create_user():
    """Creates a new user account after validating email, password strength, and role.

    Password is optional: leaving it blank is how you add someone who signs in
    with their AD/network password (auth.py falls back to LDAP for a user with
    no matching local password) - they get a random, never-shown local
    password instead of the admin having to invent one that will never be used.
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = (data.get("role") or "AUDITOR").upper()

    if not name or not email:
        return error_response("Name and email are required.", "VALIDATION_ERROR", 422)
    if not is_valid_email(email):
        return error_response("A valid email is required.", "VALIDATION_ERROR", 422)
    if password and not is_strong_password(password):
        return error_response(
            "Password must be at least 8 characters and include a letter and a number.",
            "WEAK_PASSWORD", 422,
        )
    if role not in ROLES:
        return error_response(f"Role must be one of {ROLES}.", "VALIDATION_ERROR", 422)
    if User.query.filter(db.func.lower(User.email) == email).first():
        return error_response("A user with this email already exists.", "DUPLICATE_EMAIL", 409)

    user = User(name=name, email=email, role=role)
    user.set_password(password or secrets.token_urlsafe(32))
    db.session.add(user)
    db.session.commit()

    actor_id = int(get_jwt_identity())
    log_activity(actor_id, "USER_CREATED", "User", user.id, f"Created user {user.name} ({user.role}).",
                 request.remote_addr)
    return success_response(user.to_dict(), 201)


@bp.put("/<int:user_id>")
@roles_required("ADMIN")
def update_user(user_id):
    """Updates a user's name, email, role, active status, or password."""
    user = db.session.get(User, user_id)
    if not user:
        return error_response("User not found.", "USER_NOT_FOUND", 404)

    data = request.get_json(silent=True) or {}
    if "name" in data and data["name"]:
        user.name = data["name"].strip()
    if "email" in data and data["email"]:
        email = data["email"].strip().lower()
        if not is_valid_email(email):
            return error_response("A valid email is required.", "VALIDATION_ERROR", 422)
        existing = User.query.filter(db.func.lower(User.email) == email, User.id != user.id).first()
        if existing:
            return error_response("A user with this email already exists.", "DUPLICATE_EMAIL", 409)
        user.email = email
    if "role" in data and data["role"]:
        role = data["role"].upper()
        if role not in ROLES:
            return error_response(f"Role must be one of {ROLES}.", "VALIDATION_ERROR", 422)
        user.role = role
    if "is_active" in data:
        user.is_active = bool(data["is_active"])
    if "password" in data and data["password"]:
        if not is_strong_password(data["password"]):
            return error_response(
                "Password must be at least 8 characters and include a letter and a number.",
                "WEAK_PASSWORD", 422,
            )
        user.set_password(data["password"])

    db.session.commit()
    actor_id = int(get_jwt_identity())
    action = "USER_DISABLED" if ("is_active" in data and not data["is_active"]) else "USER_UPDATED"
    log_activity(actor_id, action, "User", user.id, f"Updated user {user.name}.", request.remote_addr)
    return success_response(user.to_dict())
