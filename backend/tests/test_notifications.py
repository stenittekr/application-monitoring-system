from unittest.mock import patch

from app.services.monitoring_service import run_health_check
from app.services.email_service import EmailSendError
from app.models.notification import Notification


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_down_sends_exactly_one_notification_per_outage(db, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_health_check(sample_application)  # opens incident, sends DOWN
            run_health_check(sample_application)  # still down, same incident
            run_health_check(sample_application)  # still down, same incident

    down_emails = [c for c in mock_send.call_args_list if "[ALERT]" in c.args[1]]
    assert len(down_emails) == 1

    notification = Notification.query.filter_by(notification_type="DOWN").first()
    assert notification.status == "SENT"
    assert notification.recipient == sample_application.owner_email
    assert notification.cc == sample_application.manager_email


def test_recovery_sends_recovery_notification(db, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(200)):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_health_check(sample_application)

    subjects = [c.args[1] for c in mock_send.call_args_list]
    assert any("[RECOVERY]" in s for s in subjects)

    notification = Notification.query.filter_by(notification_type="RECOVERY").first()
    assert notification.status == "SENT"


def test_email_failure_is_recorded_without_losing_the_incident(db, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email", side_effect=EmailSendError("smtp down")):
            run_health_check(sample_application)

    notification = Notification.query.filter_by(notification_type="DOWN").first()
    assert notification.status == "FAILED"
    assert notification.error_message == "smtp down"
    # The incident itself must still exist and be open despite the email failure.
    from app.models.incident import Incident
    incident = Incident.query.filter_by(application_id=sample_application.id).first()
    assert incident is not None
    assert incident.status == "OPEN"
    assert incident.notification_sent is False
