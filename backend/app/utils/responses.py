"""Consistent JSON response envelope used by every API endpoint."""
from flask import jsonify


def success_response(data=None, status_code=200):
    """Builds a standard success JSON response wrapping the given data."""
    return jsonify({"success": True, "data": data if data is not None else {}}), status_code


def error_response(message, error_code="ERROR", status_code=400):
    """Builds a standard error JSON response with a message and error code."""
    return (
        jsonify({"success": False, "message": message, "error_code": error_code}),
        status_code,
    )
