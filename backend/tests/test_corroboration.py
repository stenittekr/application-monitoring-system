"""A failed check is not proof the application failed.

On 25 August one application timed out for 14 hours while six others on the
same monitor succeeded. The application was fine; the network path from the
monitor to that host was not. Ten emails went out. These pin the rule that
stops that, without silencing a genuine application failure.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

from app.models.incident import Incident
from app.services import server_service
from app.services.monitoring_service import run_health_check


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _host(db, minutes_since_heartbeat):
    """A server whose agent last reported this long ago."""
    server, _ = server_service.enroll({"hostname": "APPHOST", "owner_email": "ops@awgtc.com"})
    server.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_since_heartbeat)
    server.heartbeat_interval_seconds = 60
    db.session.commit()
    return server


def _fail_checks(app_row, times=3):
    boom = requests.exceptions.ConnectTimeout("Request timed out")
    with patch("app.services.monitoring_service.requests.get", side_effect=boom):
        with patch("app.services.notification_service.send_email") as mock_send:
            for _ in range(times):
                run_health_check(app_row)
    return mock_send


def test_a_silent_host_means_unknown_not_down(db, sample_application):
    """Both directions failing: we cannot see that host, so we cannot say the
    application is down. This is the 25 August case exactly."""
    host = _host(db, minutes_since_heartbeat=600)      # agent silent for 10 hours
    sample_application.hosted_on_server_id = host.id
    db.session.commit()

    mock_send = _fail_checks(sample_application)

    assert sample_application.current_status == "UNKNOWN"
    assert Incident.query.count() == 0, "no incident may be opened on a guess"
    assert not mock_send.called, "and no email"


def test_a_live_host_means_the_application_really_is_down(db, sample_application):
    """The agent is reaching us over the same path, so the path works and the
    application is genuinely at fault. This must still alert."""
    host = _host(db, minutes_since_heartbeat=0)        # heartbeating now
    sample_application.hosted_on_server_id = host.id
    db.session.commit()

    mock_send = _fail_checks(sample_application)

    assert sample_application.current_status == "DOWN"
    assert Incident.query.count() == 1
    assert mock_send.called, "a real outage must still alert"


def test_an_application_with_no_recorded_host_behaves_as_before(db, sample_application):
    """Most applications are not on a monitored server. Nothing to corroborate
    with is not a reason to stop alerting."""
    assert sample_application.hosted_on_server_id is None
    mock_send = _fail_checks(sample_application)

    assert sample_application.current_status == "DOWN"
    assert Incident.query.count() == 1
    assert mock_send.called


def test_unknown_is_not_treated_as_healthy(db, sample_application):
    """§11: Unknown must never read as healthy."""
    host = _host(db, minutes_since_heartbeat=600)
    sample_application.hosted_on_server_id = host.id
    db.session.commit()
    _fail_checks(sample_application)

    assert sample_application.current_status == "UNKNOWN"
    assert sample_application.current_status != "UP"
    # The evidence is kept even though the conclusion is withheld.
    from app.models.health_check import HealthCheck
    assert HealthCheck.query.filter_by(success=False).count() >= 1


def test_recovery_from_unknown_still_works(db, sample_application):
    host = _host(db, minutes_since_heartbeat=600)
    sample_application.hosted_on_server_id = host.id
    db.session.commit()
    _fail_checks(sample_application)
    assert sample_application.current_status == "UNKNOWN"

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(200)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
    assert sample_application.current_status == "UP"
