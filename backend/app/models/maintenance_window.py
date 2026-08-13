from datetime import datetime, timezone

from app.extensions import db


class MaintenanceWindow(db.Model):
    """A planned outage window. While active, health checks still run and
    record real results, but no incident is opened and no alert is sent -
    application_id NULL means the window applies to every application."""
    __tablename__ = "maintenance_windows"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), nullable=True)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(500), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    application = db.relationship("Application")

    def to_dict(self):
        """Serializes the maintenance window into a JSON-friendly dict."""
        return {
            "id": self.id,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else "All applications",
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
