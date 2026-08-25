"""The monitor must not report its own blindness as an estate-wide outage.

Three times in four days a sleeping laptop produced a false outage across every
monitored target at once - 27 emails on one occasion. These pin the guard.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.models.application import Application
from app.models.incident import Incident


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _make_apps(db, admin_user, count):
    rows = []
    for i in range(count):
        row = Application(
            name=f"App {i}", url=f"https://app{i}.example.com", environment="Production",
            owner_name="O", owner_email="o@example.com",
            manager_name="M", manager_email="m@example.com",
            monitoring_interval=1, timeout=1, retry_count=1, retry_delay=0,
        )
        db.session.add(row)
        rows.append(row)
    db.session.commit()
    return rows


def test_every_target_failing_at_once_opens_no_incidents(db, admin_user, app):
    """The signature of a blind monitor: everything fails in the same instant."""
    _make_apps(db, admin_user, 4)
    from monitoring.health_checker import run_monitoring_cycle

    with patch("app.services.monitoring_service.requests.get", side_effect=requests.exceptions.ConnectionError("network down")):
        with patch("app.services.notification_service.send_email") as mock_send:
            run_monitoring_cycle()

    assert Incident.query.count() == 0, "a blind monitor must not invent an estate-wide outage"
    assert not mock_send.called, "and must not email about it"


def test_a_single_real_outage_still_opens_an_incident(db, admin_user, app):
    """The guard must not swallow genuine failures - only correlated ones."""
    rows = _make_apps(db, admin_user, 4)
    from monitoring.health_checker import run_monitoring_cycle

    def one_bad(url, **kwargs):
        if "app0." in url:
            raise requests.exceptions.ConnectionError("this one really is down")
        return FakeResponse(200)

    with patch("app.services.monitoring_service.requests.get", side_effect=one_bad):
        with patch("app.services.notification_service.send_email"):
            run_monitoring_cycle()

    incidents = Incident.query.all()
    assert len(incidents) == 1, "one target down is an outage, not a monitoring gap"
    assert incidents[0].application_id == rows[0].id


def test_health_check_evidence_is_kept_even_when_suppressed(db, admin_user, app):
    """Suppress the conclusion, never the evidence."""
    _make_apps(db, admin_user, 4)
    from monitoring.health_checker import run_monitoring_cycle
    from app.models.health_check import HealthCheck

    with patch("app.services.monitoring_service.requests.get", side_effect=requests.exceptions.ConnectionError("network down")):
        with patch("app.services.notification_service.send_email"):
            run_monitoring_cycle()

    checks = HealthCheck.query.all()
    assert len(checks) == 4, "results must still be recorded for troubleshooting"
    assert all(c.success is False for c in checks)
