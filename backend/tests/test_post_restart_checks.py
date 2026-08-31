"""A rebooted server is checked at once, not at its next scheduled interval.

§10 asks for a priority check after a restart. Without it, a machine that came
back missing a service waits up to a full interval before anyone finds out -
and PS_QAS has had a FeedBack App auto-start task failing since 18 August that
nothing reported.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.extensions import db
from app.services import server_service


def _boot(server, uptime_seconds):
    server_service.record_heartbeat(server, {"cpu_percent": 5, "uptime_seconds": uptime_seconds})


@pytest.fixture
def server(db):
    row, _ = server_service.enroll({"hostname": "REBOOTER", "owner_email": "ops@awgtc.com"})
    return row


def test_a_restart_queues_priority_checks(db, server):
    _boot(server, 100_000)                    # up for a day
    assert server.restart_pending_checks_at is None

    _boot(server, 30)                         # uptime reset: it rebooted
    assert server.restart_pending_checks_at is not None
    assert server_service.servers_awaiting_restart_checks() == [server]


def test_a_steady_server_never_queues_them(db, server):
    """Clock jitter moves the estimated boot time a little on every heartbeat.
    That must not read as a reboot, or every server is permanently rechecked."""
    _boot(server, 100_000)
    _boot(server, 100_060)
    _boot(server, 100_120)
    assert server.restart_pending_checks_at is None
    assert server_service.servers_awaiting_restart_checks() == []


def test_the_queue_clears_once_checked(db, server):
    _boot(server, 100_000)
    _boot(server, 30)
    server_service.clear_restart_checks(server)
    assert server.restart_pending_checks_at is None
    assert server_service.servers_awaiting_restart_checks() == []


def test_a_first_heartbeat_is_not_a_restart(db, server):
    """A newly enrolled agent has no previous boot time to compare against."""
    _boot(server, 500)
    assert server.restart_pending_checks_at is None
