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
