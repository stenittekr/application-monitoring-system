"""FR-011 / layer 5: synthetic business transactions.

A URL returning 200 does not prove anyone can log in and do their job. These
cover the execution, and the rule that keeps test credentials out of the
profile text (§18).
"""
from unittest.mock import Mock, patch

import pytest

from app.services.workflow_service import _SESSIONS, run_workflow, validate_workflow


@pytest.fixture(autouse=True)
def _clean_session_cache():
    """Sessions persist between checks by design; they must not persist between tests."""
    _SESSIONS.clear()
    yield
    _SESSIONS.clear()


class FakeApp:
    id = 999          # sessions are cached per application id
    url = "https://portal.example.com"
    timeout = 10
    verify_ssl = True


LOGIN_FLOW = [
    {"name": "Login page", "method": "GET", "path": "/login", "expect_contains": "sign in"},
    {"name": "Sign in", "method": "POST", "path": "/login",
     "form": {"user": "svc_monitor", "password": "${SYN_PASSWORD}"}, "expect_status": 302},
    {"name": "Landing page", "method": "GET", "path": "/home", "expect_contains": "welcome"},
]


def _responses(*specs):
    """Builds a session whose request() returns each spec in turn."""
    made = [Mock(status_code=code, text=body) for code, body in specs]
    session = Mock()
    session.request.side_effect = made
    return session


def test_a_passing_workflow_reports_success(monkeypatch):
    monkeypatch.setenv("SYN_PASSWORD", "s3cret")
    session = _responses((200, "Please Sign In"), (302, ""), (200, "Welcome back"))
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        ok, message, elapsed = run_workflow(FakeApp(), LOGIN_FLOW)
    assert ok is True and message is None and elapsed >= 0


def test_a_failing_step_is_named(monkeypatch):
    """'Workflow failed' is not actionable; naming the step is."""
    monkeypatch.setenv("SYN_PASSWORD", "s3cret")
    session = _responses((200, "Please Sign In"), (401, "Invalid credentials"))
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        ok, message, _ = run_workflow(FakeApp(), LOGIN_FLOW)
    assert ok is False
    assert "Step 2 'Sign in'" in message
    assert "expected HTTP 302, got 401" in message


def test_a_200_that_is_secretly_broken_is_caught(monkeypatch):
    """The whole reason layer 5 exists: the site answers, but is unusable."""
    monkeypatch.setenv("SYN_PASSWORD", "s3cret")
    session = _responses((200, "Please Sign In"), (302, ""), (200, "Service temporarily unavailable"))
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        ok, message, _ = run_workflow(FakeApp(), LOGIN_FLOW)
    assert ok is False
    assert "Landing page" in message and "welcome" in message


def test_credentials_come_from_the_environment_not_the_profile(monkeypatch):
    monkeypatch.setenv("SYN_PASSWORD", "s3cret")
    session = _responses((200, "sign in"), (302, ""), (200, "welcome"))
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        run_workflow(FakeApp(), LOGIN_FLOW)
    posted = session.request.call_args_list[1].kwargs["data"]
    assert posted["password"] == "s3cret", "the reference must be resolved before sending"


def test_a_literal_password_in_a_workflow_is_rejected():
    """Stored profiles are displayed, exported and backed up (§18)."""
    errors = validate_workflow([
        {"name": "Sign in", "method": "POST", "path": "/login",
         "form": {"user": "svc", "password": "hunter2"}},
    ])
    assert any("environment variable" in e for e in errors)


def test_workflow_shape_is_validated():
    assert validate_workflow([]) == ["A workflow needs at least one step."]
    assert any("path must start with '/'" in e
               for e in validate_workflow([{"name": "x", "method": "GET", "path": "login"}]))
    assert any("method must be one of" in e
               for e in validate_workflow([{"name": "x", "method": "DELETE", "path": "/x"}]))
    assert any("needs a name" in e for e in validate_workflow([{"method": "GET", "path": "/x"}]))


def test_a_network_failure_is_reported_without_leaking_credentials(monkeypatch):
    import requests as real_requests
    monkeypatch.setenv("SYN_PASSWORD", "s3cret")
    session = Mock()
    session.request.side_effect = real_requests.exceptions.ConnectionError(
        "refused for https://svc:s3cret@portal.example.com/login")
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        ok, message, _ = run_workflow(FakeApp(), LOGIN_FLOW)
    assert ok is False
    assert "s3cret" not in message


# --- Session reuse, driven by the target application's real limits ---------
#     sessions expire after 600s idle · 10 login failures / 300s per IP ·
#     every login writes an audit row · 500s return a generic message.

LOGIN_FLOW_WITH_MARKER = [
    {"name": "Sign in", "method": "POST", "path": "/", "login": True,
     "form": {"username": "svc_monitor", "password": "${SYN_PASSWORD}"},
     "expect_contains": "dashboard"},
    {"name": "Home", "method": "GET", "path": "/home", "expect_contains": "dashboard"},
]


def test_a_second_check_does_not_log_in_again(monkeypatch):
    """288 logins a day would be 288 audit rows a day, per workflow."""
    monkeypatch.setenv("SYN_PASSWORD", "s3cret")
    session = Mock()
    session.request.return_value = Mock(status_code=200, text="Dashboard")
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        run_workflow(FakeApp(), LOGIN_FLOW_WITH_MARKER)
        first = session.request.call_count
        run_workflow(FakeApp(), LOGIN_FLOW_WITH_MARKER)
        second = session.request.call_count - first

    assert first == 2, "the first check logs in and then verifies"
    assert second == 1, "the second reuses the session and only verifies"


def test_a_dropped_session_triggers_one_re_login(monkeypatch):
    """Being bounced to the login page is not an outage."""
    monkeypatch.setenv("SYN_PASSWORD", "s3cret")
    good = Mock(status_code=200, text="Dashboard")
    session = Mock()
    session.request.return_value = good
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        run_workflow(FakeApp(), LOGIN_FLOW_WITH_MARKER)          # establishes a session
        session.request.return_value = Mock(status_code=401, text="Please sign in")
        session.request.side_effect = None
        # Verify fails as a session loss, then the full flow runs; still failing
        # here, but the important part is that it retried with a login.
        before = session.request.call_count
        ok, message, _ = run_workflow(FakeApp(), LOGIN_FLOW_WITH_MARKER)
        attempts = session.request.call_count - before

    assert ok is False
    assert attempts >= 2, "a session loss must be retried with a fresh login"


def test_repeated_login_failures_stop_before_the_rate_limit(monkeypatch):
    """The target allows 10 failures / 300s. An expired service-account password
    must not burn through that and lock the monitor out of its own recovery."""
    monkeypatch.setenv("SYN_PASSWORD", "wrong")
    session = Mock()
    session.request.return_value = Mock(status_code=401, text="Invalid username or password")
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        for _ in range(3):
            run_workflow(FakeApp(), LOGIN_FLOW_WITH_MARKER)
        attempts_before = session.request.call_count
        ok, message, _ = run_workflow(FakeApp(), LOGIN_FLOW_WITH_MARKER)

    assert ok is False
    assert session.request.call_count == attempts_before, "no request may be sent during cooldown"
    assert "Login paused" in message
    assert "password" in message.lower(), "the message must say what to check"


def test_a_stale_session_is_not_reused(monkeypatch):
    """Sessions expire after 600s idle; reusing one past that just fails oddly."""
    import app.services.workflow_service as ws
    monkeypatch.setenv("SYN_PASSWORD", "s3cret")
    session = Mock()
    session.request.return_value = Mock(status_code=200, text="Dashboard")
    with patch("app.services.workflow_service.requests.Session", return_value=session):
        run_workflow(FakeApp(), LOGIN_FLOW_WITH_MARKER)
        # Age the cached session past the inactivity window.
        ws._SESSIONS[FakeApp.id]["last_used"] -= (ws.SESSION_MAX_IDLE_SECONDS + 1)
        before = session.request.call_count
        run_workflow(FakeApp(), LOGIN_FLOW_WITH_MARKER)
        attempts = session.request.call_count - before

    assert attempts == 2, "an expired session must log in again rather than be reused"


def test_a_workflow_without_a_login_step_is_warned_about():
    from app.services.workflow_service import workflow_warnings
    assert workflow_warnings(LOGIN_FLOW_WITH_MARKER) == []
    warnings = workflow_warnings([{"name": "Ping", "method": "GET", "path": "/health"}])
    assert warnings and "login step" in warnings[0]


def test_a_workflow_survives_a_save_and_reload(db, admin_user):
    """The editor posts steps; they must come back the same shape."""
    from app.services import application_service

    steps = [
        {"name": "Login page", "method": "GET", "path": "/", "expect_contains": "sign in"},
        {"name": "Sign in", "method": "POST", "path": "/", "login": True,
         "form": {"username": "svc_monitor", "password": "${SYN_PS_PASSWORD}"},
         "expect_contains": "dashboard"},
    ]
    row = application_service.create_application(
        {"name": "Portal workflow", "url": "https://ps.example.com", "health_check_type": "WORKFLOW",
         "owner_email": "o@example.com", "manager_email": "m@example.com",
         "owner_name": "O", "manager_name": "M", "workflow_steps": steps},
        {"interval": 300, "timeout": 10, "retry_count": 2, "retry_delay": 3},
    )
    assert row.workflow_steps == steps

    application_service.update_application(row, {"workflow_steps": steps[:1]})
    assert len(row.workflow_steps) == 1

    # An update that does not mention workflow_steps must leave them alone.
    application_service.update_application(row, {"description": "renamed"})
    assert len(row.workflow_steps) == 1


def test_the_api_rejects_a_workflow_with_a_literal_password(client, admin_headers):
    response = client.post("/api/applications", headers=admin_headers, json={
        "name": "Bad workflow", "url": "https://ps.example.com", "health_check_type": "WORKFLOW",
        "owner_email": "o@example.com", "manager_email": "m@example.com",
        "owner_name": "O", "manager_name": "M",
        "workflow_steps": [{"name": "Sign in", "method": "POST", "path": "/",
                            "form": {"password": "hunter2"}}],
    })
    assert response.status_code == 422
    assert "environment variable" in str(response.get_json())
