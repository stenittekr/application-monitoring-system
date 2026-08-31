"""FR-006: additions, removals and version changes between discovery snapshots."""
from unittest.mock import patch

from app.models.server_change import ServerChange
from app.services import server_service


def _hb(server, services=(), programs=()):
    server_service.record_heartbeat(server, {
        "uptime_seconds": 100,
        "discovered_services": [{"name": n, "display_name": n, "status": st} for n, st in services],
        "discovered_programs": [{"name": n, "version": v, "publisher": None, "installed_on": None}
                                for n, v in programs],
    })


def test_first_snapshot_records_nothing(db):
    """A first heartbeat is a beginning, not 240 additions."""
    server, _ = server_service.enroll({"hostname": "NEW-BOX"})
    _hb(server, services=[("A", "running"), ("B", "stopped")], programs=[("Git", "2.45.1")])
    assert ServerChange.query.count() == 0


def test_added_and_removed_software_is_recorded(db):
    server, _ = server_service.enroll({"hostname": "SW-BOX"})
    _hb(server, programs=[("Git", "2.45.1"), ("7-Zip", "19.00")])
    _hb(server, programs=[("Git", "2.45.1"), ("Docker Desktop", "4.78.0")])

    changes = {(c.change_type, c.item_name) for c in ServerChange.query.all()}
    assert ("ADDED", "Docker Desktop") in changes
    assert ("REMOVED", "7-Zip") in changes
    assert ("ADDED", "Git") not in changes, "unchanged items must not be reported"


def test_a_version_upgrade_is_recorded_with_both_versions(db):
    server, _ = server_service.enroll({"hostname": "VER-BOX"})
    _hb(server, programs=[("Google Chrome", "151.0.7922.170")])
    _hb(server, programs=[("Google Chrome", "152.0.8000.10")])

    change = ServerChange.query.filter_by(change_type="CHANGED").one()
    assert change.item_name == "Google Chrome"
    assert change.old_value == "151.0.7922.170"
    assert change.new_value == "152.0.8000.10"


def test_a_service_starting_and_stopping_is_not_configuration_drift(db):
    """Windows starts and stops its own services constantly - WerSvc, DsmSvc,
    TrustedInstaller. Recording each transition produced 1,412 entries in
    nineteen days and buried the ten that mattered. FR-006 asks for additions,
    removals and version changes; a service doing what it was designed to do is
    none of those.

    Whether a service that *should* be running is running is a different
    question, answered by the component checks against a chosen watchlist."""
    server, _ = server_service.enroll({"hostname": "SVC-CHG"})
    _hb(server, services=[("MSSQLSERVER", "running")])
    _hb(server, services=[("MSSQLSERVER", "stopped")])

    assert ServerChange.query.filter_by(category="SERVICE").count() == 0


def test_a_service_appearing_or_disappearing_is_still_recorded(db):
    """Installed or uninstalled is real drift, and must survive the above."""
    server, _ = server_service.enroll({"hostname": "SVC-ADD"})
    _hb(server, services=[("MSSQLSERVER", "running")])
    _hb(server, services=[("MSSQLSERVER", "running"), ("NewThing", "running")])

    change = ServerChange.query.filter_by(category="SERVICE", change_type="ADDED").one()
    assert change.item_name == "NewThing"


def test_per_user_service_instances_are_ignored(db):
    """Windows names a per-user instance with a session suffix - cbdhsvc_26200e2f -
    which changes at every logon. Treated as installed services they produced 390
    additions and removals for services nobody touched."""
    server, _ = server_service.enroll({"hostname": "PER-USER"})
    _hb(server, services=[("cbdhsvc_26200e2f", "running")])
    _hb(server, services=[("cbdhsvc_130d63", "running")])

    assert ServerChange.query.filter_by(category="SERVICE").count() == 0


def test_a_quiet_server_produces_no_change_noise(db):
    """Identical snapshots must record nothing, or the log is useless."""
    server, _ = server_service.enroll({"hostname": "QUIET"})
    for _ in range(4):
        _hb(server, services=[("A", "running")], programs=[("Git", "2.45.1")])
    assert ServerChange.query.count() == 0
