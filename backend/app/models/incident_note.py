from datetime import datetime, timezone

from app.extensions import db


class IncidentNote(db.Model):
    """An investigation note against an incident.

    §21 requires authorised users to be able to comment on incidents, and §11
    step 7 expects an operator to record what they did. Kept as rows rather than
    a free-text column so each note carries its own author and timestamp - the
    audit value is in who said what, and when.

    Notes are append-only. An investigation record that can be quietly rewritten
    is not evidence.
    """

    __tablename__ = "incident_notes"

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey("incidents.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    note = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User")

    def to_dict(self):
        """Serializes the note, including the author's name for display."""
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
