from datetime import datetime, timezone

from app.extensions import db


class ServerChange(db.Model):
    """One detected difference between two consecutive discovery snapshots.

    FR-006: discovery already collects services, processes and installed
    software on every heartbeat, and the new snapshot simply overwrote the old
    one. Diffing before the overwrite gives change detection with no extra
    collection - the previous snapshot is the row already in the database.
    """

    __tablename__ = "server_changes"

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)

    category = db.Column(db.String(20), nullable=False)     # SERVICE / PROGRAM / PORT
    change_type = db.Column(db.String(20), nullable=False)  # ADDED / REMOVED / CHANGED
    item_name = db.Column(db.String(300), nullable=False)

    old_value = db.Column(db.String(300), nullable=True)
    new_value = db.Column(db.String(300), nullable=True)

    detected_at = db.Column(db.DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        """Serializes the change for the API."""
        return {
            "id": self.id,
            "server_id": self.server_id,
            "category": self.category,
            "change_type": self.change_type,
            "item_name": self.item_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }
