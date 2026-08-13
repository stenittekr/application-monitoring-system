import json
from datetime import datetime, timezone

from app.extensions import db

STATUSES = ("UP", "DOWN", "UNKNOWN")


class Server(db.Model):
    """Database model for an enrolled agent/server being monitored."""
    __tablename__ = "servers"

    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(255), nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    os_name = db.Column(db.String(100), nullable=True)
    os_version = db.Column(db.String(255), nullable=True)
    agent_version = db.Column(db.String(50), nullable=True)

    token_hash = db.Column(db.String(64), nullable=False)  # sha256 hex digest of the agent's secret

    owner_name = db.Column(db.String(150), nullable=True)
    owner_email = db.Column(db.String(255), nullable=True)

    heartbeat_interval_seconds = db.Column(db.Integer, nullable=False, default=60)
    current_status = db.Column(db.String(20), nullable=False, default="UNKNOWN")

    cpu_percent = db.Column(db.Float, nullable=True)
    ram_percent = db.Column(db.Float, nullable=True)
    disk_percent = db.Column(db.Float, nullable=True)
    uptime_seconds = db.Column(db.Integer, nullable=True)

    last_heartbeat_at = db.Column(db.DateTime, nullable=True)
    last_boot_at = db.Column(db.DateTime, nullable=True)  # estimated from uptime_seconds each heartbeat

    # Latest discovery snapshot, stored as JSON text - these are candidates for
    # review, not automatically monitored (matches the "Discovered, not yet
    # approved" status the requirements doc calls for). A dedicated
    # approval/profile workflow is Phase 2, not built yet.
    discovered_services_json = db.Column(db.Text, nullable=True)
    discovered_ports_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    @property
    def name(self):
        """Alias so incident/notification code can treat a Server like an Application."""
        return self.hostname

    def to_dict(self):
        """Serializes the server into a JSON-friendly dict (never includes the token)."""
        return {
            "id": self.id,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "agent_version": self.agent_version,
            "owner_name": self.owner_name,
            "owner_email": self.owner_email,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "current_status": self.current_status,
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "disk_percent": self.disk_percent,
            "uptime_seconds": self.uptime_seconds,
            "last_heartbeat_at": self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
            "last_boot_at": self.last_boot_at.isoformat() if self.last_boot_at else None,
            "discovered_services": json.loads(self.discovered_services_json) if self.discovered_services_json else [],
            "discovered_ports": json.loads(self.discovered_ports_json) if self.discovered_ports_json else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.deleted_at is None,
        }
