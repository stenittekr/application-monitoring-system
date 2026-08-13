import json
from datetime import datetime, timezone

from app.extensions import db


class ActivityLog(db.Model):
    """Database model for an audit-trail entry recording a user or system action."""

    __tablename__ = "activity_logs"

    # BigInteger on SQL Server (production); SQLite (tests) needs plain
    # INTEGER for rowid-based autoincrement to kick in.
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    action = db.Column(db.String(100), nullable=False)

    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)

    description = db.Column(db.String(1000), nullable=True)

    ip_address = db.Column(db.String(50), nullable=True)
    metadata_json = db.Column("metadata", db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User")

    @property
    def metadata_dict(self):
        """Parses the stored metadata JSON string into a dict, defaulting to empty on failure."""
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except (TypeError, ValueError):
            return {}

    def to_dict(self):
        """Serializes the activity log entry into a JSON-friendly dict."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "description": self.description,
            "ip_address": self.ip_address,
            "metadata": self.metadata_dict,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
