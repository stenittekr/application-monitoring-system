from datetime import datetime, timezone

from app.extensions import db


class ServerMetric(db.Model):
    """One periodic capacity reading per server.

    Separate from health_checks, which record whether something answered. This
    records how full it is getting, which is a trend question: a single row
    means nothing and the shape of many is the whole point.

    Written hourly rather than per heartbeat. A minute-by-minute series answers
    no question a daily trend does not, and costs sixty times the rows.
    """

    __tablename__ = "server_metrics"

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    recorded_at = db.Column(db.DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc), index=True)
    disk_percent = db.Column(db.Float, nullable=True)
    disk_total_gb = db.Column(db.Float, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "server_id": self.server_id,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "disk_percent": self.disk_percent,
            "disk_total_gb": self.disk_total_gb,
        }
