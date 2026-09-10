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


def _server(db, hostname, scope):
    server, _ = server_service.enroll({"hostname": hostname, "owner_email": "stenitte@awgtc.com"})
    server.alert_scope = scope
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
    server = _server(db, "MONITOR-LAPTOP", "OWNER")
    row, mock_send = _notify(db, server)
    assert mock_send.called, "its owner still needs to know"
    assert mock_send.call_args.kwargs.get("cc_addr") in (None, ""), "and nobody else does"
    assert row.cc in (None, "")


def test_a_real_server_still_copies_everyone(db, cc_list):
    server = _server(db, "PROD-SERVER", "ALL")
    row, mock_send = _notify(db, server)
    cc = mock_send.call_args.kwargs.get("cc_addr") or ""
    assert "ajoy@awgtc.com" in cc and "raam@awgtc.com" in cc


def test_the_flag_defaults_to_copying_everyone(db, cc_list):
    """A server nobody has classified must not go quiet by accident."""
    server, _ = server_service.enroll({"hostname": "NEW-SERVER", "owner_email": "stenitte@awgtc.com"})
    assert server.alert_scope == "ALL"
    row, mock_send = _notify(db, server)
    assert "ajoy@awgtc.com" in (mock_send.call_args.kwargs.get("cc_addr") or "")


# --------------------------------------------------------------------------
# The platform cannot be unreachable from itself.
#
# On 27 August the monitor wrote "FUJALW-LAP-STENITTE is unreachable" into a
# log file on FUJALW-LAP-STENITTE. Its agent had missed one heartbeat while the
# machine was busy; the platform was running throughout, and completed ten
# cycles in the same window it declared the host unreachable.
# --------------------------------------------------------------------------
import socket
from datetime import timedelta

from app.services.server_service import check_missed_heartbeats, is_this_machine


def _silent_server(db, hostname):
    row, _ = server_service.enroll({"hostname": hostname, "owner_email": "stenitte@awgtc.com"})
    row.heartbeat_interval_seconds = 60
    row.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db.session.commit()
    return row


def test_the_platforms_own_host_is_never_declared_unreachable(db):
    server = _silent_server(db, socket.gethostname())
    assert is_this_machine(server)

    with patch("app.services.notification_service.send_email") as mock_send:
        check_missed_heartbeats()

    assert server.current_status == "AGENT_DOWN", "the gap is recorded"
    assert server.current_status != "DOWN", "but not as an outage"
    assert Incident.query.filter_by(server_id=server.id, kind="REACHABILITY").count() == 0
    assert not mock_send.called


def test_another_silent_server_still_alerts(db):
    server = _silent_server(db, "SOME-OTHER-BOX")
    assert not is_this_machine(server)

    with patch("app.services.notification_service.send_email") as mock_send:
        check_missed_heartbeats()

    assert server.current_status == "DOWN"
    assert mock_send.called


def test_an_incident_opened_before_this_rule_is_closed(db):
    """Incident #40 was open on exactly this mistaken premise."""
    server = _silent_server(db, socket.gethostname())
    now = datetime.now(timezone.utc)
    db.session.add(Incident(server_id=server.id, status="OPEN", kind="REACHABILITY",
                            reason="Missed heartbeat", started_at=now, detected_at=now))
    db.session.commit()

    with patch("app.services.notification_service.send_email") as mock_send:
        check_missed_heartbeats()

    incident = Incident.query.filter_by(server_id=server.id, kind="REACHABILITY").one()
    assert incident.status == "RESOLVED"
    assert incident.resolution_category == "False alarm - monitoring"
    assert not mock_send.called


def test_a_server_set_to_no_email_sends_nothing(db, cc_list):
    """Some weeks a machine is expected to misbehave and nobody needs telling."""
    server = _server(db, "NOISY-BOX", "NONE")
    row, mock_send = _notify(db, server)
    assert not mock_send.called
    assert row.status == "SUPPRESSED"
    assert Incident.query.filter_by(server_id=server.id).count() == 1, "still recorded"


def test_an_invalid_scope_is_rejected_rather_than_guessed(db):
    from app.models.server import Server
    assert "SOMETIMES" not in Server.ALERT_SCOPES
