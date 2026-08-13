from datetime import datetime, timezone

from app.extensions import db


class HealthCheck(db.Model):
    """Database model for a single recorded health-check attempt on an application."""

    __tablename__ = "health_checks"

    # BigInteger on SQL Server (production); SQLite (tests) needs plain
    # INTEGER for rowid-based autoincrement to kick in.
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), nullable=False)
    checked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(20), nullable=False)  # UP / DOWN / DEGRADED
    http_status_code = db.Column(db.Integer, nullable=True)
    response_time = db.Column(db.Float, nullable=True)  # milliseconds
    success = db.Column(db.Boolean, nullable=False)
    error_message = db.Column(db.String(1000), nullable=True)
    attempt_number = db.Column(db.Integer, nullable=False, default=1)

    def to_dict(self):
        """Serializes the health check into a JSON-friendly dict."""
        return {
            "id": self.id,
            "application_id": self.application_id,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "status": self.status,
            "http_status_code": self.http_status_code,
            "response_time": self.response_time,
            "success": self.success,
            "error_message": self.error_message,
            "attempt_number": self.attempt_number,
        }
