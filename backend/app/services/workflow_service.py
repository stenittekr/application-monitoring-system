"""Synthetic business-workflow checks - layer 5 of the core monitoring model.

A URL returning 200 does not prove anyone can log in and do their job. This
runs a short, declarative sequence of HTTP steps against an application and
asserts what each one should return: fetch the login page, post credentials,
confirm the landing page actually contains what a signed-in user sees.

Deliberately declarative, not scriptable. §14 allows only allow-listed
diagnostic actions - never arbitrary code - so a workflow is a list of steps
with a fixed vocabulary, stored as JSON. There is no eval, no shell, and no way
to express anything but an HTTP request and an assertion about its response.

A workflow step:

    {
      "name":            "Sign in",             # shown in the failure message
      "method":          "POST",                # GET or POST
      "path":            "/login",              # joined to the application URL
      "form":            {"user": "${SYN_USER}", "password": "${SYN_PASSWORD}"},
      "expect_status":   302,                   # default 200
      "expect_contains": "Welcome",             # optional, case-insensitive
      "expect_absent":   "Invalid credentials"  # optional
    }

Credentials are ${ENV_VAR} references resolved from the platform's environment
at run time, exactly like database DSNs. Validation rejects a literal secret, so
test credentials never sit in the profile text (§18).

Cookies persist across steps, so a session established by a login step carries
into the ones that follow.
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
MAX_BODY_INSPECTED = 200_000  # enough to assert on; not a reason to buffer 50 MB

_ENV_REF = re.compile(r"^\$\{(\w+)\}$")


def _resolve(value):
    """Turns a ${ENV_VAR} reference into its value; leaves anything else alone."""
    match = _ENV_REF.match(str(value or ""))
    return os.environ.get(match.group(1), "") if match else value


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
        method = str(step.get("method") or "GET").upper()
        if method not in ALLOWED_METHODS:
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
                # A password typed straight into the profile would be stored,
                # displayed and exported. Only a reference is acceptable.
                if _looks_secret(field) and not _ENV_REF.match(str(value or "")):
                    errors.append(
                        f"{where}: '{field}' must reference an environment variable "
                        f"as ${{VAR_NAME}}, not a literal value."
                    )
    return errors


def _looks_secret(field_name):
    """Field names whose values must never be stored in the profile."""
    return bool(re.search(r"(?i)pass|pwd|secret|token|key|otp", str(field_name or "")))


def run_workflow(application, steps):
    """Executes the steps in order. Returns (success, message, elapsed_ms).

    Stops at the first failing step and names it, because "workflow failed" is
    not actionable but "step 2 'Sign in' returned 401" is.
    """
    base = (application.url or "").rstrip("/")
    start = time.monotonic()
    session = requests.Session()
    try:
        for index, step in enumerate(steps, start=1):
            label = step.get("name") or f"step {index}"
            method = str(step.get("method") or "GET").upper()
            url = base + str(step.get("path") or "/")
            data = {k: _resolve(v) for k, v in (step.get("form") or {}).items()}

            response = session.request(
                method, url,
                data=data or None,
                timeout=min(application.timeout or STEP_TIMEOUT_SECONDS, STEP_TIMEOUT_SECONDS),
                allow_redirects=step.get("follow_redirects", True),
                verify=application.verify_ssl,
            )

            expected = step.get("expect_status", 200)
            if response.status_code != expected:
                return False, f"Step {index} '{label}': expected HTTP {expected}, got {response.status_code}", _ms(start)

            body = response.text[:MAX_BODY_INSPECTED].lower()
            needle = step.get("expect_contains")
            if needle and str(needle).lower() not in body:
                return False, f"Step {index} '{label}': response did not contain '{needle}'", _ms(start)
            absent = step.get("expect_absent")
            if absent and str(absent).lower() in body:
                return False, f"Step {index} '{label}': response contained '{absent}'", _ms(start)

        return True, None, _ms(start)
    except requests.exceptions.RequestException as exc:
        return False, redact(f"Workflow request failed: {exc}")[:400], _ms(start)
    finally:
        session.close()


def _ms(start):
    return (time.monotonic() - start) * 1000
