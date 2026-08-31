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
    "department", "icon", "baseline_notes", "criticality", "support_hours", "hosted_on_server_id", "network_witness_server_id", "sla_target_percent", "site",
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


# The fields worth restoring. Deliberately not everything: current_status and
# last_checked_at describe what happened, not what was configured, and rolling
# those back would rewrite history rather than configuration.
VERSIONED_FIELDS = APPLICATION_FIELDS + (
    "criticality", "support_hours", "sla_target_percent", "site",
    "hosted_on_server_id", "network_witness_server_id", "workflow_json",
    "depends_on_json", "maturity_status",
)


def snapshot_application(app_row):
    """The configuration of an application, as a plain dict."""
    return {field: getattr(app_row, field, None) for field in VERSIONED_FIELDS}


def record_version(app_row, user_id=None, note=None):
    """Stores the profile as it is now, before a change lands.

    Called before the edit rather than after, so version 1 is what the profile
    looked like before anyone touched it - which is the version someone wants
    back when a change turns out to be wrong.
    """
    import json

    from app.models.application_version import ApplicationVersion

    latest = (ApplicationVersion.query
              .filter_by(application_id=app_row.id)
              .order_by(ApplicationVersion.version.desc())
              .first())
    version = (latest.version + 1) if latest else 1
    row = ApplicationVersion(
        application_id=app_row.id, version=version,
        snapshot_json=json.dumps(snapshot_application(app_row), default=str),
        changed_by_id=user_id, change_note=note,
    )
    db.session.add(row)
    db.session.commit()
    return row


def rollback_application(app_row, version_number, user_id=None):
    """Restores a stored version. Returns (application, error).

    The current profile is snapshotted first, so a rollback is itself
    reversible. Undo that cannot be undone is not a safety feature.
    """
    from app.models.application_version import ApplicationVersion

    target = (ApplicationVersion.query
              .filter_by(application_id=app_row.id, version=version_number)
              .first())
    if not target:
        return None, f"Version {version_number} does not exist for this application."

    record_version(app_row, user_id, note=f"Before rollback to version {version_number}")

    snapshot = target.snapshot
    for field in VERSIONED_FIELDS:
        if field in snapshot:
            setattr(app_row, field, snapshot[field])
    db.session.commit()
    return app_row, None


def update_application(app_row, data, user_id=None):
    """Updates only the whitelisted fields present in data, normalizing strings/types as needed.

    The profile as it stands is versioned first (FR-019), so any change can be
    undone and §19's "retain last valid version" holds without anyone having
    remembered to take a copy.
    """
    record_version(app_row, user_id, note=data.get("change_note"))
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
