import socket
from unittest.mock import patch, MagicMock

import requests

from app.services.monitoring_service import run_health_check
from app.models.health_check import HealthCheck


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_successful_check_marks_application_up(db, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(200)):
        run_health_check(sample_application)

    assert sample_application.current_status == "UP"
    assert HealthCheck.query.filter_by(application_id=sample_application.id).count() == 1


def test_unexpected_status_code_counts_as_failure(db, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        run_health_check(sample_application)

    check = HealthCheck.query.filter_by(application_id=sample_application.id).first()
    assert check.success is False
    assert check.http_status_code == 500


def test_503_counts_as_failure(db, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(503)):
        run_health_check(sample_application)

    assert sample_application.current_status == "DOWN"


def test_timeout_is_recorded_as_failure(db, sample_application):
    with patch("app.services.monitoring_service.requests.get", side_effect=requests.exceptions.Timeout()):
        run_health_check(sample_application)

    check = HealthCheck.query.filter_by(application_id=sample_application.id).first()
    assert check.success is False
    assert "timed out" in check.error_message.lower()


def test_retries_before_confirming_down(db, sample_application):
    sample_application.retry_count = 3
    db.session.commit()

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)) as mock_get:
        run_health_check(sample_application)

    assert mock_get.call_count == 3  # one attempt per retry, all failing
    checks = HealthCheck.query.filter_by(application_id=sample_application.id).order_by(HealthCheck.attempt_number).all()
    assert [c.attempt_number for c in checks] == [1, 2, 3]
    assert sample_application.current_status == "DOWN"


def test_recovery_within_retries_stops_early(db, sample_application):
    sample_application.retry_count = 3
    db.session.commit()

    responses = [FakeResponse(500), FakeResponse(200)]
    with patch("app.services.monitoring_service.requests.get", side_effect=responses) as mock_get:
        run_health_check(sample_application)

    assert mock_get.call_count == 2  # stopped retrying once it succeeded
    assert sample_application.current_status == "UP"


def _make_tcp_application(db):
    from app.models.application import Application

    app_row = Application(
        name="TCP App", server="db.internal", port=1433, health_check_type="TCP",
        environment="Production", owner_name="Owner", owner_email="owner@test.com",
        manager_name="Manager", manager_email="manager@test.com",
        retry_count=2, retry_delay=0, timeout=5, current_status="UP",
    )
    db.session.add(app_row)
    db.session.commit()
    return app_row


def test_tcp_check_success_marks_up(db):
    app_row = _make_tcp_application(db)
    with patch("app.services.monitoring_service.socket.create_connection") as mock_connect:
        mock_connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        run_health_check(app_row)

    mock_connect.assert_called_once_with(("db.internal", 1433), timeout=5)
    assert app_row.current_status == "UP"
    check = HealthCheck.query.filter_by(application_id=app_row.id).first()
    assert check.http_status_code is None
    assert check.success is True


def test_tcp_check_connection_refused_marks_down(db):
    app_row = _make_tcp_application(db)
    with patch("app.services.monitoring_service.socket.create_connection", side_effect=ConnectionRefusedError()):
        run_health_check(app_row)

    assert app_row.current_status == "DOWN"
    check = HealthCheck.query.filter_by(application_id=app_row.id).first()
    assert check.success is False
    assert "TCP connection failed" in check.error_message


def test_tcp_check_timeout_marks_down(db):
    app_row = _make_tcp_application(db)
    with patch("app.services.monitoring_service.socket.create_connection", side_effect=socket.timeout()):
        run_health_check(app_row)

    check = HealthCheck.query.filter_by(application_id=app_row.id).first()
    assert check.success is False
    assert "timed out" in check.error_message.lower()


# --------------------------------------------------------------------------
# §1: "a running process does not prove that an application is usable".
# A status code proves something answered. It does not prove what answered.
# --------------------------------------------------------------------------

class _Body:
    def __init__(self, status_code, text):
        self.status_code, self.text = status_code, text


def test_a_200_that_says_unavailable_is_not_up(db, sample_application):
    """The failure this exists for: an error page returning 200."""
    sample_application.expect_absent = "Service Unavailable"
    db.session.commit()
    with patch("app.services.monitoring_service.requests.get",
               return_value=_Body(200, "<h1>Service Unavailable</h1>")):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
    assert sample_application.current_status == "DOWN"


def test_a_page_missing_its_expected_content_is_not_up(db, sample_application):
    sample_application.expect_contains = "Sign in"
    db.session.commit()
    with patch("app.services.monitoring_service.requests.get",
               return_value=_Body(200, "<html>nothing useful here</html>")):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
    assert sample_application.current_status == "DOWN"


def test_the_real_page_passes_both_rules(db, sample_application):
    sample_application.expect_contains = "Sign in"
    sample_application.expect_absent = "Service Unavailable"
    db.session.commit()
    with patch("app.services.monitoring_service.requests.get",
               return_value=_Body(200, "<form>Sign in</form>")):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
    assert sample_application.current_status == "UP"


def test_an_application_with_no_rules_behaves_exactly_as_before(db, sample_application):
    """Existing checks must not change behaviour, or every application needs
    re-verifying before this can ship."""
    assert sample_application.expect_contains is None
    with patch("app.services.monitoring_service.requests.get",
               return_value=_Body(200, "anything at all")):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
    assert sample_application.current_status == "UP"
