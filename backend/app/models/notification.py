from datetime import datetime, timezone

from app.extensions import db


class Notification(db.Model):
    """Database model for a single email notification sent for an incident."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey("incidents.id"), nullable=False)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), nullable=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=True)

    notification_type = db.Column(db.String(20), nullable=False)  # DOWN / RECOVERY / REMINDER

    recipient = db.Column(db.String(255), nullable=False)
    cc = db.Column(db.String(255), nullable=True)

    subject = db.Column(db.String(500), nullable=False)
    # Kept so a notification held over a weekend (or retried after an SMTP
    # outage) is delivered with its real content, not a placeholder.
    body = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="PENDING")  # PENDING/SENT/FAILED

    sent_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.String(1000), nullable=True)
    retry_count = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        """Serializes the notification into a JSON-friendly dict."""
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "application_id": self.application_id,
            "server_id": self.server_id,
            "notification_type": self.notification_type,
            "recipient": self.recipient,
            "cc": self.cc,
            "subject": self.subject,
            "body": self.body,
            "status": self.status,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
