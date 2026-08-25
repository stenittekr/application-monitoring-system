import json
from datetime import datetime, timezone

from app.extensions import db

STATUSES = ("UP", "DOWN", "DEGRADED", "UNKNOWN", "DISABLED")

# doc §7.3 application understanding lifecycle. New apps default to MONITORED
# since the existing "New Application" flow already turns on active checks
# immediately - DISCOVERED/INFORMATION_REQUIRED/PROFILE_DRAFT are for an admin
# to deliberately choose while a profile is still being filled in.
MATURITY_STATUSES = (
    "DISCOVERED", "INFORMATION_REQUIRED", "PROFILE_DRAFT", "MONITORED", "MAINTENANCE", "RETIRED",
)


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
    # Consecutive failed checks. retry_count covers retries within one check;
    # this counts whole checks, minutes apart, so a momentary blip cannot raise
    # an incident on its own.
    failure_streak = db.Column(db.Integer, nullable=False, default=0)

    # §7.3/§9 Application Health Profile: lifecycle status, what this app
    # depends on (stored as JSON, same pattern as Server.discovered_*_json),
    # and a free-text description of what "normal" looks like.
    maturity_status = db.Column(db.String(30), nullable=False, default="MONITORED")
    depends_on_json = db.Column(db.Text, nullable=True)
    # For DATABASE checks: what actually lives on the monitored instance.
    discovered_databases_json = db.Column(db.Text, nullable=True)
    # TLS certificate, for HTTPS checks. §12.1 asks for expiring certificates on
    # the overview; §19 asks to warn before a credential expires rather than
    # after. Refreshed daily, not per check - an extra handshake every 5 minutes
    # to read a date that moves once a year is waste.
    cert_expires_at = db.Column(db.DateTime, nullable=True)
    cert_issuer = db.Column(db.String(300), nullable=True)
    cert_checked_at = db.Column(db.DateTime, nullable=True)
    # Layer 5: a declarative synthetic business transaction. JSON steps, never
    # code - see workflow_service for the vocabulary and why it is limited.
    workflow_json = db.Column(db.Text, nullable=True)
    baseline_notes = db.Column(db.Text, nullable=True)

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

    @property
    def tracked_databases(self):
        """The databases on this instance that we actually care about.

        The instance hosts 80; only a handful belong to systems we run. The
        watchlist lives in system_settings so it changes without a deploy, and
        a name on the list that is NOT present on the server is reported as
        missing rather than quietly omitted - that absence is the interesting case.
        """
        if self.health_check_type != "DATABASE":
            return []
        from app.models.system_setting import SystemSetting

        row = SystemSetting.query.filter_by(setting_key="tracked_databases").first()
        wanted = [n.strip() for n in (row.setting_value if row else "").split(",") if n.strip()]
        if not wanted:
            return []
        found = {d["name"].lower(): d for d in self.discovered_databases}
        result = []
        for name in wanted:
            match = found.get(name.lower())
            result.append(match if match else {"name": name, "state": "NOT FOUND", "recovery_model": None})
        return result

    @property
    def workflow_steps(self):
        """The synthetic workflow steps, or [] if none is configured."""
        return json.loads(self.workflow_json) if self.workflow_json else []

    @property
    def cert_days_remaining(self):
        """Whole days until the TLS certificate expires, or None if unknown.

        Negative means already expired - reported rather than clamped, because
        "expired 3 days ago" and "expires today" call for different urgency."""
        if not self.cert_expires_at:
            return None
        expires = self.cert_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return (expires - datetime.now(timezone.utc)).days

    @property
    def discovered_databases(self):
        """Databases found on this instance at the last check (DATABASE type only)."""
        return json.loads(self.discovered_databases_json) if self.discovered_databases_json else []

    @property
    def depends_on(self):
        """Application IDs this application depends on (e.g. a shared database or API)."""
        return json.loads(self.depends_on_json) if self.depends_on_json else []

    @depends_on.setter
    def depends_on(self, application_ids):
        self.depends_on_json = json.dumps([int(i) for i in application_ids]) if application_ids else None

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
            "maturity_status": self.maturity_status,
            "depends_on": self.depends_on,
            "discovered_databases": self.discovered_databases,
            "cert_expires_at": self.cert_expires_at.isoformat() if self.cert_expires_at else None,
            "cert_issuer": self.cert_issuer,
            "workflow_steps": self.workflow_steps,
            "cert_days_remaining": self.cert_days_remaining,
            "tracked_databases": self.tracked_databases,
            "baseline_notes": self.baseline_notes,
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
