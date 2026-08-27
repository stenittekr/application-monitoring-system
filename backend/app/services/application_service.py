"""Application CRUD and monitoring-toggle business logic."""
from datetime import datetime, timezone

from app.extensions import db
import json

from app.models.application import Application

APPLICATION_FIELDS = (
    "name", "description", "url", "server", "port", "health_check_type", "environment",
    "owner_name", "owner_email", "manager_name", "manager_email",
    "monitoring_enabled", "monitoring_interval", "timeout",
    "retry_count", "retry_delay", "expected_status_code", "verify_ssl",
    "department", "icon", "baseline_notes", "criticality", "support_hours", "hosted_on_server_id", "network_witness_server_id",
)


def apply_workflow_steps(app_row, data):
    """Stores the synthetic workflow steps when the caller sent them.

    Kept out of APPLICATION_FIELDS because the column holds JSON while the
    payload carries a list, and because an absent key must leave an existing
    workflow alone rather than wiping it."""
    if "workflow_steps" not in data:
        return
    steps = data.get("workflow_steps")
    app_row.workflow_json = json.dumps(steps) if steps else None


def list_applications(user):
    """Returns all non-deleted applications, restricted to owned/managed ones for APP_OWNER users."""
    query = Application.query.filter(Application.deleted_at.is_(None))
    if user.role == "APP_OWNER":
        query = query.filter(
            db.or_(Application.manager_email == user.email, Application.owner_email == user.email)
        )
    return query.order_by(Application.name.asc()).all()


def is_authorized_for_application(user, app_row):
    """Every role except APP_OWNER can see/act on any application; an
    Application Owner is restricted to applications they own or manage."""
    if user.role != "APP_OWNER":
        return True
    return app_row.owner_email == user.email or app_row.manager_email == user.email


def get_application(application_id):
    """Looks up a single non-deleted application by id."""
    return Application.query.filter_by(id=application_id, deleted_at=None).first()


def create_application(data, defaults):
    """Creates a new application row, filling in monitoring defaults for any fields not supplied."""
    health_check_type = (data.get("health_check_type") or "HTTP").upper()
    app_row = Application(
        name=data["name"].strip(),
        description=(data.get("description") or "").strip() or None,
        url=(data.get("url") or "").strip() or None,
        server=(data.get("server") or "").strip() or None,
        port=int(data["port"]) if data.get("port") else None,
        health_check_type=health_check_type,
        environment=(data.get("environment") or "Production").strip(),
        owner_name=(data.get("owner_name") or "").strip(),
        owner_email=data["owner_email"].strip(),
        manager_name=(data.get("manager_name") or "").strip(),
        manager_email=data["manager_email"].strip(),
        monitoring_enabled=bool(data.get("monitoring_enabled", True)),
        monitoring_interval=int(data.get("monitoring_interval") or defaults["interval"]),
        timeout=int(data.get("timeout") or defaults["timeout"]),
        retry_count=int(data.get("retry_count") if data.get("retry_count") is not None else defaults["retry_count"]),
        retry_delay=int(data.get("retry_delay") or defaults["retry_delay"]),
        expected_status_code=int(data.get("expected_status_code") or 200),
        verify_ssl=bool(data.get("verify_ssl", True)),
        department=(data.get("department") or "").strip() or None,
        icon=(data.get("icon") or "").strip() or None,
        current_status="UNKNOWN",
        maturity_status=(data.get("maturity_status") or "MONITORED").upper(),
        baseline_notes=(data.get("baseline_notes") or "").strip() or None,
        depends_on=data.get("depends_on") or [],
    )
    apply_workflow_steps(app_row, data)
    db.session.add(app_row)
    db.session.commit()
    return app_row


def update_application(app_row, data):
    """Updates only the whitelisted fields present in data, normalizing strings/types as needed."""
    for field in APPLICATION_FIELDS:
        if field in data and data[field] is not None:
            value = data[field]
            if field in ("name", "description", "url", "server", "environment", "owner_name",
                          "owner_email", "manager_name", "manager_email") and isinstance(value, str):
                value = value.strip()
            if field == "health_check_type":
                value = str(value).upper()
            if field == "port":
                value = int(value)
            setattr(app_row, field, value)
    apply_workflow_steps(app_row, data)
    if "maturity_status" in data and data["maturity_status"]:
        app_row.maturity_status = str(data["maturity_status"]).upper()
    if "depends_on" in data:
        app_row.depends_on = [i for i in (data["depends_on"] or []) if i != app_row.id]
    app_row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return app_row


def set_monitoring_enabled(app_row, enabled):
    """Toggles monitoring on/off for an application, resetting its status accordingly."""
    app_row.monitoring_enabled = enabled
    if not enabled:
        app_row.current_status = "DISABLED"
    elif app_row.current_status == "DISABLED":
        app_row.current_status = "UNKNOWN"
    app_row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return app_row


def soft_delete_application(app_row):
    """Marks an application as deleted and disables its monitoring, without removing the row."""
    app_row.deleted_at = datetime.now(timezone.utc)
    app_row.monitoring_enabled = False
    app_row.current_status = "DISABLED"
    db.session.commit()
    return app_row
