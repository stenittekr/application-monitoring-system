"""Diagnosis reports which link in the chain broke (§19 diagnostics).

"DOWN" is a verdict. The chain is the answer: a name that does not resolve, a
port refusing connections and a page serving the wrong content are three
different problems with three different owners.
"""
import pytest

from app.models.application import Application
from app.extensions import db as _db
from app.services import diagnose_service, server_service


def _app(db, **kwargs):
    row = Application(name=kwargs.pop("name", "Thing"),
                      url=kwargs.pop("url", "http://127.0.0.1:9/"),
                      health_check_type=kwargs.pop("health_check_type", "HTTP"),
                      environment="QA", owner_name="o", owner_email="o@test",
                      manager_name="m", manager_email="m@test",
                      monitoring_enabled=True, monitoring_interval=60, timeout=2,
                      retry_count=1, retry_delay=0, expected_status_code=200,
                      current_status="UNKNOWN", **kwargs)
    db.session.add(row)
    db.session.commit()
    return row


def _states(result):
    return {step["step"]: step["state"] for step in result["steps"]}


def test_a_name_that_does_not_resolve_stops_the_chain_and_says_so(db):
    row = _app(db, url="http://no-such-host.invalid/")

    result = diagnose_service.diagnose(row)

    assert _states(result)["dns"] == "failed"
    assert "does not resolve" in result["steps"][-1]["detail"]
    # Nothing after DNS is attempted - a connection probe against a name that
    # does not resolve produces a second, misleading failure.
    assert "tcp" not in _states(result)


def test_a_refused_port_is_reported_as_nothing_listening(db):
    # Port 9 (discard) is reserved and closed on a normal machine.
    row = _app(db, url="http://127.0.0.1:9/")

    result = diagnose_service.diagnose(row)

    states = _states(result)
    assert states["dns"] == "ok"
    assert states["tcp"] == "failed"
    assert "not running" in result["steps"][-1]["detail"]


def test_an_application_with_no_recorded_server_says_what_is_missing(db):
    row = _app(db, url="http://127.0.0.1:9/")

    result = diagnose_service.diagnose(row)

    assert result["host"]["known"] is False
    assert "Hosted on" in result["host"]["detail"]


def test_a_reporting_agent_with_no_listener_proves_it_is_not_running(db):
    server, _ = server_service.enroll({"hostname": "DIAGHOST", "owner_email": "o@test"})
    server_service.record_heartbeat(server, {
        "cpu_percent": 1.0, "ram_percent": 1.0, "disk_percent": 1.0,
        "discovered_ports": [], "discovered_processes": [],
    })
    row = _app(db, url="http://127.0.0.1:9/", hosted_on_server_id=server.id)

    facts = diagnose_service.diagnose(row, server)["host"]

    assert facts["known"] is True
    assert facts["process"] is None
    # The distinction that matters: the agent is reporting, so "not running" is
    # a fact rather than an absence of information.
    assert "is not running" in facts["process_detail"]


def test_a_silent_agent_admits_it_does_not_know(db):
    server, _ = server_service.enroll({"hostname": "SILENTHOST", "owner_email": "o@test"})
    server.current_status = "AGENT_DOWN"
    _db.session.commit()
    row = _app(db, url="http://127.0.0.1:9/", hosted_on_server_id=server.id)

    facts = diagnose_service.diagnose(row, server)["host"]

    assert "unknown" in facts["process_detail"]


def test_a_database_check_is_not_walked_as_a_url(db):
    row = _app(db, health_check_type="DATABASE",
               url="mssql+pyodbc://user:pw@host/db?driver=ODBC+Driver+17")

    result = diagnose_service.diagnose(row)

    assert _states(result) == {"target": "skipped"}
