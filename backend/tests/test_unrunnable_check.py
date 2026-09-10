"""A check that could not run is not a passing check.

On 25 August both MSSQL checks began raising ModuleNotFoundError, because
pyodbc was installed where the service could not see it. The cycle logged the
traceback and moved on. No health check row was written, no status changed, and
both applications displayed UP for two days while being checked 2,400 times and
answering none of them.

§11: "Unknown / Stale / Not Available must never be shown as Healthy."
"""
from unittest.mock import patch

import pytest

from app.models.health_check import HealthCheck
from app.models.incident import Incident
from app.services.monitoring_service import run_health_check


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _monitor_breaks(app_row, times=1):
    """The monitor itself failing - not the application refusing a connection."""
    boom = ModuleNotFoundError("No module named 'pyodbc'")
    with patch("app.services.monitoring_service._perform_http_attempt", side_effect=boom):
        with patch("app.services.notification_service.send_email") as mock_send:
            for _ in range(times):
                run_health_check(app_row)
    return mock_send


def test_a_check_that_cannot_run_is_unknown_not_up(db, sample_application):
    """The exact 25 August case."""
    assert sample_application.current_status == "UP"
    _monitor_breaks(sample_application)

    assert sample_application.current_status == "UNKNOWN"
    assert sample_application.current_status != "UP", "a broken check must not read as healthy"


def test_a_check_that_cannot_run_is_not_reported_as_down_either(db, sample_application):
    """Reporting DOWN would be the same lie in the other direction."""
    mock_send = _monitor_breaks(sample_application, times=5)

    assert sample_application.current_status == "UNKNOWN"
    assert Incident.query.count() == 0, "we know nothing, so there is nothing to declare"
    assert not mock_send.called


def test_the_failure_is_recorded_rather_than_swallowed(db, sample_application):
    """A row must exist saying the check did not happen, or nobody can tell
    a monitored application from an unmonitored one."""
    _monitor_breaks(sample_application)

    check = HealthCheck.query.order_by(HealthCheck.id.desc()).first()
    assert check is not None, "silence is the bug"
    assert check.status == "UNKNOWN"
    assert check.success is False
    assert "pyodbc" in check.error_message
    assert check.response_time is None, "no probe was timed, so nothing may be averaged in"


def test_an_unrunnable_check_does_not_close_an_open_incident(db, sample_application):
    """Otherwise losing a driver announces every outage as recovered."""
    import requests
    boom = requests.exceptions.ConnectTimeout("Request timed out")
    with patch("app.services.monitoring_service.requests.get", side_effect=boom):
        with patch("app.services.notification_service.send_email"):
            for _ in range(3):
                run_health_check(sample_application)
    incident = Incident.query.one()
    assert incident.status == "OPEN"

    with patch("app.services.notification_service.send_email") as mock_send:
        _monitor_breaks(sample_application)

    assert incident.status == "OPEN", "we stopped being able to look, nothing recovered"
    assert not mock_send.called, "and nobody may be told that it did"


def test_an_unrunnable_check_does_not_discard_a_failure_streak(db, sample_application):
    """A gap in the record must not reset progress towards confirming an outage."""
    import requests
    boom = requests.exceptions.ConnectTimeout("Request timed out")
    with patch("app.services.monitoring_service.requests.get", side_effect=boom):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
    assert sample_application.failure_streak == 1

    with patch("app.services.notification_service.send_email"):
        _monitor_breaks(sample_application)

    assert sample_application.failure_streak == 1, "the streak is paused, not erased"


def test_a_real_recovery_still_closes_the_incident(db, sample_application):
    """The guard must not break ordinary recovery."""
    import requests
    boom = requests.exceptions.ConnectTimeout("Request timed out")
    with patch("app.services.monitoring_service.requests.get", side_effect=boom):
        with patch("app.services.notification_service.send_email"):
            for _ in range(3):
                run_health_check(sample_application)
    incident = Incident.query.one()
    assert incident.status == "OPEN"

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(200)):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_health_check(sample_application)

    assert incident.status == "RESOLVED"
    assert sample_application.current_status == "UP"
    assert mock_send.called, "a genuine recovery is still announced"
