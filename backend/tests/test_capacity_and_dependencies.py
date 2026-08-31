"""Growth rate, clock skew and dependency suppression.

A static threshold says a disk is 85% full. It cannot say whether that took two
years or two days, and those need different responses. §19 asks for the rate
because the warning that matters arrives before the threshold does.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import requests

from app.extensions import db
from app.models.incident import Incident
from app.models.server_metric import ServerMetric
from app.services import capacity_service, server_service
from app.services.monitoring_service import failed_dependency, run_health_check


def _readings(db, server, points):
    """points = [(days_ago, disk_percent), ...]"""
    now = datetime.now(timezone.utc)
    for days_ago, percent in points:
        db.session.add(ServerMetric(server_id=server.id, disk_percent=percent,
                                    disk_total_gb=200.0,
                                    recorded_at=now - timedelta(days=days_ago)))
    db.session.commit()


@pytest.fixture
def server(db):
    row, _ = server_service.enroll({"hostname": "CAPHOST", "owner_email": "ops@awgtc.com"})
    row.disk_percent = 83.8
    db.session.commit()
    return row


# ---- capacity forecast ----------------------------------------------------

def test_a_steady_climb_produces_a_date(db, server):
    """PS_QAS went 82.0 -> 83.8 in four days. That is the useful number."""
    _readings(db, server, [(4, 82.0), (0, 83.8)])
    forecast = capacity_service.disk_forecast(server)
    assert forecast["growth_percent_per_day"] == pytest.approx(0.45, abs=0.02)
    assert forecast["days_until_full"] == pytest.approx(36, abs=2)
    assert "full_on" in forecast


def test_a_flat_disk_gets_no_forecast(db, server):
    """"Never fills" is a promise. Saying nothing is the honest answer."""
    _readings(db, server, [(10, 60.0), (0, 60.01)])
    assert capacity_service.disk_forecast(server)["days_until_full"] is None


def test_a_shrinking_disk_gets_no_forecast(db, server):
    _readings(db, server, [(10, 70.0), (0, 55.0)])
    assert capacity_service.disk_forecast(server)["days_until_full"] is None


def test_too_little_history_refuses_to_guess(db, server):
    """Two readings an hour apart say nothing about a fortnight."""
    _readings(db, server, [(0, 80.0)])
    assert capacity_service.disk_forecast(server) is None


def test_readings_are_kept_at_most_hourly(db, server):
    now = datetime.now(timezone.utc)
    assert capacity_service.record_disk_reading(server, now) is not None
    assert capacity_service.record_disk_reading(server, now + timedelta(minutes=5)) is None
    assert capacity_service.record_disk_reading(server, now + timedelta(hours=2)) is not None
    assert ServerMetric.query.count() == 2


# ---- clock skew -----------------------------------------------------------

def test_a_wrong_agent_clock_is_recorded(db, server):
    ahead = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    server_service.record_heartbeat(server, {"cpu_percent": 5, "agent_time": ahead})
    assert server.clock_skew_seconds > 10000
    assert server.clock_is_trustworthy is False


def test_a_normal_clock_is_trusted(db, server):
    server_service.record_heartbeat(
        server, {"cpu_percent": 5, "agent_time": datetime.now(timezone.utc).isoformat()})
    assert abs(server.clock_skew_seconds) < 120
    assert server.clock_is_trustworthy is True


def test_an_agent_that_reports_no_time_is_not_accused(db, server):
    """Older agents send nothing. Absent is not the same as wrong."""
    server_service.record_heartbeat(server, {"cpu_percent": 5})
    assert server.clock_skew_seconds is None
    assert server.clock_is_trustworthy is True


# ---- dependency suppression ----------------------------------------------

def _down(db, app_row):
    now = datetime.now(timezone.utc)
    db.session.add(Incident(application_id=app_row.id, status="OPEN", kind="REACHABILITY",
                            reason="down", started_at=now, detected_at=now))
    db.session.commit()


def test_a_child_of_a_failed_dependency_does_not_alert_separately(db, sample_application):
    """When a database dies, every application on it fails within a minute. The
    second, third and fourth emails carry nothing the first did not."""
    from app.models.application import Application
    database = Application(name="Shared DB", url="http://db.local", environment="Production", owner_name="Owner", manager_name="Mgr", manager_email="m@a.com",
                           owner_email="o@a.com", monitoring_enabled=True, monitoring_interval=60,
                           timeout=5, retry_count=1, retry_delay=0, expected_status_code=200,
                           current_status="DOWN")
    db.session.add(database)
    db.session.commit()
    _down(db, database)

    sample_application.depends_on = [database.id]
    db.session.commit()
    assert failed_dependency(sample_application).name == "Shared DB"

    boom = requests.exceptions.ConnectTimeout("timed out")
    with patch("app.services.monitoring_service.requests.get", side_effect=boom):
        with patch("app.services.notification_service.send_email") as mock_send:
            for _ in range(3):
                run_health_check(sample_application)

    assert sample_application.current_status == "DOWN", "the outage is still recorded"
    assert Incident.query.filter_by(application_id=sample_application.id).count() == 0
    assert not mock_send.called, "the alert for the cause already went out"


def test_a_healthy_dependency_does_not_suppress_anything(db, sample_application):
    from app.models.application import Application
    healthy = Application(name="Something Fine", url="http://ok.local", environment="Production", owner_name="Owner", manager_name="Mgr", manager_email="m@a.com",
                          owner_email="o@a.com", monitoring_enabled=True, monitoring_interval=60,
                          timeout=5, retry_count=1, retry_delay=0, expected_status_code=200,
                          current_status="UP")
    db.session.add(healthy)
    db.session.commit()
    sample_application.depends_on = [healthy.id]
    db.session.commit()
    assert failed_dependency(sample_application) is None


# --------------------------------------------------------------------------
# A server is as full as its fullest disk.
#
# PS_QAS reported 88% and a warning. That was C:. It also had an E: with 129 GB
# free, which nothing mentioned - and had the two been the other way round,
# nothing would have mentioned that either.
# --------------------------------------------------------------------------
import json


def _volumes(db, server, volumes):
    server.disk_volumes_json = json.dumps(volumes)
    db.session.commit()


def test_the_fullest_volume_is_the_one_that_counts(db, server):
    server.disk_percent = 40.0
    _volumes(db, server, [
        {"mount": "C:\\", "fstype": "NTFS", "total_gb": 200.0, "used_percent": 40.0},
        {"mount": "D:\\", "fstype": "NTFS", "total_gb": 500.0, "used_percent": 96.0},
    ])
    assert server.worst_disk_percent == 96.0
    assert server.fullest_volume["mount"] == "D:\\"
    assert server_service.resource_flags(server)["disk"] == "CRITICAL"


def test_a_roomy_second_volume_does_not_mask_a_full_system_drive(db, server):
    """The PS_QAS shape: C: nearly full, E: nearly empty. The warning stands."""
    server.disk_percent = 88.0
    _volumes(db, server, [
        {"mount": "C:\\", "fstype": "NTFS", "total_gb": 200.7, "used_percent": 87.5},
        {"mount": "E:\\", "fstype": "NTFS", "total_gb": 200.5, "used_percent": 35.7},
    ])
    assert server.worst_disk_percent == 88.0
    assert server_service.resource_flags(server)["disk"] == "WARNING"


def test_an_older_agent_falls_back_to_the_system_drive(db, server):
    """Agents below v0.7.0 report no volumes. That must not read as 0% free."""
    server.disk_percent = 97.0
    server.disk_volumes_json = None
    db.session.commit()
    assert server.worst_disk_percent == 97.0          # not None, and not zero
    assert server_service.resource_flags(server)["disk"] == "CRITICAL"
