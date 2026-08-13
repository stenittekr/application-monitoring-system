from datetime import datetime

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.models.health_check import HealthCheck
from app.models.application import Application
from app.utils.responses import success_response

bp = Blueprint("health_checks", __name__, url_prefix="/api/health-checks")


@bp.get("")
@jwt_required()
def list_health_checks():
    """Returns health check records filtered by application, status, success, and date range."""
    query = HealthCheck.query.join(Application, Application.id == HealthCheck.application_id)

    application_id = request.args.get("application_id", type=int)
    if application_id:
        query = query.filter(HealthCheck.application_id == application_id)

    status = request.args.get("status")
    if status:
        query = query.filter(HealthCheck.status == status)

    success = request.args.get("success")
    if success is not None:
        query = query.filter(HealthCheck.success == (success.lower() == "true"))

    date_from = request.args.get("date_from")
    if date_from:
        try:
            query = query.filter(HealthCheck.checked_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get("date_to")
    if date_to:
        try:
            query = query.filter(HealthCheck.checked_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass

    limit = min(request.args.get("limit", default=200, type=int), 2000)
    rows = query.order_by(HealthCheck.checked_at.desc()).limit(limit).all()

    results = []
    for row in rows:
        item = row.to_dict()
        item["application_name"] = row.application.name
        results.append(item)
    return success_response(results)
