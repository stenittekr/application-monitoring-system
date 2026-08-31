from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.extensions import db
from app.models.system_setting import SystemSetting
from app.auth.decorators import roles_required
from app.services.audit_service import log_activity
from app.utils.responses import success_response, error_response

bp = Blueprint("settings", __name__, url_prefix="/api/settings")

SENSITIVE_KEYS = {"smtp_password"}


def _masked_dict(row):
    """Serializes a setting row, masking its value if the key is sensitive."""
    data = row.to_dict()
    if row.setting_key in SENSITIVE_KEYS and data["setting_value"]:
        data["setting_value"] = "********"
    return data


@bp.get("")
@roles_required("ADMIN")
def list_settings():
    """Returns all system settings, with sensitive values masked."""
    rows = SystemSetting.query.order_by(SystemSetting.setting_key.asc()).all()
    return success_response([_masked_dict(r) for r in rows])


@bp.put("/<string:setting_key>")
@roles_required("ADMIN")
def update_setting(setting_key):
    """Creates or updates a single system setting and logs the change."""
    data = request.get_json(silent=True) or {}
    if "setting_value" not in data:
        return error_response("setting_value is required.", "VALIDATION_ERROR", 422)

    row = SystemSetting.query.filter_by(setting_key=setting_key).first()
    if not row:
        row = SystemSetting(setting_key=setting_key)
        db.session.add(row)

    old_value = row.setting_value
    row.setting_value = str(data["setting_value"])
    actor_id = int(get_jwt_identity())
    row.updated_by = actor_id
    db.session.commit()

    old_display = "********" if setting_key in SENSITIVE_KEYS and old_value else old_value
    new_display = "********" if setting_key in SENSITIVE_KEYS else row.setting_value
    log_activity(actor_id, "SETTINGS_CHANGED", "SystemSetting", row.id,
                 f"Changed {setting_key} from '{old_display}' to '{new_display}'.", request.remote_addr)
    return success_response(_masked_dict(row))


@bp.get("/alerting-status")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR", "APP_OWNER")
def alerting_status():
    """Whether incident alert email is currently switched on.

    Readable by everyone who can see incidents, not only administrators. A
    quiet inbox has two possible meanings - nothing is wrong, or nobody is
    being told - and the whole point of this platform is that those never look
    the same.
    """
    from app.services.notification_service import alerts_enabled, _in_quiet_days

    return success_response({
        "alerts_enabled": alerts_enabled(),
        "quiet_today": _in_quiet_days(),
    })
