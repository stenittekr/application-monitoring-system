"""FR-011 / layer 5: synthetic business transactions.

A URL returning 200 does not prove anyone can log in and do their job. These
cover the execution, and the rule that keeps test credentials out of the
profile text (§18).
"""
from unittest.mock import Mock, patch

import pytest

from app.services.workflow_service import run_workflow, validate_workflow


class FakeApp:
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
