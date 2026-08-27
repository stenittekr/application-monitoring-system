"""Alerts about the monitoring machine itself stop at its owner.

The laptop running the platform raised 19 of the last 27 incidents - CPU spikes
on wake, missed heartbeats when it left the office. All real, all worth
recording, none of them a manager's problem.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.incident import Incident
from app.models.notification import Notification
from app.models.system_setting import SystemSetting
from app.services import server_service
from app.services.notification_service import _attempt_send


@pytest.fixture
def cc_list(db):
    db.session.add(SystemSetting(setting_key="alert_cc_recipients",
                                 setting_value="ajoy@awgtc.com, raam@awgtc.com"))
    db.session.commit()


def _server(db, hostname, owner_only):
    server, _ = server_service.enroll({"hostname": hostname, "owner_email": "stenitte@awgtc.com"})
    server.owner_only_alerts = owner_only
    db.session.commit()
    return server


def _notify(db, server):
    now = datetime.now(timezone.utc)
    incident = Incident(server_id=server.id, status="OPEN", kind="RESOURCE",
                        reason="CPU 100% >= critical 95%", started_at=now, detected_at=now)
    db.session.add(incident)
    db.session.commit()
    row = Notification(incident_id=incident.id, server_id=server.id, notification_type="DOWN",
                       recipient=server.owner_email, subject="s", body="b", status="PENDING")
    db.session.add(row)
    db.session.commit()
    with patch("app.services.notification_service.send_email") as mock_send:
        _attempt_send(row, "b")
    return row, mock_send


def test_the_monitoring_machine_does_not_copy_the_managers(db, cc_list):
    server = _server(db, "MONITOR-LAPTOP", owner_only=True)
    row, mock_send = _notify(db, server)
    assert mock_send.called, "its owner still needs to know"
    assert mock_send.call_args.kwargs.get("cc_addr") in (None, ""), "and nobody else does"
    assert row.cc in (None, "")


def test_a_real_server_still_copies_everyone(db, cc_list):
    server = _server(db, "PROD-SERVER", owner_only=False)
    row, mock_send = _notify(db, server)
    cc = mock_send.call_args.kwargs.get("cc_addr") or ""
    assert "ajoy@awgtc.com" in cc and "raam@awgtc.com" in cc


def test_the_flag_defaults_to_copying_everyone(db, cc_list):
    """A server nobody has classified must not go quiet by accident."""
    server, _ = server_service.enroll({"hostname": "NEW-SERVER", "owner_email": "stenitte@awgtc.com"})
    assert server.owner_only_alerts is False
    row, mock_send = _notify(db, server)
    assert "ajoy@awgtc.com" in (mock_send.call_args.kwargs.get("cc_addr") or "")
