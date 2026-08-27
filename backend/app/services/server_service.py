"""Agent enrollment, heartbeat processing, and missed-heartbeat detection.

Mirrors monitoring_service.py's application pattern: the central platform
decides a server is DOWN by noticing missed heartbeats itself, rather than
trusting the (possibly dead) server to report its own outage.
"""
import hashlib
import json
import logging
import secrets
import socket
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
        # SQLite round-trips DateTime columns as naive - normalize before
        # comparing against the timezone-aware estimate, same as
        # check_missed_heartbeats() does below.
        last_boot = server.last_boot_at
        if last_boot.tzinfo is None:
            last_boot = last_boot.replace(tzinfo=timezone.utc)
        drift = abs((estimated_boot_at - last_boot).total_seconds())
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
    """Registers a server and issues it a secret token.

    Re-enrolling a hostname that is already enrolled reuses that row and
    rotates its token rather than inserting a second one. Agents do get
    reinstalled, and a duplicate row sits on the dashboard as a permanently
    UNKNOWN phantom while the real row keeps reporting - which makes "is the
    agent running?" impossible to answer at a glance.

    Only live rows match: a server that was deliberately deleted stays deleted
    and enrolls fresh.
    """
    hostname = data["hostname"].strip()
    token = secrets.token_hex(32)

    server = Server.query.filter(
        db.func.lower(Server.hostname) == hostname.lower(), Server.deleted_at.is_(None)
    ).first()
    if server is None:
        server = Server(hostname=hostname, current_status="UNKNOWN",
                        heartbeat_interval_seconds=int(data.get("heartbeat_interval_seconds") or 60))
        db.session.add(server)

    # Only overwrite what the caller actually sent. A self-enrolling agent posts
    # no owner fields, and blanking owner_email on a re-enroll would silently
    # stop that server's DOWN emails (notification_service skips empty owners).
    server.hostname = hostname
    for field in ("ip_address", "os_name", "os_version", "agent_version", "owner_name", "owner_email"):
        value = (data.get(field) or "").strip()
        if value:
            setattr(server, field, value)
    if data.get("heartbeat_interval_seconds"):
        server.heartbeat_interval_seconds = int(data["heartbeat_interval_seconds"])

    # current_status is left alone on re-enrol: the next heartbeat drives it
    # through record_heartbeat, which also resolves any incident still open.
    server.token_hash = _hash_token(token)
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


def _record_clock_skew(server, agent_time):
    """Compares the agent's own clock with ours (§19 "clock incorrect").

    Every timestamp the platform stores is its own, precisely so that a wrong
    clock on a monitored machine cannot reorder an incident timeline. But a
    badly wrong clock is worth knowing about in its own right: it breaks the
    agent's log correlation, its certificate validation, and often its Kerberos
    tickets, none of which this platform would otherwise notice.
    """
    if not agent_time:
        server.clock_skew_seconds = None
        return
    try:
        reported = datetime.fromisoformat(str(agent_time))
    except (TypeError, ValueError):
        server.clock_skew_seconds = None
        return
    if reported.tzinfo is None:
        reported = reported.replace(tzinfo=timezone.utc)

    skew = int((reported - datetime.now(timezone.utc)).total_seconds())
    was_trustworthy = server.clock_is_trustworthy
    server.clock_skew_seconds = skew
    if was_trustworthy and not server.clock_is_trustworthy:
        logger.warning("Server %s clock is %d seconds out - its own logs and any "
                       "certificate checks it makes will be affected.", server.hostname, skew)


def record_heartbeat(server, data):
    """Updates a server's live metrics and resolves any open incident, since a
    heartbeat arriving at all means the server is reachable right now."""
    was_down = server.current_status == "DOWN"
    # Before the new snapshot lands on top of the old one.
    detect_inventory_changes(server, data)
    _detect_restart(server, data.get("uptime_seconds"), datetime.now(timezone.utc))
    server.cpu_percent = data.get("cpu_percent")
    server.ram_percent = data.get("ram_percent")
    server.disk_percent = data.get("disk_percent")
    server.uptime_seconds = data.get("uptime_seconds")
    # Only overwrite when reported: an older agent omits these, and blanking
    # them would make the dashboard forget capacities it already knew.
    for field in ("cpu_cores", "ram_total_mb", "disk_total_gb"):
        if data.get(field) is not None:
            setattr(server, field, data[field])
    if data.get("agent_version"):
        server.agent_version = data["agent_version"]
    # Identity now arrives with every heartbeat, so an OS upgrade, a rename or a
    # new DHCP lease is reflected instead of frozen at enrolment time. Only
    # overwrite what was actually sent - an older agent omits these entirely.
    for field in ("hostname", "os_name", "os_version", "os_edition",
                  "os_architecture", "domain", "cpu_model"):
        value = (data.get(field) or "").strip() if isinstance(data.get(field), str) else data.get(field)
        if value:
            setattr(server, field, value)
    if data.get("ip_addresses"):
        server.ip_addresses_json = json.dumps(data["ip_addresses"])
        # Keep the single ip_address column meaningful: the first routable IPv4.
        primary = next((a["address"] for a in data["ip_addresses"] if a.get("family") == "IPv4"), None)
        if primary:
            server.ip_address = primary
    if data.get("discovered_services") is not None:
        server.discovered_services_json = json.dumps(data["discovered_services"])
    if data.get("discovered_ports") is not None:
        server.discovered_ports_json = json.dumps(data["discovered_ports"])
    if data.get("discovered_processes") is not None:
        server.discovered_processes_json = json.dumps(data["discovered_processes"])
    if data.get("discovered_programs") is not None:
        server.discovered_programs_json = json.dumps(data["discovered_programs"])
    for field, column in (("network_interfaces", "network_interfaces_json"),
                          ("cpu_per_core", "cpu_per_core_json"),
                          ("hardware", "hardware_json"),
                          ("disk_volumes", "disk_volumes_json"),
                          ("scheduled_tasks", "scheduled_tasks_json"),
                          ("containers", "containers_json")):
        if data.get(field) is not None:
            setattr(server, column, json.dumps(data[field]))
    _record_clock_skew(server, data.get("agent_time"))
    server.last_heartbeat_at = datetime.now(timezone.utc)
    server.current_status = "UP"
    db.session.commit()

    evaluate_resource_thresholds(server)
    evaluate_component_checks(server)

    if was_down:
        incident = incident_service.get_active_incident(server_id=server.id)
        if incident:
            incident_service.resolve_incident(incident, server.last_heartbeat_at)
            notification_service.send_server_recovery_notification(incident, server)
            logger.info("Server %s reachable again, incident #%s resolved", server.hostname, incident.id)
    return server


# Defaults; override per-site in system_settings without touching code.
RESOURCE_THRESHOLD_DEFAULTS = {
    "cpu": ("cpu_warning_percent", "cpu_critical_percent", "85", "95"),
    "ram": ("ram_warning_percent", "ram_critical_percent", "85", "95"),
    "disk": ("disk_warning_percent", "disk_critical_percent", "85", "95"),
}


def _threshold(key, default):
    """Reads a numeric threshold from system_settings, falling back to the default."""
    from app.models.system_setting import SystemSetting

    row = SystemSetting.query.filter_by(setting_key=key).first()
    try:
        return float(row.setting_value) if row and row.setting_value else float(default)
    except (TypeError, ValueError):
        return float(default)


# A single sample is not a condition. CPU spikes to 100% when a machine wakes,
# and alerting on that produced ten incidents in ninety minutes, several opening
# and closing within the same second. Requirements 13/FR-012 ask for exactly
# this: consecutive failures to open, consecutive successes to close.
RESOURCE_BREACHES_TO_OPEN = 3
RESOURCE_CLEARS_TO_CLOSE = 3


def resource_flags(server):
    """Returns {"cpu": "OK"|"WARNING"|"CRITICAL"|"UNAVAILABLE", ...} for display.

    Same thresholds the alerting uses, so the dashboard can never disagree with
    the emails. ponytail: re-reads settings per server (6 small queries); fold
    into one cached read if the server count ever makes that matter."""
    flags = {}
    for metric, (warn_key, crit_key, warn_default, crit_default) in RESOURCE_THRESHOLD_DEFAULTS.items():
        value = getattr(server, f"{metric}_percent")
        if value is None:
            flags[metric] = "UNAVAILABLE"
        elif value >= _threshold(crit_key, crit_default):
            flags[metric] = "CRITICAL"
        elif value >= _threshold(warn_key, warn_default):
            flags[metric] = "WARNING"
        else:
            flags[metric] = "OK"
    return flags


def evaluate_resource_thresholds(server):
    """Opens or resolves a RESOURCE incident for CPU/RAM/disk pressure.

    Deliberately separate from the reachability incident: a server can be short
    of disk while perfectly reachable, and the two must not close each other.
    A metric the agent could not collect is skipped entirely - "not available"
    is not the same as "fine", and must never read as either healthy or 0%."""
    breaches = []
    for metric, (warn_key, crit_key, warn_default, crit_default) in RESOURCE_THRESHOLD_DEFAULTS.items():
        value = getattr(server, f"{metric}_percent")
        if value is None:
            continue  # not collected - report nothing rather than a false pass
        critical, warning = _threshold(crit_key, crit_default), _threshold(warn_key, warn_default)
        if value >= critical:
            breaches.append((f"{metric.upper()} {value:.0f}% >= critical {critical:.0f}%", True))
        elif value >= warning:
            breaches.append((f"{metric.upper()} {value:.0f}% >= warning {warning:.0f}%", False))

    existing = incident_service.get_active_incident(server_id=server.id, kind="RESOURCE")
    now = datetime.now(timezone.utc)

    if not breaches:
        server.resource_breach_streak = 0
        server.resource_clear_streak = (server.resource_clear_streak or 0) + 1
        db.session.commit()
        if existing and server.resource_clear_streak >= RESOURCE_CLEARS_TO_CLOSE:
            incident_service.resolve_incident(existing, now)
            notification_service.send_server_recovery_notification(existing, server)
            logger.info("Server %s resource pressure cleared, incident #%s resolved", server.hostname, existing.id)
        return None

    server.resource_clear_streak = 0
    server.resource_breach_streak = (server.resource_breach_streak or 0) + 1
    db.session.commit()

    if existing:
        return existing  # already alerted; do not re-notify every heartbeat

    if server.resource_breach_streak < RESOURCE_BREACHES_TO_OPEN:
        # Real pressure persists; a spike does not. Wait for it to prove itself.
        return None

    summary = "; ".join(text for text, _ in breaches)
    critical = any(is_critical for _, is_critical in breaches)
    incident, created = incident_service.open_incident(
        server, detected_at=now, reason=f"Resource threshold: {summary}",
        error_message=summary, is_server=True, kind="RESOURCE",
    )
    if created:
        logger.warning("Server %s resource incident #%s: %s", server.hostname, incident.id, summary)
        # Only critical breaches page anyone. A warning is visible on the
        # dashboard; emailing every one of those is how alert fatigue starts.
        if critical:
            notification_service.send_server_down_notification(incident, server, summary)
    return incident


COMPONENT_BREACHES_TO_OPEN = 2
COMPONENT_CLEARS_TO_CLOSE = 2


# Discovery is noisy by nature; a first heartbeat would otherwise report every
# service on the machine as "ADDED". Capped so one odd cycle cannot write
# thousands of rows.
MAX_CHANGES_PER_CATEGORY = 40


def _diff_snapshot(old_items, new_items, key, value_of):
    """Returns (added, removed, changed) between two discovery snapshots."""
    old_map = {str(i.get(key)).lower(): i for i in old_items if i.get(key)}
    new_map = {str(i.get(key)).lower(): i for i in new_items if i.get(key)}
    added = [new_map[k] for k in new_map.keys() - old_map.keys()]
    removed = [old_map[k] for k in old_map.keys() - new_map.keys()]
    changed = [(old_map[k], new_map[k]) for k in old_map.keys() & new_map.keys()
               if value_of(old_map[k]) != value_of(new_map[k])]
    return added, removed, changed


def _record_changes(server, category, old_items, new_items, key, value_of):
    """Writes ServerChange rows for one category. Silent on the first snapshot."""
    from app.models.server_change import ServerChange

    if not old_items:
        return 0  # nothing to compare against; not a change, just a beginning
    added, removed, changed = _diff_snapshot(old_items, new_items, key, value_of)
    rows = []
    for item in added[:MAX_CHANGES_PER_CATEGORY]:
        rows.append(ServerChange(server_id=server.id, category=category, change_type="ADDED",
                                 item_name=str(item.get(key))[:300], new_value=value_of(item)))
    for item in removed[:MAX_CHANGES_PER_CATEGORY]:
        rows.append(ServerChange(server_id=server.id, category=category, change_type="REMOVED",
                                 item_name=str(item.get(key))[:300], old_value=value_of(item)))
    for old, new in changed[:MAX_CHANGES_PER_CATEGORY]:
        rows.append(ServerChange(server_id=server.id, category=category, change_type="CHANGED",
                                 item_name=str(new.get(key))[:300],
                                 old_value=value_of(old), new_value=value_of(new)))
    for row in rows:
        db.session.add(row)
    return len(rows)


def detect_inventory_changes(server, data):
    """Compares the incoming discovery snapshot against the stored one.

    Must run BEFORE the new snapshot overwrites the old, which is why it is
    called at the top of record_heartbeat rather than the bottom.
    """
    total = 0
    if data.get("discovered_services") is not None:
        total += _record_changes(
            server, "SERVICE", json.loads(server.discovered_services_json or "[]"),
            data["discovered_services"], "name", lambda i: (i.get("status") or "")[:300])
    if data.get("discovered_programs") is not None:
        total += _record_changes(
            server, "PROGRAM", json.loads(server.discovered_programs_json or "[]"),
            data["discovered_programs"], "name", lambda i: (i.get("version") or "")[:300])
    if total:
        db.session.commit()
        logger.info("Server %s: %d inventory change(s) detected", server.hostname, total)
    return total


def set_expected_components(server, services, processes):
    """Records what must be running, then re-evaluates immediately so the change
    is reflected without waiting for the next heartbeat."""
    server.expected_services_json = json.dumps([str(s).strip() for s in services if str(s).strip()])
    server.expected_processes_json = json.dumps([str(p).strip() for p in processes if str(p).strip()])
    server.component_breach_streak = 0
    server.component_clear_streak = 0
    db.session.commit()
    return server


def evaluate_component_checks(server):
    """Opens or resolves a COMPONENT incident for an expected service or process
    that is stopped or missing.

    This is the layer the requirements open with: a running server proves
    nothing about whether the software on it is up. Discovery already reports
    what is present; this compares that against what ought to be present.

    Kept apart from REACHABILITY and RESOURCE incidents because all three can be
    true at once - a server can be reachable, short of disk, and missing a
    service, and each needs its own lifecycle.
    """
    problems = [c for c in server.component_status if c["state"] != "OK"]
    existing = incident_service.get_active_incident(server_id=server.id, kind="COMPONENT")
    now = datetime.now(timezone.utc)

    if not problems:
        server.component_breach_streak = 0
        server.component_clear_streak = (server.component_clear_streak or 0) + 1
        db.session.commit()
        if existing and server.component_clear_streak >= COMPONENT_CLEARS_TO_CLOSE:
            incident_service.resolve_incident(existing, now)
            notification_service.send_server_recovery_notification(existing, server)
            logger.info("Server %s components healthy again, incident #%s resolved",
                        server.hostname, existing.id)
        return None

    server.component_clear_streak = 0
    server.component_breach_streak = (server.component_breach_streak or 0) + 1
    db.session.commit()

    if existing:
        return existing
    if server.component_breach_streak < COMPONENT_BREACHES_TO_OPEN:
        # A service restarting legitimately shows as stopped for one heartbeat.
        return None

    summary = "; ".join(f"{c['kind']} {c['name']} is {c['state']}" for c in problems)
    incident, created = incident_service.open_incident(
        server, detected_at=now, reason=f"Component check: {summary}",
        error_message=summary, is_server=True, kind="COMPONENT",
    )
    if created:
        logger.warning("Server %s component incident #%s: %s", server.hostname, incident.id, summary)
        notification_service.send_server_down_notification(incident, server, summary)
    return incident


# An application answering on a host proves the machine is up, but only a recent
# answer proves it is up *now*. Comfortably longer than the slowest monitoring
# interval, so one skipped cycle does not silently withdraw the evidence.
CORROBORATION_MAX_AGE_SECONDS = 900


def _as_utc(value):
    """Naive timestamps out of SQLite are UTC; this makes that explicit."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def applications_confirm_host(server):
    """Are applications on this server demonstrably serving traffic right now?

    Returns True (a recent check passed), False (recent checks all failed), or
    None (nothing linked to this server has been checked recently, so there is
    no evidence either way).

    The mirror of monitoring_service.host_is_reachable(). There, a live
    heartbeat vouches for a failed application check; here a passing
    application check vouches for a missing heartbeat. In both directions the
    evidence travels a different path from the signal it is judging, which is
    the only reason it is worth anything.

    Only applications explicitly linked through hosted_on_server_id count. An
    unlinked application says nothing about this particular host.
    """
    from app.models.application import Application

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CORROBORATION_MAX_AGE_SECONDS)
    evidence = False
    for application in Application.query.filter(
            Application.hosted_on_server_id == server.id,
            Application.deleted_at.is_(None),
            Application.monitoring_enabled.is_(True)).all():
        checked = _as_utc(application.last_checked_at)
        if checked is None or checked < cutoff:
            continue  # too old to say anything about the here and now
        evidence = True
        # last_successful_check_at is stamped with the same instant as
        # last_checked_at on success, so equality means the newest check passed.
        if _as_utc(application.last_successful_check_at) == checked:
            return True
    return False if evidence else None


def _agent_not_reporting(server, last_heartbeat, now):
    """Records a silent agent on a host that is demonstrably still serving.

    AGENT_DOWN rather than DOWN, because those are different faults with
    different fixes: DOWN means go and look at the machine, AGENT_DOWN means go
    and look at the agent. Calling this one DOWN pages somebody at 3am about a
    server that is answering HTTP 200, and the alert they learn to ignore is
    the same alert that matters when the machine really does fall over.

    Any REACHABILITY incident already open on that mistaken premise is closed
    here, silently - nothing recovered, so nobody is told that it did.
    """
    quiet_minutes = int((now - last_heartbeat).total_seconds() / 60)
    if server.current_status != "AGENT_DOWN":
        server.current_status = "AGENT_DOWN"
        db.session.commit()
        logger.warning(
            "Server %s has not reported for %d minutes, but its applications are "
            "responding - recording AGENT_DOWN, not an outage. Check the agent "
            "service and its hub_url.", server.hostname, quiet_minutes)

    incident = incident_service.get_active_incident(server_id=server.id, kind="REACHABILITY")
    if incident:
        incident_service.resolve_incident(incident, now)
        incident.resolution_category = "False alarm - monitoring"
        incident.resolution_note = (
            f"Applications hosted on {server.hostname} are responding, so the server "
            f"is running; only its agent has stopped reporting ({quiet_minutes} "
            f"minutes). Closed automatically - this was not an outage."
        )
        db.session.commit()
        logger.info("Incident #%s closed: %s is serving traffic, the agent is not reporting.",
                    incident.id, server.hostname)


def is_this_machine(server):
    """Is this the machine the platform itself is running on?

    Matched on hostname rather than configured, so it stays correct when the
    platform moves to another server - the answer changes by itself.
    """
    return (server.hostname or "").strip().lower() == socket.gethostname().strip().lower()


def check_missed_heartbeats(suppress_incidents=False):
    """Scans all servers for missed heartbeats and opens/keeps an incident open
    for any that have gone quiet too long. Called every monitoring cycle,
    alongside the existing application health checks.

    suppress_incidents is set when the cycle has judged the monitor itself to
    have been blind. Statuses still update, but no incident or alert is raised -
    a monitor that was asleep sees every agent as silent, and would otherwise
    declare the whole estate unreachable."""
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

        # The platform cannot be unreachable from itself. If this code is
        # running, the machine it is running on is up, whatever its agent did -
        # on 27 August the monitor wrote "FUJALW-LAP-STENITTE is unreachable"
        # into a log file on FUJALW-LAP-STENITTE, because the agent missed one
        # heartbeat while the machine was busy. The gap is still recorded and
        # still shows as stale; it is only the outage claim that is withdrawn.
        if is_this_machine(server):
            if server.current_status != "AGENT_DOWN":
                server.current_status = "AGENT_DOWN"
                db.session.commit()
                logger.info("Agent on %s (this machine) has not reported for %ds. The platform "
                            "is running here, so this is the agent, not an outage.",
                            server.hostname, int((now - last).total_seconds()))
            incident = incident_service.get_active_incident(server_id=server.id, kind="REACHABILITY")
            if incident:
                incident_service.resolve_incident(incident, now)
                incident.resolution_category = "False alarm - monitoring"
                incident.resolution_note = (
                    "The monitoring platform runs on this machine, so it cannot have been "
                    "unreachable. Closed automatically.")
                db.session.commit()
            continue

        # A missing heartbeat means we have lost contact with the agent. Whether
        # we have lost the *server* is a separate question, and one the
        # applications running on it can answer.
        if applications_confirm_host(server) is True:
            _agent_not_reporting(server, last, now)
            continue

        if server.current_status not in ("DOWN", "AGENT_DOWN"):
            server.current_status = "DOWN"
            db.session.commit()
            if suppress_incidents:
                logger.warning("Server %s appears unreachable, but the monitor was blind this "
                                "cycle - not raising an incident.", server.hostname)
                continue
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
