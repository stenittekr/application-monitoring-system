"""The agent reports on itself (§7.1).

Everything else it sends describes the machine. Without this, the one component
nobody watches is the one doing the watching, and a silently degrading agent
looks exactly like a healthy one until it stops.
"""
import json

import pytest

from app.extensions import db
from app.services import server_service


@pytest.fixture
def server(db):
    row, _ = server_service.enroll({"hostname": "AGENTHOST", "owner_email": "ops@awgtc.com"})
    return row


def _beat(server, health):
    server_service.record_heartbeat(server, {"cpu_percent": 5, "agent_health": health})


def test_a_healthy_agent_reads_ok(db, server):
    _beat(server, {"queued_heartbeats": 0, "failed_heartbeats": 0, "agent_memory_mb": 42.0})
    assert server.agent_health_status == "OK"
    assert server.agent_health["agent_memory_mb"] == 42.0


def test_a_growing_queue_is_a_warning(db, server):
    """A queue that does not drain means heartbeats are kept, not delivered -
    while the one that got through still looks fine."""
    _beat(server, {"queued_heartbeats": 25, "failed_heartbeats": 25})
    assert server.agent_health_status == "WARNING"


def test_a_struggling_agent_is_never_critical(db, server):
    """A monitoring fault must not be able to present as a server outage."""
    _beat(server, {"queued_heartbeats": 500})
    assert server.agent_health_status != "CRITICAL"
    assert server.current_status == "UP"


def test_an_older_agent_is_unavailable_not_healthy(db, server):
    """Silence about health is not a clean bill of health."""
    server_service.record_heartbeat(server, {"cpu_percent": 5})
    assert server.agent_health_status == "UNAVAILABLE"
    assert server.agent_health_status != "OK"
