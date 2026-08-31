import json
from datetime import datetime, timezone

from app.extensions import db


class ApplicationVersion(db.Model):
    """A snapshot of an application's monitoring profile before it was changed.

    FR-019 asks for versioned, approvable, roll-back-able configuration. §19
    adds that a configuration error must be recoverable by returning to the last
    good version.

    A snapshot per change rather than a diff: a diff is smaller and useless at
    the moment you need it, when the question is "what did this look like on
    Tuesday" and the answer has to be complete enough to restore.

    Written before the change lands, so version 1 is the profile as it was
    before the first edit rather than after it.
    """

    __tablename__ = "application_versions"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"),
                               nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    snapshot_json = db.Column(db.Text, nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    change_note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    @property
    def snapshot(self):
        return json.loads(self.snapshot_json) if self.snapshot_json else {}

    def to_dict(self):
        return {
            "id": self.id,
            "application_id": self.application_id,
            "version": self.version,
            "changed_by_id": self.changed_by_id,
            "change_note": self.change_note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "snapshot": self.snapshot,
        }
