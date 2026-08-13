"""Agent enrollment, heartbeat processing, and missed-heartbeat detection.

Mirrors monitoring_service.py's application pattern: the central platform
decides a server is DOWN by noticing missed heartbeats itself, rather than
trusting the (possibly dead) server to report its own outage.
"""
import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.server import Server
from app.services import incident_service, notification_service
from app.services.audit_service import log_activity

logger = logging.getLogger(__name__)

# How many missed intervals before we declare a server DOWN - one blip
# (a slow network tick) shouldn't raise a false alarm.
MISSED_INTERVALS_BEFORE_DOWN = 3

# Estimated boot time (now - uptime) drifts a little every heartbeat from
# clock skew and measurement jitter alone - only flag it as an actual
# restart once the drift is bigger than that could plausibly explain.
RESTART_DETECTION_TOLERANCE_SECONDS = 120


def _detect_restart(server, uptime_seconds, now):
    """Compares this heartbeat's estimated boot time against the last one
    recorded; a jump bigger than clock-jitter tolerance means the server
    actually rebooted since the previous heartbeat."""
    if uptime_seconds is None:
        return
    estimated_boot_at = now - timedelta(seconds=uptime_seconds)
    if server.last_boot_at is not None:
        drift = abs((estimated_boot_at - server.last_boot_at).total_seconds())
        if drift > RESTART_DETECTION_TOLERANCE_SECONDS:
            log_activity(
                None, "SERVER_RESTART_DETECTED", "Server", server.id,
                f"{server.hostname} restarted (uptime reset to {uptime_seconds}s).",
            )
    server.last_boot_at = estimated_boot_at


def _hash_token(token):
    """One-way hash for storing/comparing an agent's secret (fast by design -
    this is checked on every heartbeat, unlike a human password checked once)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def enroll(data):
    """Registers a new server and issues it a one-time secret token."""
    token = secrets.token_hex(32)
    server = Server(
        hostname=data["hostname"].strip(),
        ip_address=(data.get("ip_address") or "").strip() or None,
        os_name=(data.get("os_name") or "").strip() or None,
        os_version=(data.get("os_version") or "").strip() or None,
        agent_version=(data.get("agent_version") or "").strip() or None,
        owner_name=(data.get("owner_name") or "").strip() or None,
        owner_email=(data.get("owner_email") or "").strip() or None,
        heartbeat_interval_seconds=int(data.get("heartbeat_interval_seconds") or 60),
        token_hash=_hash_token(token),
        current_status="UNKNOWN",
    )
    db.session.add(server)
    db.session.commit()
    return server, token


def verify_token(server, token):
    """Checks a submitted token against the stored hash."""
    return bool(token) and _hash_token(token) == server.token_hash


def get_server(server_id):
    """Looks up a single non-deleted server by id."""
    return Server.query.filter_by(id=server_id, deleted_at=None).first()


def list_servers():
    """Returns all non-deleted servers."""
    return Server.query.filter(Server.deleted_at.is_(None)).order_by(Server.hostname.asc()).all()


def record_heartbeat(server, data):
    """Updates a server's live metrics and resolves any open incident, since a
    heartbeat arriving at all means the server is reachable right now."""
    was_down = server.current_status == "DOWN"
    _detect_restart(server, data.get("uptime_seconds"), datetime.now(timezone.utc))
    server.cpu_percent = data.get("cpu_percent")
    server.ram_percent = data.get("ram_percent")
    server.disk_percent = data.get("disk_percent")
    server.uptime_seconds = data.get("uptime_seconds")
    if data.get("agent_version"):
        server.agent_version = data["agent_version"]
    if data.get("discovered_services") is not None:
        server.discovered_services_json = json.dumps(data["discovered_services"])
    if data.get("discovered_ports") is not None:
        server.discovered_ports_json = json.dumps(data["discovered_ports"])
    server.last_heartbeat_at = datetime.now(timezone.utc)
    server.current_status = "UP"
    db.session.commit()

    if was_down:
        incident = incident_service.get_active_incident(server_id=server.id)
        if incident:
            incident_service.resolve_incident(incident, server.last_heartbeat_at)
            notification_service.send_server_recovery_notification(incident, server)
            logger.info("Server %s reachable again, incident #%s resolved", server.hostname, incident.id)
    return server


def check_missed_heartbeats():
    """Scans all servers for missed heartbeats and opens/keeps an incident open
    for any that have gone quiet too long. Called every monitoring cycle,
    alongside the existing application health checks."""
    now = datetime.now(timezone.utc)
    for server in list_servers():
        if server.last_heartbeat_at is None:
            continue  # never checked in yet - nothing to compare against
        last = server.last_heartbeat_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        grace = timedelta(seconds=server.heartbeat_interval_seconds * MISSED_INTERVALS_BEFORE_DOWN)
        if now - last <= grace:
            continue  # still within tolerance

        if server.current_status != "DOWN":
            server.current_status = "DOWN"
            db.session.commit()
            incident, created = incident_service.open_incident(
                server, detected_at=now,
                reason="Missed heartbeat", error_message=f"No heartbeat since {last.isoformat()}",
                is_server=True,
            )
            if created:
                logger.warning("Server %s missed its heartbeat - incident #%s opened", server.hostname, incident.id)
            notification_service.send_server_down_notification(
                incident, server, f"No heartbeat since {last.isoformat()}"
            )
