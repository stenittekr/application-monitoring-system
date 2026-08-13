from datetime import datetime, timezone

from app.extensions import db

STATUSES = ("UP", "DOWN", "DEGRADED", "UNKNOWN", "DISABLED")


class Application(db.Model):
    """Database model for a monitored application and its health-check configuration."""

    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(1000), nullable=True)
    url = db.Column(db.String(1000), nullable=True)  # required for HTTP/HTTPS checks, unused for TCP
    server = db.Column(db.String(255), nullable=True)  # required for TCP checks
    port = db.Column(db.Integer, nullable=True)  # required for TCP checks
    health_check_type = db.Column(db.String(10), nullable=False, default="HTTP")  # HTTP / HTTPS / TCP
    environment = db.Column(db.String(50), nullable=False, default="Production")
    owner_name = db.Column(db.String(150), nullable=False)
    owner_email = db.Column(db.String(255), nullable=False)
    manager_name = db.Column(db.String(150), nullable=False)
    manager_email = db.Column(db.String(255), nullable=False)

    monitoring_enabled = db.Column(db.Boolean, nullable=False, default=True)
    monitoring_interval = db.Column(db.Integer, nullable=False, default=300)
    timeout = db.Column(db.Integer, nullable=False, default=10)
    retry_count = db.Column(db.Integer, nullable=False, default=3)
    retry_delay = db.Column(db.Integer, nullable=False, default=5)
    expected_status_code = db.Column(db.Integer, nullable=False, default=200)
    verify_ssl = db.Column(db.Boolean, nullable=False, default=True)
    department = db.Column(db.String(100), nullable=True)
    icon = db.Column(db.String(50), nullable=True)  # bootstrap-icons class, e.g. "bi-people"

    current_status = db.Column(db.String(20), nullable=False, default="UNKNOWN")

    last_checked_at = db.Column(db.DateTime, nullable=True)
    last_successful_check_at = db.Column(db.DateTime, nullable=True)
    last_failed_check_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    health_checks = db.relationship(
        "HealthCheck", backref="application", lazy="dynamic", cascade="all, delete-orphan"
    )
    incidents = db.relationship(
        "Incident", backref="application", lazy="dynamic", cascade="all, delete-orphan"
    )

    def to_dict(self):
        """Serializes the application into a JSON-friendly dict."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "server": self.server,
            "port": self.port,
            "health_check_type": self.health_check_type,
            "environment": self.environment,
            "owner_name": self.owner_name,
            "owner_email": self.owner_email,
            "manager_name": self.manager_name,
            "manager_email": self.manager_email,
            "monitoring_enabled": self.monitoring_enabled,
            "monitoring_interval": self.monitoring_interval,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "retry_delay": self.retry_delay,
            "expected_status_code": self.expected_status_code,
            "verify_ssl": self.verify_ssl,
            "department": self.department,
            "icon": self.icon,
            "current_status": self.current_status,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "last_successful_check_at": self.last_successful_check_at.isoformat()
            if self.last_successful_check_at
            else None,
            "last_failed_check_at": self.last_failed_check_at.isoformat()
            if self.last_failed_check_at
            else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.deleted_at is None,
        }
