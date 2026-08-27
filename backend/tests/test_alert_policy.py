"""Not every alert deserves the same interruption.

Sixty emails went out in one week. Most were resource warnings and repeats,
and several arrived overnight for things nobody could act on until morning.
An alert nobody can act on now is not information, it is interruption.
"""
from datetime import datetime, time, timezone
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.incident import Incident
from app.models.notification import Notification
from app.models.system_setting import SystemSetting
from app.services import alert_policy
from app.services.notification_service import send_daily_digest


def _incident(kind="REACHABILITY", reason=""):
    return Incident(kind=kind, reason=reason, status="OPEN",
                    started_at=datetime.now(timezone.utc), detected_at=datetime.now(timezone.utc))


class Thing:
    """Stands in for an application or server."""
    def __init__(self, environment=None, criticality=None, support_hours=None):
        self.environment, self.criticality, self.support_hours = environment, criticality, support_hours


# ---- severity -------------------------------------------------------------

def test_a_resource_warning_is_low_and_a_critical_one_is_not(db):
    assert alert_policy.severity_of(_incident("RESOURCE", "DISK 82% >= warning 75%")) == alert_policy.LOW
    assert alert_policy.severity_of(_incident("RESOURCE", "CPU 99% >= critical 95%")) == alert_policy.HIGH


def test_something_unreachable_in_production_is_critical(db):
    incident = _incident("REACHABILITY", "Health check failed")
    assert alert_policy.severity_of(incident, Thing(environment="Production")) == alert_policy.CRITICAL
    assert alert_policy.severity_of(incident, Thing(environment="Test")) == alert_policy.HIGH


def test_a_stopped_component_sits_between_the_two(db):
    assert alert_policy.severity_of(_incident("COMPONENT", "service X is stopped")) == alert_policy.MEDIUM


# ---- support hours --------------------------------------------------------

def test_24x7_is_always_in_hours(db):
    assert alert_policy.in_support_hours(Thing(support_hours="24x7"))
    assert alert_policy.in_support_hours(Thing())


def test_an_office_hours_window_is_respected(db):
    thing = Thing(support_hours="08:00-18:00")
    with patch("app.services.alert_policy.datetime") as clock:
        clock.now.return_value = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        assert alert_policy.in_support_hours(thing, datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)) is True


def test_an_unreadable_window_fails_open(db):
    """A typo in a schedule must not silence alerting."""
    assert alert_policy.in_support_hours(Thing(support_hours="whenever")) is True


# ---- routing --------------------------------------------------------------

def test_low_goes_to_the_digest_and_high_goes_out_now(db):
    assert alert_policy.route(alert_policy.LOW)[0] == alert_policy.DIGEST
    assert alert_policy.route(alert_policy.HIGH)[0] == alert_policy.EMAIL
    assert alert_policy.route(alert_policy.CRITICAL)[0] == alert_policy.EMAIL


def test_routing_can_be_changed_without_a_deploy(db):
    db.session.add(SystemSetting(setting_key="route_low", setting_value="EMAIL"))
    db.session.commit()
    assert alert_policy.route(alert_policy.LOW)[0] == alert_policy.EMAIL


def test_an_invalid_route_falls_back_to_sending(db):
    """A bad setting must not quietly stop alerts."""
    db.session.add(SystemSetting(setting_key="route_high", setting_value="banana"))
    db.session.commit()
    assert alert_policy.route(alert_policy.HIGH)[0] == alert_policy.EMAIL


# ---- the digest -----------------------------------------------------------

def _held(subject="[ALERT] something", recipient="stenitte@awgtc.com"):
    """A notification the policy held back. Notifications require an incident,
    so one is created for it."""
    incident = _incident("RESOURCE", "DISK 82% >= warning 75%")
    db.session.add(incident)
    db.session.commit()
    row = Notification(incident_id=incident.id, notification_type="DOWN", recipient=recipient,
                       subject=subject, body="b", status="DIGEST")
    db.session.add(row)
    db.session.commit()
    return row


def test_the_digest_sends_one_email_for_everything_held(db):
    for i in range(4):
        _held(f"[ALERT] thing {i}")
    with patch("app.services.notification_service.send_email") as mock_send:
        count = send_daily_digest(datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc))
    assert count == 4
    assert mock_send.call_count == 1, "four events, one email"
    body = mock_send.call_args[0][2]
    assert "4 monitoring event(s)" in body
    assert "thing 3" in body
    assert Notification.query.filter_by(status="DIGEST").count() == 0


def test_the_digest_does_not_send_twice_in_one_day(db):
    _held()
    with patch("app.services.notification_service.send_email"):
        send_daily_digest(datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc))
    _held()
    with patch("app.services.notification_service.send_email") as mock_send:
        send_daily_digest(datetime(2026, 8, 27, 17, 0, tzinfo=timezone.utc))
    assert not mock_send.called


def test_nothing_held_means_no_email_at_all(db):
    """A digest saying "nothing happened" is the noise this removes."""
    with patch("app.services.notification_service.send_email") as mock_send:
        assert send_daily_digest(datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)) == 0
    assert not mock_send.called
