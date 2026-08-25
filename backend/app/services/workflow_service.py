"""Synthetic business-workflow checks - layer 5 of the core monitoring model.

A URL returning 200 does not prove anyone can log in and do their job. This
runs a short, declarative sequence of HTTP steps against an application and
asserts what each one should return.

Deliberately declarative, not scriptable. §14 allows only allow-listed
diagnostic actions - never arbitrary code - so a workflow is a list of steps
with a fixed vocabulary, stored as JSON. There is no eval, no shell, and no way
to express anything but an HTTP request and an assertion about its response.

    {
      "name":            "Sign in",
      "method":          "POST",                # GET or POST
      "path":            "/",
      "login":           true,                  # see "Session reuse" below
      "form":            {"username": "svc_monitor", "password": "${SYN_PASSWORD}"},
      "expect_status":   200,
      "expect_contains": "Dashboard",
      "expect_absent":   "Invalid username or password"
    }

Credentials are ${ENV_VAR} references resolved at run time. Validation rejects a
literal in any password-like field, so test logins are not stored in the profile
text, displayed in the UI, or carried into an export (§18).

Session reuse - and why it is not optional
------------------------------------------
The target application imposes limits that a naive "log in on every check"
workflow would violate within a day:

  * sessions expire after 600s of inactivity
  * logins are rate limited to 10 failures per 300s per IP
  * every login attempt writes an audit row

Logging in on each 5-minute tick would add ~288 audit rows a day per workflow,
and an expired service-account password would burn through the rate limit in
under three minutes and lock the monitor out of its own retries.

So steps flagged `"login": true` run only when there is no usable session:

  * a session is kept per application and reused while it is younger than the
    inactivity window
  * if a post-login step fails in a way that looks like the session was dropped,
    the session is discarded and the full flow runs once more
  * after repeated login failures the workflow stops attempting to log in for a
    cooldown period, well short of the rate limit, and reports why

The result is roughly one login per inactivity window rather than one per check.
"""
import logging
import os
import re
import time

import requests

from app.utils.redaction import redact

logger = logging.getLogger(__name__)

ALLOWED_METHODS = ("GET", "POST")
MAX_STEPS = 10
STEP_TIMEOUT_SECONDS = 20
MAX_BODY_INSPECTED = 200_000

# Comfortably inside the target's 600s inactivity window, so a session is never
# reused a moment after the server has already dropped it.
SESSION_MAX_IDLE_SECONDS = 480

# The target allows 10 login failures per 300s per IP. Stopping at 3 leaves a
# wide margin, because tripping that limit locks the monitor out of the retries
# it would need to recover.
MAX_LOGIN_FAILURES = 3
LOGIN_COOLDOWN_SECONDS = 900

# Signs that a request was bounced back to the login screen rather than served.
SESSION_LOST_MARKERS = ("login", "sign in", "session expired", "please log in")

_ENV_REF = re.compile(r"^\$\{(\w+)\}$")

# Live sessions, keyed by application id. Process-local by design: the worker is
# a single process, and a session cookie is not something to share between hosts.
# ponytail: swap for a shared store only if the worker is ever run more than once.
_SESSIONS = {}


def _resolve(value):
    """Turns a ${ENV_VAR} reference into its value; leaves anything else alone."""
    match = _ENV_REF.match(str(value or ""))
    return os.environ.get(match.group(1), "") if match else value


def _looks_secret(field_name):
    """Field names whose values must never be stored in the profile."""
    return bool(re.search(r"(?i)pass|pwd|secret|token|key|otp", str(field_name or "")))


def validate_workflow(steps):
    """Returns a list of human-readable errors; empty means the workflow is valid.

    Runs before anything is stored, so an invalid workflow is rejected at the
    edit rather than failing silently at 3am (§19 configuration error).
    """
    errors = []
    if not isinstance(steps, list) or not steps:
        return ["A workflow needs at least one step."]
    if len(steps) > MAX_STEPS:
        errors.append(f"A workflow may have at most {MAX_STEPS} steps.")

    for index, step in enumerate(steps, start=1):
        where = f"Step {index}"
        if not isinstance(step, dict):
            errors.append(f"{where} must be an object.")
            continue
        if not str(step.get("name") or "").strip():
            errors.append(f"{where} needs a name.")
        if str(step.get("method") or "GET").upper() not in ALLOWED_METHODS:
            errors.append(f"{where}: method must be one of {ALLOWED_METHODS}.")
        if not str(step.get("path") or "").strip().startswith("/"):
            errors.append(f"{where}: path must start with '/'.")
        status = step.get("expect_status", 200)
        if not isinstance(status, int) or not (100 <= status <= 599):
            errors.append(f"{where}: expect_status must be an HTTP status code.")
        form = step.get("form")
        if form is not None and not isinstance(form, dict):
            errors.append(f"{where}: form must be an object of field names to values.")
        elif isinstance(form, dict):
            for field, value in form.items():
                if _looks_secret(field) and not _ENV_REF.match(str(value or "")):
                    errors.append(
                        f"{where}: '{field}' must reference an environment variable "
                        f"as ${{VAR_NAME}}, not a literal value."
                    )

    return errors


def workflow_warnings(steps):
    """Non-fatal advice about a workflow, shown when editing."""
    if isinstance(steps, list) and steps and not any(
            isinstance(s, dict) and s.get("login") for s in steps):
        return ["No step is marked as the login step, so a fresh login will run "
                "on every check. Mark the authenticating step with \"login\": true "
                "to reuse the session."]
    return []


def _session_for(application_id):
    """Returns a reusable session, or None if there is not a usable one."""
    entry = _SESSIONS.get(application_id)
    if not entry:
        return None
    if time.monotonic() - entry["last_used"] > SESSION_MAX_IDLE_SECONDS:
        _drop_session(application_id, "idle past the inactivity window")
        return None
    return entry["session"]


def _drop_session(application_id, why):
    """Closes and forgets a session."""
    entry = _SESSIONS.pop(application_id, None)
    if entry:
        try:
            entry["session"].close()
        except Exception:
            pass
        logger.info("Workflow session for application %s dropped: %s", application_id, why)


def _cooldown_remaining(application_id):
    """Seconds left before logins may be attempted again, or 0."""
    entry = _SESSIONS.get(f"cooldown:{application_id}")
    if not entry:
        return 0
    return max(0, entry - time.monotonic())


def _note_login_failure(application_id):
    """Counts a failed login and starts a cooldown once the run is long enough.

    The point is to stay well clear of the target's 10-failures-per-300s limit:
    an expired service-account password otherwise locks the monitor out of the
    very retries it needs to recover once the password is fixed.
    """
    key = f"failures:{application_id}"
    count = _SESSIONS.get(key, 0) + 1
    _SESSIONS[key] = count
    if count >= MAX_LOGIN_FAILURES:
        _SESSIONS[f"cooldown:{application_id}"] = time.monotonic() + LOGIN_COOLDOWN_SECONDS
        _SESSIONS[key] = 0
        logger.warning("Application %s: %d consecutive workflow login failures - "
                       "pausing logins for %ds to stay clear of the rate limit.",
                       application_id, count, LOGIN_COOLDOWN_SECONDS)


def _clear_login_failures(application_id):
    _SESSIONS.pop(f"failures:{application_id}", None)
    _SESSIONS.pop(f"cooldown:{application_id}", None)


def _looks_like_session_loss(response, body):
    """True when a request that should have been served was bounced to login."""
    if response.status_code in (401, 403):
        return True
    return any(marker in body for marker in SESSION_LOST_MARKERS)


def _run_steps(session, application, steps, skip_login):
    """Runs the steps once. Returns (ok, message, session_lost)."""
    base = (application.url or "").rstrip("/")
    for index, step in enumerate(steps, start=1):
        if skip_login and step.get("login"):
            continue
        label = step.get("name") or f"step {index}"
        method = str(step.get("method") or "GET").upper()
        data = {k: _resolve(v) for k, v in (step.get("form") or {}).items()}

        response = session.request(
            method, base + str(step.get("path") or "/"),
            data=data or None,
            timeout=min(application.timeout or STEP_TIMEOUT_SECONDS, STEP_TIMEOUT_SECONDS),
            allow_redirects=step.get("follow_redirects", True),
            verify=application.verify_ssl,
        )
        body = response.text[:MAX_BODY_INSPECTED].lower()

        expected = step.get("expect_status", 200)
        if response.status_code != expected:
            # A 500 here says only "something broke" - the application returns a
            # generic message - so the step name and status are the whole signal.
            lost = skip_login and _looks_like_session_loss(response, body)
            return False, (f"Step {index} '{label}': expected HTTP {expected}, "
                           f"got {response.status_code}"), lost

        needle = step.get("expect_contains")
        if needle and str(needle).lower() not in body:
            lost = skip_login and _looks_like_session_loss(response, body)
            return False, f"Step {index} '{label}': response did not contain '{needle}'", lost

        absent = step.get("expect_absent")
        if absent and str(absent).lower() in body:
            return False, f"Step {index} '{label}': response contained '{absent}'", False

    return True, None, False


def run_workflow(application, steps):
    """Executes the workflow, reusing a session where the definition allows it.

    Returns (success, message, elapsed_ms). Stops at the first failing step and
    names it, because "workflow failed" is not actionable but
    "step 2 'Sign in' returned 401" is.
    """
    start = time.monotonic()
    app_id = application.id
    has_login_step = any(s.get("login") for s in steps)

    waiting = _cooldown_remaining(app_id)
    if waiting:
        return (False,
                f"Login paused for {int(waiting)}s after repeated failures - "
                f"staying clear of the application's login rate limit. "
                f"Check the monitoring account's password.",
                _ms(start))

    session = _session_for(app_id) if has_login_step else None
    reusing = session is not None

    if session is None:
        session = requests.Session()

    # A network-level failure is data, not an exception to propagate: the caller
    # turns it into a DOWN result like any other failed check.
    try:
        ok, message, session_lost = _run_steps(session, application, steps, skip_login=reusing)

        # A dropped session is not an outage: log in again and judge on that.
        if not ok and reusing and session_lost:
            _drop_session(app_id, "server rejected the reused session")
            session = requests.Session()
            ok, message, session_lost = _run_steps(session, application, steps, skip_login=False)
            reusing = False
    except requests.exceptions.RequestException as exc:
        _drop_session(app_id, "request failed")
        if not reusing:
            session.close()
        return False, redact(f"Workflow request failed: {exc}")[:400], _ms(start)

    if ok:
        if has_login_step:
            _SESSIONS[app_id] = {"session": session, "last_used": time.monotonic()}
        else:
            session.close()
        _clear_login_failures(app_id)
        return True, None, _ms(start)

    if has_login_step and not reusing:
        _note_login_failure(app_id)
    if not reusing:
        session.close()
    return False, message, _ms(start)


def _ms(start):
    return (time.monotonic() - start) * 1000
