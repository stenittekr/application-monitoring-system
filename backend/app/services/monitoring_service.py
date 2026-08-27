"""Core health-check execution and status-transition logic.

This is the single source of truth for "what happens when we check an
application" - used by the manual "run check now" API endpoint AND by the
standalone monitoring/ scheduler process, so behavior never diverges.
"""
import json
import logging
import os
import re
import socket
import time
from datetime import datetime, timezone
from functools import lru_cache

import requests
import ssl
import urllib3
from urllib.parse import urlparse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.extensions import db
from app.models.health_check import HealthCheck
from app.services import incident_service, notification_service, maintenance_service
from app.utils.redaction import redact

logger = logging.getLogger(__name__)

DEGRADED_RESPONSE_MS = 3000  # success but slow => DEGRADED instead of UP

# Whole checks that must fail in a row before an incident is opened and anyone
# is emailed. retry_count already retries within a single check; this requires
# the failure to survive across separate checks, minutes apart, so a transient
# blip on one poll never produces an alert for a site that is actually serving.
FAILED_CHECKS_BEFORE_INCIDENT_DEFAULT = "2"


def _checks_before_incident():
    """How many consecutive failed checks are required, from system_settings."""
    from app.models.system_setting import SystemSetting

    row = SystemSetting.query.filter_by(setting_key="failed_checks_before_incident").first()
    try:
        return max(1, int(row.setting_value)) if row and row.setting_value else int(FAILED_CHECKS_BEFORE_INCIDENT_DEFAULT)
    except (TypeError, ValueError):
        return int(FAILED_CHECKS_BEFORE_INCIDENT_DEFAULT)

# Apps with verify_ssl=False (opt-in, e.g. internal CA not in this trust store)
# would otherwise spam InsecureRequestWarning on every single check.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _perform_single_attempt(application):
    """Sends one health-check probe (HTTP/HTTPS request or TCP connect,
    depending on the application's configured type) and returns a dict
    describing the outcome.

    Each probe catches the failures that are *evidence about the target* - a
    refused connection, a timeout, a driver refusing the credentials - and
    reports them as DOWN. Anything that escapes to here is a fault in the
    monitor instead: a missing driver, a malformed DSN, a bug of ours. That is
    not evidence of anything, so it is reported as UNKNOWN.
    """
    try:
        if application.health_check_type == "TCP":
            return _perform_tcp_attempt(application)
        if application.health_check_type == "DATABASE":
            return _perform_database_attempt(application)
        if application.health_check_type == "WORKFLOW":
            return _perform_workflow_attempt(application)
        return _perform_http_attempt(application)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see below
        # Broad on purpose. Every narrower except above returns a verdict; the
        # only thing left here is the monitor breaking, and the one outcome we
        # must never produce for that is silence.
        logger.exception("Check for application %s could not run", application.name)
        return _unrunnable(f"{type(exc).__name__}: {exc}")


def _perform_tcp_attempt(application):
    """Attempts a raw TCP connection to application.server:application.port."""
    start = time.monotonic()
    try:
        with socket.create_connection((application.server, application.port), timeout=application.timeout):
            elapsed_ms = (time.monotonic() - start) * 1000
            status = "DEGRADED" if elapsed_ms > DEGRADED_RESPONSE_MS else "UP"
            return {
                "success": True,
                "status": status,
                "http_status_code": None,
                "response_time": elapsed_ms,
                "error_message": None,
            }
    except socket.timeout:
        return _failure(start, "TCP connection timed out")
    except socket.gaierror as exc:
        return _failure(start, f"DNS resolution failed: {exc}")
    except OSError as exc:
        return _failure(start, f"TCP connection failed: {exc}")


# Per-dialect name for "how long to wait for the connection". There is no
# common spelling of this across DB-API drivers, so it has to be looked up.
_CONNECT_TIMEOUT_ARG = {"mssql": "timeout", "mysql": "connect_timeout"}


# ${VAR} or %VAR% standing in for the whole password, and nothing else.
_PASSWORD_VAR_RE = re.compile(r"^\$\{(\w+)\}$|^%(\w+)%$")


def _expand_dsn(raw):
    """Returns the DSN as a URL with its ${ENV_VAR} password resolved.

    The substitution happens on the parsed URL object, never on the URL text.
    Real passwords contain URL-significant characters - "Awgt@2020" has an @
    that ends the userinfo, "S#a#p#2024" has a # that starts a fragment - so
    expanding into the string first silently rewrites the host and the check
    times out against an address nobody meant to contact."""
    url = make_url(raw)
    match = _PASSWORD_VAR_RE.match(url.password or "")
    if match:
        url = url.set(password=os.environ.get(match.group(1) or match.group(2), ""))
    return url


@lru_cache(maxsize=64)
def _db_engine(dsn, timeout):
    """Builds (and caches) an Engine for one DSN. NullPool on purpose: a
    connectivity check must open a genuinely new connection every time, or it
    would happily report UP by reusing a pooled handle to a dead server."""
    url = _expand_dsn(dsn)
    connect_args = {}
    arg = _CONNECT_TIMEOUT_ARG.get(url.get_backend_name())
    if arg:
        connect_args[arg] = timeout
    return create_engine(url, poolclass=NullPool, connect_args=connect_args, hide_parameters=True)


# What lives on the instance, per dialect. Read-only catalogue queries.
_INVENTORY_SQL = {
    "mssql": ("select d.name, d.state_desc, d.recovery_model_desc from sys.databases d order by d.name",
              ("name", "state", "recovery_model")),
    "mysql": ("select schema_name, 'ONLINE', null from information_schema.schemata order by schema_name",
              ("name", "state", "recovery_model")),
}


def collect_database_inventory(connection, url):
    """Lists the databases on the instance. Best-effort: a login without
    catalogue rights returns [] rather than failing the health check, because
    this is extra context, not the thing being monitored."""
    query = _INVENTORY_SQL.get(url.get_backend_name())
    if not query:
        return []
    sql, fields = query
    try:
        return [dict(zip(fields, [row[0], row[1], row[2]])) for row in connection.execute(text(sql))]
    except SQLAlchemyError:
        return []


def _perform_database_attempt(application):
    """Connects to application.url (a SQLAlchemy DSN) and runs SELECT 1.

    The stored DSN carries ${ENV_VAR} in place of the password - validation
    enforces that - so no credential is ever written to the applications table.
    It is expanded here, at check time, from the process environment."""
    start = time.monotonic()
    dsn = application.url or ""
    secret = _expand_dsn(dsn).password if dsn else None
    try:
        with _db_engine(dsn, application.timeout).connect() as connection:
            connection.execute(text("SELECT 1"))
            # Stop the clock first: response_time must measure the connectivity
            # probe, not the inventory query that follows it.
            elapsed_ms = (time.monotonic() - start) * 1000
            inventory = collect_database_inventory(connection, _expand_dsn(dsn))
        if inventory:
            application.discovered_databases_json = json.dumps(inventory)
            db.session.commit()
        return {
            "success": True,
            "status": "DEGRADED" if elapsed_ms > DEGRADED_RESPONSE_MS else "UP",
            "http_status_code": None,
            "response_time": elapsed_ms,
            "error_message": None,
        }
    except (SQLAlchemyError, OSError, ValueError) as exc:
        # Driver errors quote the connection string back at you, so the expanded
        # password has to be scrubbed before this is stored and emailed out.
        message = redact(str(exc), extra=[secret] if secret else ())
        return _failure(start, f"Database connection failed: {message[:400]}")


# How often to re-read a certificate. It moves once a year; an extra TLS
# handshake on every check would be pure waste.
CERT_REFRESH_HOURS = 24
CERT_WARNING_DAYS_DEFAULT = "30"


def _refresh_certificate(application):
    """Reads the TLS certificate expiry for an HTTPS application.

    Best-effort and completely separate from the health check: a certificate we
    cannot read is not an outage, and must never turn a working site red.
    Skipped entirely when verify_ssl is off, since the whole point there is that
    the certificate is not trusted anyway.
    """
    if not (application.url or "").lower().startswith("https://") or not application.verify_ssl:
        return
    now = datetime.now(timezone.utc)
    last = application.cert_checked_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < CERT_REFRESH_HOURS * 3600:
            return

    parsed = urlparse(application.url)
    host, port = parsed.hostname, parsed.port or 443
    if not host:
        return
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=application.timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
        # notAfter looks like "Jun  1 12:00:00 2027 GMT" - always this format,
        # always GMT, per RFC 5280.
        expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        issuer = dict(x[0] for x in cert.get("issuer", ())).get("organizationName")
        application.cert_expires_at = expires
        application.cert_issuer = (issuer or "")[:300] or None
    except Exception as exc:  # noqa: BLE001 - any failure here is non-fatal
        logger.debug("Certificate read failed for %s: %s", application.name, redact(str(exc)))
    finally:
        application.cert_checked_at = now
        db.session.commit()


def expiring_certificates(within_days=None):
    """Applications whose certificate expires within the window, soonest first."""
    from app.models.system_setting import SystemSetting

    if within_days is None:
        row = SystemSetting.query.filter_by(setting_key="cert_warning_days").first()
        try:
            within_days = int(row.setting_value) if row and row.setting_value else int(CERT_WARNING_DAYS_DEFAULT)
        except (TypeError, ValueError):
            within_days = int(CERT_WARNING_DAYS_DEFAULT)
    from app.models.application import Application

    rows = [a for a in Application.query.filter(Application.deleted_at.is_(None),
                                                 Application.cert_expires_at.isnot(None))
            if a.cert_days_remaining is not None and a.cert_days_remaining <= within_days]
    return sorted(rows, key=lambda a: a.cert_days_remaining)


def _perform_workflow_attempt(application):
    """Runs the application's synthetic business transaction (layer 5).

    A workflow failing is a real outage: the site answered, but nobody can
    actually use it. That is precisely the case a URL check cannot see."""
    from app.services.workflow_service import run_workflow

    steps = application.workflow_steps
    if not steps:
        return _failure(0.0, "No workflow steps configured for this application.")

    start = time.monotonic()
    success, message, elapsed_ms = run_workflow(application, steps)
    if not success:
        return {
            "success": False, "status": "DOWN", "http_status_code": None,
            "response_time": elapsed_ms, "error_message": redact(message),
        }
    return {
        "success": True,
        "status": "DEGRADED" if elapsed_ms > DEGRADED_RESPONSE_MS else "UP",
        "http_status_code": None, "response_time": elapsed_ms, "error_message": None,
    }


def _perform_http_attempt(application):
    """Sends one HTTP request and returns a dict describing the outcome."""
    start = time.monotonic()
    try:
        response = requests.get(
            application.url, timeout=application.timeout, allow_redirects=True, verify=application.verify_ssl
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        success = response.status_code == application.expected_status_code
        if not success:
            return {
                "success": False,
                "status": "DOWN",
                "http_status_code": response.status_code,
                "response_time": elapsed_ms,
                "error_message": (
                    f"Unexpected status code {response.status_code}, "
                    f"expected {application.expected_status_code}"
                ),
            }
        status = "DEGRADED" if elapsed_ms > DEGRADED_RESPONSE_MS else "UP"
        return {
            "success": True,
            "status": status,
            "http_status_code": response.status_code,
            "response_time": elapsed_ms,
            "error_message": None,
        }
    except requests.exceptions.Timeout:
        return _failure(start, "Request timed out")
    except requests.exceptions.SSLError as exc:
        return _failure(start, f"SSL certificate error: {exc}")
    except requests.exceptions.ConnectionError as exc:
        return _failure(start, f"Connection failed (DNS/refused/unreachable): {exc}")
    except requests.exceptions.RequestException as exc:
        return _failure(start, str(exc))


def _unrunnable(message):
    """The result for a check that never ran.

    On 25 August the MSSQL checks began raising ModuleNotFoundError because
    pyodbc was installed where the service could not see it. The cycle logged
    the traceback and moved on, so no health check row was written, no status
    changed, and both applications sat on the dashboard showing UP for two
    days while being checked 2,400 times and answering none of them.

    A check that cannot run tells us nothing about the application. §11 is
    explicit that nothing we are unsure of may read as healthy, so it is
    recorded as UNKNOWN: visible, not green, and not an outage either -
    reporting DOWN would be the same lie in the other direction.

    response_time is None rather than 0.0 for the same reason: no probe was
    timed, and a zero would drag the response-time average towards a
    performance improvement that never happened.
    """
    return {
        "success": False,
        "status": "UNKNOWN",
        "http_status_code": None,
        "response_time": None,
        "error_message": redact(f"Check could not run: {message}")[:400],
    }


def _failure(start, message):
    """Builds the standard DOWN result dict for a failed attempt, timing it from `start`.

    Redaction happens here rather than at each call site: this message is
    persisted on the health check, copied onto the incident, and emailed out."""
    elapsed_ms = (time.monotonic() - start) * 1000
    message = redact(message)
    return {
        "success": False,
        "status": "DOWN",
        "http_status_code": None,
        "response_time": elapsed_ms,
        "error_message": message,
    }


# A heartbeat older than this many of the server's own intervals means the agent
# is not currently reaching us either.
CORROBORATION_STALE_INTERVALS = 3


def host_is_reachable(application):
    """Is the application's host demonstrably in contact with us right now?

    Returns True (agent heartbeating), False (agent silent), or None (nothing
    recorded to corroborate with).

    An agent heartbeat is inbound over the same network path our outbound check
    uses. A live heartbeat therefore proves the path works, which makes a failed
    HTTP check the application's fault. Both failing together means the path
    itself is gone, and blaming the application would be a guess.
    """
    # The host first, because its agent shares the application's fate exactly.
    # Failing that, a nominated witness on the same network - for a database on
    # a machine we do not monitor, a server we do monitor on the same network
    # is the only evidence available, and it is better than none.
    server_id = application.hosted_on_server_id or application.network_witness_server_id
    if not server_id:
        return None
    from app.models.server import Server

    server = db.session.get(Server, server_id)
    if not server or not server.last_heartbeat_at:
        return None
    last = server.last_heartbeat_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    allowed = (server.heartbeat_interval_seconds or 60) * CORROBORATION_STALE_INTERVALS
    return (datetime.now(timezone.utc) - last).total_seconds() <= allowed


def apply_transition_from(application, health_check):
    """Drives the incident/notification lifecycle from an already-persisted check.

    Split out from run_health_check so the monitoring cycle can look at every
    result before deciding whether any of them should be believed - if the
    monitor itself lost the network, every check "fails" and none of those
    failures are real."""
    _apply_transition(application, {
        "success": health_check.success,
        "status": health_check.status,
        "http_status_code": health_check.http_status_code,
        "error_message": health_check.error_message,
    }, health_check.checked_at)


def run_health_check(application, apply_transition=True):
    """Runs up to `retry_count` attempts (with `retry_delay` between them),
    persists every attempt, updates the application, and drives the
    incident/notification lifecycle. Returns the final HealthCheck row."""
    total_attempts = max(1, application.retry_count)
    result = None
    final_health_check = None

    for attempt in range(1, total_attempts + 1):
        result = _perform_single_attempt(application)
        checked_at = datetime.now(timezone.utc)

        health_check = HealthCheck(
            application_id=application.id,
            checked_at=checked_at,
            status=result["status"],
            http_status_code=result["http_status_code"],
            response_time=result["response_time"],
            success=result["success"],
            error_message=result["error_message"],
            attempt_number=attempt,
        )
        db.session.add(health_check)
        db.session.commit()
        final_health_check = health_check

        if result["success"]:
            break  # confirmed reachable - no need to keep retrying
        if attempt < total_attempts:
            time.sleep(application.retry_delay)

    # After the measurement, never inside it.
    _refresh_certificate(application)

    if apply_transition:
        _apply_transition(application, result, final_health_check.checked_at)
    return final_health_check


def _apply_transition(application, result, checked_at):
    application.current_status = result["status"]
    application.last_checked_at = checked_at
    if result["success"]:
        application.last_successful_check_at = checked_at
    else:
        application.last_failed_check_at = checked_at
    db.session.commit()

    if maintenance_service.is_in_maintenance(application.id):
        return

    now_down = result["status"] == "DOWN"

    # A check that never ran is not a success and not a failure; it is a gap in
    # the record. Clearing the streak on one would discard a genuine outage's
    # progress towards being confirmed.
    unrunnable = result["status"] == "UNKNOWN" and not result["success"]

    # Consecutive whole checks, not retries inside one check. A blip on a single
    # poll must never alert for a site that is actually serving.
    if now_down:
        application.failure_streak = (application.failure_streak or 0) + 1
    elif not unrunnable:
        application.failure_streak = 0
    db.session.commit()

    # Driven by whether an incident is actually open, not by the status
    # transition: current_status flips to DOWN on the first failure so the
    # dashboard tells the truth, but that must not consume the transition the
    # alerting depends on.
    incident = incident_service.get_active_incident(application.id)
    required = _checks_before_incident()

    if now_down:
        # Before blaming the application, check whether we can see its host at
        # all. §11 is explicit that Unknown must never read as healthy - it does
        # not alert, but it is not UP either.
        corroborated = host_is_reachable(application)
        if corroborated is False and not incident:
            application.current_status = "UNKNOWN"
            db.session.commit()
            logger.warning(
                "Application %s failed, but its host %s is not reaching us either - "
                "recording UNKNOWN rather than DOWN. This looks like a network path "
                "problem between the monitor and that host, not an application fault.",
                application.name, application.hosted_on_server_id)
            return

        if incident:
            notification_service.maybe_send_reminder(incident, application)
        elif application.failure_streak >= required:
            incident, created = incident_service.open_incident(
                application,
                detected_at=checked_at,
                reason=result["error_message"] or "Health check failed after retries",
                http_status_code=result["http_status_code"],
                error_message=result["error_message"],
            )
            if created:
                logger.warning("Incident #%s opened for application %s", incident.id, application.name)
            notification_service.send_down_notification(
                incident, application, result["http_status_code"], result["error_message"]
            )
        else:
            logger.info("Application %s failed check %d of %d required - not alerting until confirmed.",
                        application.name, application.failure_streak, required)
    elif incident and result["success"]:
        # Only an actual success closes an incident. Without the guard, the
        # monitor losing its database driver would announce every open outage
        # as recovered.
        incident_service.resolve_incident(incident, checked_at)
        notification_service.send_recovery_notification(incident, application)
        logger.info("Incident #%s resolved for application %s", incident.id, application.name)
