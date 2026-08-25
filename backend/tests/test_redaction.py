"""Requirements §14/§18: secrets must not reach storage, email, logs or webhooks.

Two real leaks in this codebase had the same shape - a value that was correct to
use got formatted into a message that was then persisted and mailed. These pin
the general defence rather than the two specific call sites that were patched.
"""
from app.utils.redaction import redact


def test_connection_string_password_is_masked():
    text = "connect failed: mssql+pyodbc://awgtcps:Awgt@2020@162.20.20.250,1433/master"
    out = redact(text)
    assert "Awgt@2020" not in out
    assert "162.20.20.250" in out, "the host is diagnostic information and must survive"


def test_named_secret_parameters_are_masked():
    for text in ("password=hunter2", "Token: abc123def456", "api_key = zzzz9999",
                 "PWD=S#a#p#2024;UID=sap"):
        out = redact(text)
        assert "hunter2" not in out
        assert "abc123def456" not in out
        assert "zzzz9999" not in out
        assert "S#a#p#2024" not in out


def test_bearer_tokens_and_agent_tokens_are_masked():
    token = "949521d9a0bee00f4d74cf0f38fa92ff094aafadb76a78bad2d46c542add5911"
    assert token not in redact(f"heartbeat rejected for token {token}")
    assert "eyJhbGciOiJIUzI1NiJ9" not in redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9")


def test_environment_secrets_are_masked_by_value(monkeypatch):
    """The strongest rule: whatever is in .env under a secret-ish name never
    appears in output, however it got into the string."""
    monkeypatch.setenv("DB_SOMETHING_PASSWORD", "Tr0ub4dor&3")
    assert "Tr0ub4dor&3" not in redact("driver said: login failed for Tr0ub4dor&3")


def test_short_values_are_not_scrubbed(monkeypatch):
    """Blanking every short env value would destroy ordinary messages."""
    monkeypatch.setenv("SOME_KEY", "1")
    assert redact("check 1 of 3 failed") == "check 1 of 3 failed"


def test_redact_is_safe_on_none_and_non_strings():
    assert redact(None) is None
    assert redact(500) == "500"


def test_a_failed_check_stores_a_redacted_error(db, sample_application):
    """End to end: the message that lands on the health check row is clean."""
    from unittest.mock import patch
    import requests
    from app.models.health_check import HealthCheck
    from app.services.monitoring_service import run_health_check

    boom = requests.exceptions.ConnectionError("refused for https://svc:S3cretPassw0rd@internal/api")
    with patch("app.services.monitoring_service.requests.get", side_effect=boom):
        with patch("app.services.notification_service.send_email"):
            run_health_check(sample_application)

    stored = HealthCheck.query.order_by(HealthCheck.id.desc()).first()
    assert "S3cretPassw0rd" not in (stored.error_message or "")
