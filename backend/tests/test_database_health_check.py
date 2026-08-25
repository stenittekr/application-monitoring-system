"""DATABASE health-check type: the SELECT 1 probe, and the credential scrubbing
that stops an expanded password reaching the incidents table or an alert email."""
import os

from app.services.monitoring_service import _perform_database_attempt


class FakeApp:
    """Only the fields _perform_database_attempt actually reads."""
    def __init__(self, url, timeout=3):
        self.url = url
        self.timeout = timeout
        self.health_check_type = "DATABASE"


def test_reachable_database_reports_up():
    result = _perform_database_attempt(FakeApp("sqlite://"))
    assert result["success"] is True
    assert result["status"] == "UP"
    assert result["error_message"] is None
    assert result["response_time"] >= 0


def test_unreachable_database_reports_down_without_leaking_the_password(monkeypatch):
    monkeypatch.setenv("TEST_DB_PASSWORD", "sup3rs3cr3t")
    # 192.0.2.0/24 is the reserved TEST-NET-1 block - guaranteed unroutable.
    app = FakeApp("mysql+pymysql://dms:${TEST_DB_PASSWORD}@192.0.2.1:3306/dms", timeout=2)

    result = _perform_database_attempt(app)

    assert result["success"] is False
    assert result["status"] == "DOWN"
    assert "Database connection failed" in result["error_message"]
    # The whole point: the driver echoes the DSN back, and this is stored in
    # incidents and emailed out, so the real password must not be in it.
    assert "sup3rs3cr3t" not in result["error_message"]


def test_missing_env_var_is_reported_not_silently_connected():
    os.environ.pop("NO_SUCH_DB_PASSWORD", None)
    # Unexpanded ${...} stays literal, so the connect must fail rather than
    # quietly succeeding against a wrong target.
    result = _perform_database_attempt(FakeApp("mysql+pymysql://u:${NO_SUCH_DB_PASSWORD}@192.0.2.2:3306/d", timeout=2))
    assert result["success"] is False
