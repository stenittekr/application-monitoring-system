from unittest.mock import patch

from app.services.monitoring_service import run_health_check
from app.models.incident import Incident


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _run_down_check(sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)


def _run_up_check(sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(200)):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)


def test_down_detection_creates_incident(db, sample_application):
    _run_down_check(sample_application)
    incidents = Incident.query.filter_by(application_id=sample_application.id).all()
    assert len(incidents) == 1
    assert incidents[0].status == "OPEN"


def test_repeated_failures_do_not_create_duplicate_incidents(db, sample_application):
    _run_down_check(sample_application)
    _run_down_check(sample_application)
    _run_down_check(sample_application)

    incidents = Incident.query.filter_by(application_id=sample_application.id).all()
    assert len(incidents) == 1


def test_recovery_resolves_incident_and_calculates_downtime(db, sample_application):
    _run_down_check(sample_application)
    _run_up_check(sample_application)

    incident = Incident.query.filter_by(application_id=sample_application.id).first()
    assert incident.status == "RESOLVED"
    assert incident.resolved_at is not None
    assert incident.duration_seconds is not None
    assert incident.duration_seconds >= 0


def test_new_outage_after_recovery_opens_a_new_incident(db, sample_application):
    _run_down_check(sample_application)
    _run_up_check(sample_application)
    _run_down_check(sample_application)

    incidents = Incident.query.filter_by(application_id=sample_application.id).all()
    assert len(incidents) == 2
    assert incidents[0].status == "RESOLVED"
    assert incidents[1].status == "OPEN"
