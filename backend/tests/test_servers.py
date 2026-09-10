from unittest.mock import patch

from app.models.activity_log import ActivityLog
from app.services import server_service


def _enroll(db):
    server, token = server_service.enroll({"hostname": "test-server"})
    return server


def _restart_logged(server):
    return ActivityLog.query.filter_by(
        action="SERVER_RESTART_DETECTED", entity_type="Server", entity_id=server.id
    ).count()


def test_second_heartbeat_does_not_crash(db):
    """Regression test: a real bug crashed record_heartbeat() on the SECOND
    heartbeat for a server (naive vs. timezone-aware datetime subtraction in
    _detect_restart), which every test up to now missed because none of them
    sent more than one heartbeat for the same server."""
    server = _enroll(db)
    server_service.record_heartbeat(server, {"uptime_seconds": 1000})
    # The second call is what actually exercises the last_boot_at comparison.
    server_service.record_heartbeat(server, {"uptime_seconds": 1010})
    assert server.current_status == "UP"


def test_restart_is_detected_on_uptime_reset(db):
    """A large drop in reported uptime between heartbeats means the server
    actually rebooted - this must be recorded, not crash or go unnoticed."""
    server = _enroll(db)
    server_service.record_heartbeat(server, {"uptime_seconds": 100_000})
    server_service.record_heartbeat(server, {"uptime_seconds": 30})  # uptime reset = reboot
    assert _restart_logged(server) == 1


def test_stable_uptime_across_heartbeats_is_not_a_restart(db):
    """Small jitter in reported uptime (clock skew, measurement timing) must
    not be misread as a restart."""
    server = _enroll(db)
    server_service.record_heartbeat(server, {"uptime_seconds": 5000})
    server_service.record_heartbeat(server, {"uptime_seconds": 5061})  # +61s wall time, ~normal jitter
    assert _restart_logged(server) == 0


def test_re_enrolling_a_hostname_reuses_the_row_and_rotates_the_token(db):
    """An agent reinstall must not leave a phantom duplicate on the dashboard."""
    from app.services import server_service

    first, token1 = server_service.enroll({
        "hostname": "AWGTC-PORTAL-QAS", "ip_address": "172.50.35.75",
        "owner_email": "ops@awgtc.com", "agent_version": "0.2.0",
    })
    # Agent reinstall: self-enrols with no owner fields, different case.
    second, token2 = server_service.enroll({
        "hostname": "awgtc-portal-qas", "agent_version": "0.3.0",
    })

    assert second.id == first.id, "re-enrol must reuse the existing server row"
    assert token2 != token1, "token must be rotated"
    assert server_service.verify_token(second, token2)
    assert not server_service.verify_token(second, token1), "old token must stop working"
    assert second.agent_version == "0.3.0"
    # Blanking this would silently stop the server's DOWN emails.
    assert second.owner_email == "ops@awgtc.com"
    assert len(server_service.list_servers()) == 1


def test_deleted_server_re_enrolls_as_a_new_row(db):
    from app.services import server_service

    from datetime import datetime, timezone

    original, _ = server_service.enroll({"hostname": "OLD-BOX"})
    original.deleted_at = datetime.now(timezone.utc)  # no delete endpoint yet; set directly
    db.session.commit()
    fresh, _ = server_service.enroll({"hostname": "OLD-BOX"})

    assert fresh.id != original.id, "a deliberately deleted server should not be revived"


def _server_with(db, **metrics):
    """Enrols a server and reports the given metrics until any breach is
    sustained - a single sample no longer counts, by design."""
    from app.services import server_service
    server, _ = server_service.enroll({"hostname": "THRESH-BOX", "owner_email": "ops@awgtc.com"})
    for _ in range(server_service.RESOURCE_BREACHES_TO_OPEN):
        server_service.record_heartbeat(server, {"uptime_seconds": 100, **metrics})
    return server


def test_disk_over_critical_opens_a_resource_incident(db):
    from app.services import incident_service

    with patch("app.services.server_service.notification_service.send_server_down_notification") as mock_alert:
        server = _server_with(db, cpu_percent=5, ram_percent=10, disk_percent=97)

    incident = incident_service.get_active_incident(server_id=server.id, kind="RESOURCE")
    assert incident is not None
    assert "DISK 97%" in incident.reason
    assert mock_alert.called, "a critical breach must notify"
    # The server is reachable - it must NOT also be marked unreachable.
    assert incident_service.get_active_incident(server_id=server.id, kind="REACHABILITY") is None
    assert server.current_status == "UP"


def test_warning_breach_does_not_email(db):
    from app.services import incident_service

    with patch("app.services.server_service.notification_service.send_server_down_notification") as mock_alert:
        server = _server_with(db, cpu_percent=5, ram_percent=10, disk_percent=88)

    assert incident_service.get_active_incident(server_id=server.id, kind="RESOURCE") is not None
    assert not mock_alert.called, "a warning is dashboard-only; emailing it causes alert fatigue"


def test_resource_incident_is_not_reopened_or_respammed(db):
    from app.services import server_service, incident_service

    with patch("app.services.server_service.notification_service.send_server_down_notification") as mock_alert:
        server = _server_with(db, cpu_percent=5, ram_percent=10, disk_percent=97)
        for _ in range(3):
            server_service.record_heartbeat(server, {"uptime_seconds": 200, "cpu_percent": 5,
                                                     "ram_percent": 10, "disk_percent": 97})
    assert mock_alert.call_count == 1, "one alert per condition, not one per heartbeat"

    # Recovery needs the same sustained evidence as the breach did.
    with patch("app.services.server_service.notification_service.send_server_recovery_notification"):
        for _ in range(server_service.RESOURCE_CLEARS_TO_CLOSE):
            server_service.record_heartbeat(server, {"uptime_seconds": 300, "cpu_percent": 5,
                                                     "ram_percent": 10, "disk_percent": 40})
    assert incident_service.get_active_incident(server_id=server.id, kind="RESOURCE") is None


def test_uncollected_metric_is_never_treated_as_healthy(db):
    from app.services import incident_service
    # disk_percent absent entirely - "not available", which must not pass as OK
    # and must not be read as 0%.
    server = _server_with(db, cpu_percent=5, ram_percent=10)
    assert server.disk_percent is None
    assert incident_service.get_active_incident(server_id=server.id, kind="RESOURCE") is None


def test_stale_heartbeat_is_not_reported_as_up(db):
    from datetime import datetime, timedelta, timezone
    server = _server_with(db, cpu_percent=5, ram_percent=10, disk_percent=20)
    assert server.to_dict()["current_status"] == "UP"

    server.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(
        seconds=server.heartbeat_interval_seconds * 3)
    db.session.commit()

    payload = server.to_dict()
    assert payload["is_stale"] is True
    assert payload["current_status"] == "STALE", "an unreporting server must not still read UP"
    assert payload["reported_status"] == "UP", "the raw last-known status stays available"


def test_a_cpu_spike_does_not_open_an_incident(db):
    """A machine waking from sleep hits 100% CPU for a moment. That is not a
    condition - alerting on it produced ten incidents in ninety minutes."""
    from app.services import server_service, incident_service

    server, _ = server_service.enroll({"hostname": "SPIKE-BOX", "owner_email": "ops@awgtc.com"})
    with patch("app.services.server_service.notification_service.send_server_down_notification") as mock_alert:
        server_service.record_heartbeat(server, {"cpu_percent": 100, "ram_percent": 10, "disk_percent": 10})
        server_service.record_heartbeat(server, {"cpu_percent": 12, "ram_percent": 10, "disk_percent": 10})

    assert incident_service.get_active_incident(server_id=server.id, kind="RESOURCE") is None
    assert not mock_alert.called


def test_sustained_pressure_still_opens_one_incident(db):
    from app.services import server_service, incident_service

    server, _ = server_service.enroll({"hostname": "SUSTAINED-BOX", "owner_email": "ops@awgtc.com"})
    with patch("app.services.server_service.notification_service.send_server_down_notification") as mock_alert:
        for _ in range(5):
            server_service.record_heartbeat(server, {"cpu_percent": 99, "ram_percent": 10, "disk_percent": 10})

    assert incident_service.get_active_incident(server_id=server.id, kind="RESOURCE") is not None
    assert mock_alert.call_count == 1, "sustained pressure alerts once, not once per heartbeat"


def _heartbeat_with(server, services=(), processes=()):
    from app.services import server_service
    server_service.record_heartbeat(server, {
        "uptime_seconds": 100, "cpu_percent": 5, "ram_percent": 5, "disk_percent": 5,
        "discovered_services": [{"name": n, "display_name": n, "status": st} for n, st in services],
        "discovered_processes": [{"name": n, "pid": 1, "memory_mb": 1, "script": None} for n in processes],
    })


def test_a_stopped_service_raises_a_component_incident(db):
    """Acceptance criterion 5: a stopped service must be detectable, and must
    read differently from a failed URL."""
    from app.services import server_service, incident_service

    server, _ = server_service.enroll({"hostname": "SVC-BOX", "owner_email": "ops@awgtc.com"})
    server_service.set_expected_components(server, ["MSSQLSERVER"], [])

    with patch("app.services.server_service.notification_service.send_server_down_notification") as alert:
        _heartbeat_with(server, services=[("MSSQLSERVER", "running")])
        assert incident_service.get_active_incident(server_id=server.id, kind="COMPONENT") is None

        # Service stops. One heartbeat is a restart; two is a problem.
        _heartbeat_with(server, services=[("MSSQLSERVER", "stopped")])
        assert incident_service.get_active_incident(server_id=server.id, kind="COMPONENT") is None
        _heartbeat_with(server, services=[("MSSQLSERVER", "stopped")])

    incident = incident_service.get_active_incident(server_id=server.id, kind="COMPONENT")
    assert incident is not None
    assert "MSSQLSERVER is STOPPED" in incident.reason
    assert alert.called
    # The server itself is reachable - this must not read as an outage.
    assert server.current_status == "UP"
    assert incident_service.get_active_incident(server_id=server.id, kind="REACHABILITY") is None


def test_a_missing_service_reads_differently_from_a_stopped_one(db):
    from app.services import server_service

    server, _ = server_service.enroll({"hostname": "GONE-BOX", "owner_email": "ops@awgtc.com"})
    server_service.set_expected_components(server, ["DMS"], [])
    _heartbeat_with(server, services=[("SomethingElse", "running")])

    states = {c["name"]: c["state"] for c in server.component_status}
    assert states["DMS"] == "MISSING", "uninstalled or renamed is not the same as stopped"


def test_expected_process_missing_is_detected(db):
    from app.services import server_service

    server, _ = server_service.enroll({"hostname": "PROC-BOX", "owner_email": "ops@awgtc.com"})
    server_service.set_expected_components(server, [], ["python.exe"])
    _heartbeat_with(server, processes=["chrome.exe"])
    assert [c["state"] for c in server.component_status] == ["MISSING"]

    _heartbeat_with(server, processes=["python.exe", "chrome.exe"])
    assert [c["state"] for c in server.component_status] == ["OK"]


def test_component_incident_resolves_when_the_service_returns(db):
    from app.services import server_service, incident_service

    server, _ = server_service.enroll({"hostname": "BACK-BOX", "owner_email": "ops@awgtc.com"})
    server_service.set_expected_components(server, ["MSSQLSERVER"], [])
    with patch("app.services.server_service.notification_service.send_server_down_notification"):
        for _ in range(2):
            _heartbeat_with(server, services=[("MSSQLSERVER", "stopped")])
    assert incident_service.get_active_incident(server_id=server.id, kind="COMPONENT") is not None

    with patch("app.services.server_service.notification_service.send_server_recovery_notification"):
        for _ in range(2):
            _heartbeat_with(server, services=[("MSSQLSERVER", "running")])
    assert incident_service.get_active_incident(server_id=server.id, kind="COMPONENT") is None


def test_no_expected_components_means_no_checking(db):
    """A server nobody has configured must not start alerting on its own."""
    from app.services import server_service, incident_service

    server, _ = server_service.enroll({"hostname": "QUIET-BOX", "owner_email": "ops@awgtc.com"})
    for _ in range(3):
        _heartbeat_with(server, services=[("Anything", "stopped")])
    assert server.component_status == []
    assert incident_service.get_active_incident(server_id=server.id, kind="COMPONENT") is None


def test_the_agent_reports_which_databases_a_process_is_connected_to(db):
    """Observed connections, stored and served (FR-011, §8).

    The point is the pid: it is what joins a listening application to the
    database sockets its own process is holding open.
    """
    server, _ = server_service.enroll({"hostname": "DBLINKHOST", "owner_email": "ops@awgtc.com"})
    server_service.record_heartbeat(server, {
        "cpu_percent": 5.0, "ram_percent": 40.0, "disk_percent": 50.0,
        "discovered_ports": [{"port": 3301, "protocol": "TCP", "pid": 4242,
                              "process_name": "python.exe"}],
        "database_links": [{"pid": 4242, "process_name": "python.exe", "local_port": 51544,
                            "remote_host": "162.20.20.250", "remote_port": 1433,
                            "engine": "SQL Server", "connections": 4}],
    })

    link = server.to_dict()["database_links"][0]
    assert link["pid"] == 4242
    assert link["engine"] == "SQL Server"
    assert link["remote_port"] == 1433
    # The listening port and the outbound local port are different things, and
    # confusing them is what made the first version of this find nothing.
    assert link["local_port"] != 3301
