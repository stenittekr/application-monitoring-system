"""Incident alert email can be switched off without stopping monitoring.

On 31 August a weekend of held mail arrived in one burst on Monday morning,
most of it about a database that was never down. Quiet days *hold* and deliver
later, which is why. This switch discards instead, so turning it back on cannot
produce a flood.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.incident import Incident
from app.models.notification import Notification
from app.models.system_setting import SystemSetting
from app.services.notification_service import (_attempt_send, alerts_enabled,
                                               retry_failed_notifications)


@pytest.fixture
def alerts_off(db):
    db.session.add(SystemSetting(setting_key="incident_alerts_enabled", setting_value="false"))
    db.session.commit()


def _queued(db, kind="DOWN", status="PENDING"):
    now = datetime.now(timezone.utc)
    incident = Incident(status="OPEN", kind="REACHABILITY", reason="x",
                        started_at=now, detected_at=now)
    db.session.add(incident)
    db.session.commit()
    row = Notification(incident_id=incident.id, notification_type=kind,
                       recipient="stenitte@awgtc.com", subject="s", body="b", status=status)
    db.session.add(row)
    db.session.commit()
    return row


def test_alerts_are_on_unless_switched_off(db):
    assert alerts_enabled() is True


def test_nothing_is_emailed_while_it_is_off(db, alerts_off):
    row = _queued(db)
    with patch("app.services.notification_service.send_email") as mock_send:
        _attempt_send(row, "b")
    assert not mock_send.called
    assert row.status == "SUPPRESSED"


def test_recovery_is_stopped_too(db, alerts_off):
    """Recovery normally always sends. "Down" and "restored" are one pair, and
    silencing half of it is worse than silencing both."""
    row = _queued(db, kind="RECOVERY")
    with patch("app.services.notification_service.send_email") as mock_send:
        _attempt_send(row, "b")
    assert not mock_send.called
    assert row.status == "SUPPRESSED"


def test_a_paused_queue_cannot_flood_later(db, alerts_off):
    """The 31 August failure: held mail delivered all at once when it resumed."""
    for _ in range(5):
        _queued(db)
    with patch("app.services.notification_service.send_email") as mock_send:
        retry_failed_notifications()
    assert not mock_send.called
    assert Notification.query.filter_by(status="PENDING").count() == 0
    assert Notification.query.filter_by(status="SUPPRESSED").count() == 5


def test_incidents_are_still_recorded_while_alerts_are_off(db, alerts_off):
    """Switching off the email must not switch off the monitoring."""
    row = _queued(db)
    with patch("app.services.notification_service.send_email"):
        _attempt_send(row, "b")
    assert Incident.query.count() == 1, "the incident still exists on the dashboard"


def test_turning_it_back_on_sends_normally(db):
    db.session.add(SystemSetting(setting_key="incident_alerts_enabled", setting_value="true"))
    db.session.commit()
    row = _queued(db)
    with patch("app.services.notification_service.send_email") as mock_send:
        _attempt_send(row, "b")
    assert mock_send.called
