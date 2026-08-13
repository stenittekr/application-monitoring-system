from datetime import datetime, timezone

from app.extensions import db


class SystemSetting(db.Model):
    """Database model for a single system-wide key/value configuration setting."""

    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), nullable=False, unique=True)
    setting_value = db.Column(db.String(1000), nullable=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def to_dict(self):
        """Serializes the setting into a JSON-friendly dict."""
        return {
            "id": self.id,
            "setting_key": self.setting_key,
            "setting_value": self.setting_value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by,
        }
