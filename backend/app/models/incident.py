from datetime import datetime, timezone

from app.extensions import db


class Incident(db.Model):
    """Database model for a downtime incident detected for an application."""

    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    # Exactly one of these is set - an incident belongs to either an application or a server.
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), nullable=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=True)

    status = db.Column(db.String(20), nullable=False, default="OPEN")  # OPEN / RESOLVED

    started_at = db.Column(db.DateTime, nullable=False)
    detected_at = db.Column(db.DateTime, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)

    duration_seconds = db.Column(db.Integer, nullable=True)

    reason = db.Column(db.String(500), nullable=True)
    http_status_code = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.String(1000), nullable=True)

    notification_sent = db.Column(db.Boolean, nullable=False, default=False)
    recovery_notification_sent = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    notifications = db.relationship(
        "Notification", backref="incident", lazy="dynamic", cascade="all, delete-orphan"
    )

    def to_dict(self):
        """Serializes the incident into a JSON-friendly dict."""
        return {
            "id": self.id,
            "application_id": self.application_id,
            "server_id": self.server_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
            "http_status_code": self.http_status_code,
            "error_message": self.error_message,
            "notification_sent": self.notification_sent,
            "recovery_notification_sent": self.recovery_notification_sent,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
