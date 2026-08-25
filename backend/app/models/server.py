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
    # Capacities behind the percentages, so "61% RAM" can be read as "61% of 16 GB".
    cpu_cores = db.Column(db.Integer, nullable=True)
    ram_total_mb = db.Column(db.Integer, nullable=True)
    disk_total_gb = db.Column(db.Float, nullable=True)
    # Consecutive heartbeats over / under threshold. A single spike is not a
    # condition worth waking anyone for.
    resource_breach_streak = db.Column(db.Integer, nullable=False, default=0)
    resource_clear_streak = db.Column(db.Integer, nullable=False, default=0)
    # Components that MUST be present. Discovery lists what is there; these say
    # what ought to be - the difference is the whole point of a component check.
    expected_services_json = db.Column(db.Text, nullable=True)
    expected_processes_json = db.Column(db.Text, nullable=True)
    component_breach_streak = db.Column(db.Integer, nullable=False, default=0)
    component_clear_streak = db.Column(db.Integer, nullable=False, default=0)
    # §7.2 identity. Refreshed on every heartbeat, not only at enrolment - a
    # machine that is upgraded, renamed or given a new address otherwise keeps
    # reporting whatever was true on the day it enrolled.
    os_edition = db.Column(db.String(100), nullable=True)
    os_architecture = db.Column(db.String(40), nullable=True)
    domain = db.Column(db.String(150), nullable=True)
    cpu_model = db.Column(db.String(200), nullable=True)
    ip_addresses_json = db.Column(db.Text, nullable=True)
    uptime_seconds = db.Column(db.Integer, nullable=True)

    last_heartbeat_at = db.Column(db.DateTime, nullable=True)
    last_boot_at = db.Column(db.DateTime, nullable=True)  # estimated from uptime_seconds each heartbeat

    # Latest discovery snapshot, stored as JSON text - these are candidates for
    # review, not automatically monitored (matches the "Discovered, not yet
    # approved" status the requirements doc calls for). A dedicated
    # approval/profile workflow is Phase 2, not built yet.
    discovered_services_json = db.Column(db.Text, nullable=True)
    discovered_ports_json = db.Column(db.Text, nullable=True)
    # Running processes, with the script name for interpreters - answers
    # "which of our Python jobs is actually running on that box".
    discovered_processes_json = db.Column(db.Text, nullable=True)
    # Installed-software inventory, as Programs and Features lists it.
    discovered_programs_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    # A heartbeat is "fresh" for this many intervals. Beyond it the metrics on
    # record describe the past, not now. check_missed_heartbeats only declares
    # DOWN after 3 missed intervals, so without this a server that stopped
    # reporting keeps showing its last CPU/RAM as though they were current -
    # which is precisely how an unreporting server looks healthy.
    STALE_AFTER_INTERVALS = 1.5

    @property
    def is_stale(self):
        """True when the newest heartbeat is too old for its metrics to be trusted."""
        if self.last_heartbeat_at is None:
            return True
        last = self.last_heartbeat_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        allowed = (self.heartbeat_interval_seconds or 60) * self.STALE_AFTER_INTERVALS
        return (datetime.now(timezone.utc) - last).total_seconds() > allowed

    @property
    def effective_status(self):
        """The status to display. STALE sits between "reporting" and the DOWN
        that check_missed_heartbeats raises later, so data gaps are visible
        immediately instead of masquerading as the last known good reading."""
        if self.current_status in ("DOWN", "UNKNOWN"):
            return self.current_status
        return "STALE" if self.is_stale else self.current_status

    @property
    def ip_addresses(self):
        """Every routable address this server reports, not just the first one."""
        return json.loads(self.ip_addresses_json) if self.ip_addresses_json else []

    @property
    def os_label(self):
        """One readable line for the OS, e.g. 'Windows 11 (build 10.0.26200) Professional'."""
        parts = [self.os_name, self.os_version]
        if self.os_edition and self.os_edition not in (self.os_version or ""):
            parts.append(self.os_edition)
        return " ".join(p for p in parts if p) or "Unknown"

    @property
    def expected_services(self):
        """Windows service names this server is expected to be running."""
        return json.loads(self.expected_services_json) if self.expected_services_json else []

    @property
    def expected_processes(self):
        """Process names this server is expected to be running."""
        return json.loads(self.expected_processes_json) if self.expected_processes_json else []

    @property
    def name(self):
        """Alias so incident/notification code can treat a Server like an Application."""
        return self.hostname

    @property
    def component_status(self):
        """Per-expected-component OK / STOPPED / MISSING, for the dashboard.

        Reported straight from the last heartbeat so the screen and the alerting
        cannot disagree. An expected component that discovery never mentions is
        MISSING (uninstalled, renamed); one it lists as not running is STOPPED.
        """
        if not (self.expected_services or self.expected_processes):
            return []
        services = {s["name"].lower(): s for s in json.loads(self.discovered_services_json or "[]")}
        processes = {p["name"].lower() for p in json.loads(self.discovered_processes_json or "[]") if p.get("name")}
        result = []
        for name in self.expected_services:
            found = services.get(name.lower())
            state = "MISSING" if not found else ("OK" if found["status"] == "running" else "STOPPED")
            result.append({"kind": "service", "name": name, "state": state})
        for name in self.expected_processes:
            result.append({"kind": "process", "name": name,
                           "state": "OK" if name.lower() in processes else "MISSING"})
        return result

    def _resource_flags(self):
        """Per-metric OK/WARNING/CRITICAL, from the same thresholds that alert."""
        from app.services.server_service import resource_flags
        return resource_flags(self)

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
            "current_status": self.effective_status,
            "reported_status": self.current_status,
            "is_stale": self.is_stale,
            "resource_flags": self._resource_flags(),
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "disk_percent": self.disk_percent,
            "cpu_cores": self.cpu_cores,
            "ram_total_mb": self.ram_total_mb,
            "disk_total_gb": self.disk_total_gb,
            "uptime_seconds": self.uptime_seconds,
            "last_heartbeat_at": self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
            "last_boot_at": self.last_boot_at.isoformat() if self.last_boot_at else None,
            "discovered_services": json.loads(self.discovered_services_json) if self.discovered_services_json else [],
            "discovered_ports": json.loads(self.discovered_ports_json) if self.discovered_ports_json else [],
            "discovered_processes": json.loads(self.discovered_processes_json) if self.discovered_processes_json else [],
            "discovered_programs": json.loads(self.discovered_programs_json) if self.discovered_programs_json else [],
            "os_edition": self.os_edition,
            "os_architecture": self.os_architecture,
            "os_label": self.os_label,
            "domain": self.domain,
            "cpu_model": self.cpu_model,
            "ip_addresses": self.ip_addresses,
            "expected_services": self.expected_services,
            "expected_processes": self.expected_processes,
            "component_status": self.component_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.deleted_at is None,
        }
