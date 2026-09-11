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
    # Who hears about this particular machine.
    #
    #   ALL    owner plus the standing distribution list
    #   OWNER  its owner only - monitoring infrastructure, not a business system
    #   NONE   nobody, while it is expected to misbehave
    #
    # The laptop running the platform raised 19 of 27 incidents in one week: CPU
    # spikes on wake, missed heartbeats when it went home. All real, none of it
    # a manager's problem, and some of it not worth an email at all.
    alert_scope = db.Column(db.String(10), nullable=False, default="ALL")
    site = db.Column(db.String(100), nullable=True)          # FR-023 grouping
    tags_json = db.Column(db.Text, nullable=True)

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

    # RESTART or UPDATE, queued from the dashboard and carried in the next
    # heartbeat's reply, then cleared - a fleet-wide fix should never require
    # a command run on 200+ machines by hand.
    pending_agent_command = db.Column(db.String(20), nullable=True)
    # e.g. {"service_name": "Spooler"} for RESTART_SERVICE - kept separate
    # from the action itself so a plain command (RESTART) needs none.
    pending_agent_command_params_json = db.Column(db.Text, nullable=True)
    last_screenshot_at = db.Column(db.DateTime, nullable=True)

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
    network_interfaces_json = db.Column(db.Text, nullable=True)
    cpu_per_core_json = db.Column(db.Text, nullable=True)
    hardware_json = db.Column(db.Text, nullable=True)
    disk_volumes_json = db.Column(db.Text, nullable=True)
    scheduled_tasks_json = db.Column(db.Text, nullable=True)
    containers_json = db.Column(db.Text, nullable=True)
    disk_usage_json = db.Column(db.Text, nullable=True)

    # Which local process is connected to which database server, as observed by
    # the agent's own socket table. A config file states intent; this states
    # fact, and the two disagree often enough to matter.
    database_links_json = db.Column(db.Text, nullable=True)

    # Throughput per physical disk, and IIS sites/pools where IIS is installed.
    disk_io_json = db.Column(db.Text, nullable=True)
    web_sites_json = db.Column(db.Text, nullable=True)
    device_inventory_json = db.Column(db.Text, nullable=True)
    reachability_json = db.Column(db.Text, nullable=True)
    # Set the moment a restart is detected, cleared once the checks that
    # follow one have run. §10 asks for a rapid priority check after a
    # reboot and then the full cycle - a server that has just come back is
    # the least trustworthy it ever is, and waiting five minutes to find
    # out what did not come back with it is the wrong answer.
    restart_pending_checks_at = db.Column(db.DateTime, nullable=True)
    agent_health_json = db.Column(db.Text, nullable=True)
    # Positive means the agent's clock is ahead of ours. Kept as a number
    # rather than a flag: "42 seconds" is a shrug, "3 hours" explains why an
    # incident timeline reads backwards.
    clock_skew_seconds = db.Column(db.Integer, nullable=True)

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
        # AGENT_DOWN already says "no fresh data" and says why, so STALE
        # would only blur it.
        if self.current_status in ("DOWN", "UNKNOWN", "AGENT_DOWN"):
            return self.current_status
        return "STALE" if self.is_stale else self.current_status

    # How far out an agent's clock may be before its timestamps stop being
    # usable for ordering. Generous: a couple of minutes of drift is normal on
    # a machine that has not synchronised recently and misleads nobody.
    CLOCK_SKEW_TOLERANCE_SECONDS = 120

    @property
    def clock_is_trustworthy(self):
        """False when this agent's timestamps should not be used for ordering."""
        if self.clock_skew_seconds is None:
            return True          # never reported; nothing to distrust yet
        return abs(self.clock_skew_seconds) <= self.CLOCK_SKEW_TOLERANCE_SECONDS

    ALERT_SCOPES = ("ALL", "OWNER", "NONE")

    @property
    def alerts_muted(self):
        """True when nothing about this server should be emailed at all."""
        return (self.alert_scope or "ALL") == "NONE"

    @property
    def owner_only_alerts(self):
        """Whether the standing distribution list is skipped for this server."""
        return (self.alert_scope or "ALL") == "OWNER"

    # A queue this deep means heartbeats are being kept rather than delivered.
    # Two is a blip between cycles; twenty is a pattern.
    AGENT_QUEUE_WARNING = 10

    @property
    def agent_health(self):
        """What the agent reports about itself (§7.1), or {} from older agents."""
        return json.loads(self.agent_health_json) if self.agent_health_json else {}

    @property
    def agent_health_status(self):
        """OK, WARNING, or UNAVAILABLE when the agent is too old to say.

        Deliberately not CRITICAL: a struggling agent is a reason to look at the
        agent, never a reason to declare the server down. Confusing those is how
        a monitoring fault becomes a false outage.
        """
        health = self.agent_health
        if not health:
            return "UNAVAILABLE"
        if health.get("queued_heartbeats", 0) >= self.AGENT_QUEUE_WARNING:
            return "WARNING"
        return "OK"

    @property
    def disk_usage(self):
        """The largest folders on each volume, as the agent last measured them.

        Refreshed every six hours rather than every heartbeat: walking a 200 GB
        volume takes minutes, and disk usage does not change meaningfully in an
        hour. If it does, that is what the growth rate is for.
        """
        return json.loads(self.disk_usage_json) if self.disk_usage_json else []

    @property
    def database_links(self):
        """Which process here is connected to which database server."""
        return json.loads(self.database_links_json) if self.database_links_json else []

    @property
    def disk_io(self):
        """Cumulative read/write counters per physical disk."""
        return json.loads(self.disk_io_json) if self.disk_io_json else []

    @property
    def reachability(self):
        """DNS, gateway and platform reachability from this machine."""
        return json.loads(self.reachability_json) if self.reachability_json else {}

    @property
    def device_inventory(self):
        """Asset identity - what this machine is, not how it is doing."""
        return json.loads(self.device_inventory_json) if self.device_inventory_json else {}

    @property
    def web_sites(self):
        """IIS sites and application pools, or [] where IIS is not installed."""
        return json.loads(self.web_sites_json) if self.web_sites_json else []

    @property
    def fullest_volume(self):
        """The volume closest to full, or None when only the system drive is known.

        disk_percent has always meant C:. PS_QAS turned out to have an E: with
        129 GB free while C: sat at 88% - and had it been the other way round,
        nothing would have said so. A server is as full as its fullest disk,
        because that is the one that stops an application.
        """
        volumes = self.disk_volumes
        return max(volumes, key=lambda v: v.get("used_percent") or 0) if volumes else None

    @property
    def worst_disk_percent(self):
        """The highest used-percentage across every volume this server reports."""
        worst = self.fullest_volume
        if worst is None:
            return self.disk_percent          # older agent: system drive only
        return max(worst.get("used_percent") or 0, self.disk_percent or 0)

    @property
    def hardware(self):
        """Temperature, fan and battery, where the machine exposes them.

        An empty dict means the OS reports none of it, which §8 requires be
        shown as "Not available" rather than as a healthy zero.
        """
        return json.loads(self.hardware_json) if self.hardware_json else {}

    @property
    def disk_volumes(self):
        return json.loads(self.disk_volumes_json) if self.disk_volumes_json else []

    @property
    def network_interfaces(self):
        return json.loads(self.network_interfaces_json) if self.network_interfaces_json else []

    @property
    def scheduled_tasks(self):
        return json.loads(self.scheduled_tasks_json) if self.scheduled_tasks_json else []

    @property
    def containers(self):
        return json.loads(self.containers_json) if self.containers_json else []

    @property
    def cpu_per_core(self):
        return json.loads(self.cpu_per_core_json) if self.cpu_per_core_json else []

    @property
    def tags(self):
        return json.loads(self.tags_json) if self.tags_json else []

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
            "alert_scope": self.alert_scope or "ALL",
            # Kept so anything reading the old field still works.
            "owner_only_alerts": (self.alert_scope == "OWNER"),
            "site": self.site,
            "tags": self.tags,
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
            "pending_agent_command": self.pending_agent_command,
            "last_screenshot_at": self.last_screenshot_at.isoformat() if self.last_screenshot_at else None,
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
            "network_interfaces": self.network_interfaces,
            "cpu_per_core": self.cpu_per_core,
            "hardware": self.hardware,
            "disk_volumes": self.disk_volumes,
            "disk_usage": self.disk_usage,
            "database_links": self.database_links,
            "disk_io": self.disk_io,
            "web_sites": self.web_sites,
            "device_inventory": self.device_inventory,
            "reachability": self.reachability,
            "worst_disk_percent": self.worst_disk_percent,
            "fullest_volume": self.fullest_volume,
            "scheduled_tasks": self.scheduled_tasks,
            "containers": self.containers,
            "clock_skew_seconds": self.clock_skew_seconds,
            "restart_pending_checks": self.restart_pending_checks_at is not None,
            "agent_health": self.agent_health,
            "agent_health_status": self.agent_health_status,
            "clock_is_trustworthy": self.clock_is_trustworthy,
            "expected_services": self.expected_services,
            "expected_processes": self.expected_processes,
            "component_status": self.component_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.deleted_at is None,
        }
