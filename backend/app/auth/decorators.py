"""Role-based authorization decorators, enforced server-side."""
from functools import wraps

from flask_jwt_extended import verify_jwt_in_request, get_jwt

from app.utils.responses import error_response


def roles_required(*allowed_roles):
    """Restricts an endpoint to the given roles. Always call after @jwt_required()
    is implied - this decorator verifies the JWT itself."""

    def decorator(fn):
        """Wraps the given endpoint function with the role check."""

        @wraps(fn)
        def wrapper(*args, **kwargs):
            """Verifies the JWT and blocks the call unless the user's role is allowed."""
            verify_jwt_in_request()
            claims = get_jwt()
            role = claims.get("role")
            if role not in allowed_roles:
                return error_response(
                    "You do not have permission to perform this action.",
                    "FORBIDDEN",
                    403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
