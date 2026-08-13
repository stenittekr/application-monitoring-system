"""Core health-check execution and status-transition logic.

This is the single source of truth for "what happens when we check an
application" - used by the manual "run check now" API endpoint AND by the
standalone monitoring/ scheduler process, so behavior never diverges.
"""
import logging
import socket
import time
from datetime import datetime, timezone

import requests
import urllib3

from app.extensions import db
from app.models.health_check import HealthCheck
from app.services import incident_service, notification_service, maintenance_service

logger = logging.getLogger(__name__)

DEGRADED_RESPONSE_MS = 3000  # success but slow => DEGRADED instead of UP

# Apps with verify_ssl=False (opt-in, e.g. internal CA not in this trust store)
# would otherwise spam InsecureRequestWarning on every single check.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _perform_single_attempt(application):
    """Sends one health-check probe (HTTP/HTTPS request or TCP connect,
    depending on the application's configured type) and returns a dict
    describing the outcome."""
    if application.health_check_type == "TCP":
        return _perform_tcp_attempt(application)
    return _perform_http_attempt(application)


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


def _failure(start, message):
    """Builds the standard DOWN result dict for a failed attempt, timing it from `start`."""
    elapsed_ms = (time.monotonic() - start) * 1000
    return {
        "success": False,
        "status": "DOWN",
        "http_status_code": None,
        "response_time": elapsed_ms,
        "error_message": message,
    }


def run_health_check(application):
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

    _apply_transition(application, result, final_health_check.checked_at)
    return final_health_check


def _apply_transition(application, result, checked_at):
    previous_status = application.current_status

    application.current_status = result["status"]
    application.last_checked_at = checked_at
    if result["success"]:
        application.last_successful_check_at = checked_at
    else:
        application.last_failed_check_at = checked_at
    db.session.commit()

    if maintenance_service.is_in_maintenance(application.id):
        return

    was_down = previous_status == "DOWN"
    now_down = result["status"] == "DOWN"

    if now_down and not was_down:
        incident, created = incident_service.open_incident(
            application,
            detected_at=checked_at,
            reason="Health check failed after retries",
            http_status_code=result["http_status_code"],
            error_message=result["error_message"],
        )
        if created:
            logger.warning("Incident #%s opened for application %s", incident.id, application.name)
        notification_service.send_down_notification(
            incident, application, result["http_status_code"], result["error_message"]
        )
    elif now_down and was_down:
        incident = incident_service.get_active_incident(application.id)
        if incident:
            notification_service.maybe_send_reminder(incident, application)
    elif was_down and not now_down:
        incident = incident_service.get_active_incident(application.id)
        if incident:
            incident_service.resolve_incident(incident, checked_at)
            notification_service.send_recovery_notification(incident, application)
            logger.info("Incident #%s resolved for application %s", incident.id, application.name)
