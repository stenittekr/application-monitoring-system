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


def _set_setting(db, key, value):
    from app.models.system_setting import SystemSetting

    row = SystemSetting.query.filter_by(setting_key=key).first()
    if row:
        row.setting_value = value
    else:
        db.session.add(SystemSetting(setting_key=key, setting_value=value))
    db.session.commit()


def _reminder_subjects(db, sample_application, quiet_days):
    """Runs one down-then-still-down cycle with quiet_days set, returns REMINDER subjects."""
    from datetime import datetime, timedelta, timezone

    _set_setting(db, "reminder_notifications_enabled", "true")
    _set_setting(db, "reminder_interval_minutes", "60")
    _set_setting(db, "quiet_days", quiet_days)

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)  # opens incident, sends DOWN

    # Age the DOWN notification so the reminder interval has elapsed.
    down = Notification.query.filter_by(notification_type="DOWN").first()
    down.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.session.commit()

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_health_check(sample_application)

    return [c.args[1] for c in mock_send.call_args_list if "[REMINDER]" in c.args[1]]


def test_reminders_are_held_back_on_quiet_days(db, sample_application):
    from datetime import datetime

    today = str(datetime.now().weekday())
    assert _reminder_subjects(db, sample_application, today) == []


def test_reminders_still_go_out_on_working_days(db, sample_application):
    assert _reminder_subjects(db, sample_application, "") != []


def test_nothing_is_emailed_on_a_quiet_day_but_the_alert_is_held(db, sample_application):
    """A weekend outage must not email, and must not be lost either."""
    from datetime import datetime
    from app.models.incident import Incident

    _set_setting(db, "quiet_days", str(datetime.now().weekday()))

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_health_check(sample_application)

    assert mock_send.call_args_list == []

    # The incident is real and the alert is queued with its full body intact.
    incident = Incident.query.filter_by(application_id=sample_application.id).first()
    assert incident.status == "OPEN"
    assert incident.notification_sent is False

    held = Notification.query.filter_by(notification_type="DOWN").one()
    assert held.status == "PENDING"
    assert held.retry_count == 0
    assert sample_application.url in held.body


def test_held_alert_is_delivered_on_the_next_working_day(db, sample_application):
    from datetime import datetime
    from app.services.notification_service import retry_failed_notifications
    from app.models.incident import Incident

    _set_setting(db, "quiet_days", str(datetime.now().weekday()))
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)

    _set_setting(db, "quiet_days", "")  # the weekend is over
    with patch("app.services.notification_service.send_email") as mock_send:
        retry_failed_notifications()

    assert len(mock_send.call_args_list) == 1
    _recipient, subject, body = mock_send.call_args_list[0].args[:3]
    assert "[ALERT]" in subject
    assert sample_application.url in body  # the real alert, not a placeholder

    held = Notification.query.filter_by(notification_type="DOWN").one()
    assert held.status == "SENT"
    assert Incident.query.filter_by(application_id=sample_application.id).one().notification_sent is True


def test_one_failed_check_does_not_alert(db, sample_application):
    """A single bad poll is not an outage. Alerting on one is how a site that is
    actually serving ends up generating a DOWN email."""
    _set_setting(db, "failed_checks_before_incident", "2")  # the production default
    from app.models.incident import Incident

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_health_check(sample_application)

    assert Incident.query.count() == 0
    assert not mock_send.called
    assert sample_application.failure_streak == 1


def test_a_confirmed_failure_alerts_once_and_states_the_reason(db, sample_application):
    _set_setting(db, "failed_checks_before_incident", "2")  # the production default
    from app.models.incident import Incident

    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_health_check(sample_application)   # 1st failure - held
            run_health_check(sample_application)   # 2nd - confirmed, alerts

    assert Incident.query.count() == 1
    down = [c for c in mock_send.call_args_list if "[ALERT]" in c.args[1]]
    assert len(down) == 1

    body = down[0].args[2]
    assert "Reason:" in body, "the alert must say what happened when we tried the site"
    assert "500" in body


def test_recovery_between_checks_resets_the_streak(db, sample_application):
    """Fail, recover, fail again is not two consecutive failures."""
    _set_setting(db, "failed_checks_before_incident", "2")
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(200)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
    assert sample_application.failure_streak == 0

    from app.models.incident import Incident
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_health_check(sample_application)
    assert Incident.query.count() == 0
    assert not mock_send.called


def test_standing_cc_list_is_added_to_application_alerts(db, sample_application):
    from app.models.notification import Notification

    _set_setting(db, "alert_cc_recipients", "ajoy@awgtc.com, raam@awgtc.com")
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)
            run_health_check(sample_application)

    cc = Notification.query.filter_by(notification_type="DOWN").one().cc
    assert "ajoy@awgtc.com" in cc
    assert "raam@awgtc.com" in cc
    assert sample_application.manager_email in cc


def test_a_resource_alert_is_not_titled_server_unreachable(db):
    """A CPU threshold alert must not claim the machine is unreachable.

    The real one that prompted this said "Server Unreachable" with a body of
    "CPU 100% >= critical 95%". The server was answering throughout; the subject
    sent the reader looking for a dead machine.
    """
    from datetime import datetime, timezone

    from app.models.incident import Incident
    from app.services import notification_service, server_service

    server, _ = server_service.enroll({"hostname": "SUBJHOST", "owner_email": "ops@awgtc.com"})
    incident = Incident(server_id=server.id, kind="RESOURCE", status="OPEN",
                        started_at=datetime.now(timezone.utc),
                        detected_at=datetime.now(timezone.utc),
                        reason="CPU 100% >= critical 95%")
    db.session.add(incident)
    db.session.commit()

    with patch("app.services.notification_service.send_email"):
        notification = notification_service.send_server_down_notification(
            incident, server, "CPU 100% >= critical 95%")

    assert "Unreachable" not in notification.subject
    assert "Resource Warning" in notification.subject
