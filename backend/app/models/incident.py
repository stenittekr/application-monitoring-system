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
    # REACHABILITY (down/unreachable) or RESOURCE (a threshold breach). A server
    # can be short of disk AND unreachable; without this the two would share one
    # incident row and each would silently close the other.
    kind = db.Column(db.String(20), nullable=False, default="REACHABILITY")

    started_at = db.Column(db.DateTime, nullable=False)
    detected_at = db.Column(db.DateTime, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)

    duration_seconds = db.Column(db.Integer, nullable=True)

    reason = db.Column(db.String(500), nullable=True)
    http_status_code = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.String(1000), nullable=True)

    notification_sent = db.Column(db.Boolean, nullable=False, default=False)
    recovery_notification_sent = db.Column(db.Boolean, nullable=False, default=False)

    acknowledged_at = db.Column(db.DateTime, nullable=True)
    acknowledged_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    escalated_at = db.Column(db.DateTime, nullable=True)
    # §11 step 9: an incident closes with a cause and a person, not just a
    # timestamp. resolved_by is null when the platform closed it automatically,
    # which is itself worth being able to tell apart.
    resolved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    resolution_category = db.Column(db.String(50), nullable=True)
    resolution_note = db.Column(db.String(1000), nullable=True)
    reopened_count = db.Column(db.Integer, nullable=False, default=0)  # set once, so escalation only fires once per incident

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    notifications = db.relationship(
        "Notification", backref="incident", lazy="dynamic", cascade="all, delete-orphan"
    )
    acknowledged_by = db.relationship("User", foreign_keys=[acknowledged_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])

    def to_dict(self):
        """Serializes the incident into a JSON-friendly dict."""
        return {
            "id": self.id,
            "application_id": self.application_id,
            "server_id": self.server_id,
            "status": self.status,
            "kind": self.kind,
            "resolved_by_id": self.resolved_by_id,
            "resolution_category": self.resolution_category,
            "resolution_note": self.resolution_note,
            "reopened_count": self.reopened_count,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
            "http_status_code": self.http_status_code,
            "error_message": self.error_message,
            "notification_sent": self.notification_sent,
            "recovery_notification_sent": self.recovery_notification_sent,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by": {"id": self.acknowledged_by.id, "name": self.acknowledged_by.name}
                if self.acknowledged_by else None,
            "assigned_to": {"id": self.assigned_to.id, "name": self.assigned_to.name}
                if self.assigned_to else None,
            "escalated_at": self.escalated_at.isoformat() if self.escalated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
