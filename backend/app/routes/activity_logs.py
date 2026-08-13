from datetime import datetime

from flask import Blueprint, request

from app.auth.decorators import roles_required
from app.models.activity_log import ActivityLog
from app.utils.responses import success_response

bp = Blueprint("activity_logs", __name__, url_prefix="/api/activity-logs")


@bp.get("")
@roles_required("ADMIN")
def list_activity_logs():
    """Returns activity log entries filtered by user, entity type, action, and date."""
    query = ActivityLog.query

    user_id = request.args.get("user_id", type=int)
    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)

    entity_type = request.args.get("entity_type")
    if entity_type:
        query = query.filter(ActivityLog.entity_type == entity_type)

    action = request.args.get("action")
    if action:
        query = query.filter(ActivityLog.action == action)

    date_from = request.args.get("date_from")
    if date_from:
        try:
            query = query.filter(ActivityLog.created_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass

    limit = min(request.args.get("limit", default=200, type=int), 2000)
    rows = query.order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return success_response([r.to_dict() for r in rows])
