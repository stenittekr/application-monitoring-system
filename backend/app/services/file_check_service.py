"""FILE and LOG checks (FR-010, FR-009, §9 supported check types).

Two failures this platform could not have seen:

  * a nightly export that stops being written. The process runs, the service is
    up, the URL answers - and the file that the business actually needs is
    yesterday's. Every other check passes.
  * an application writing the same exception every few seconds. Nothing is
    down, response times are normal, and the only evidence is in a log nobody
    reads until someone complains.

Both are configured as a check like any other, so they inherit intervals,
consecutive-failure rules, severity, maintenance windows and alert routing.

These run from the platform, which means the path has to be reachable from it -
a local path on a monitored server is not. A UNC share is the usual answer;
per-agent execution is the better one and is not built.
"""
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Enough of a log to find a repeating error, not so much that a runaway file
# takes the monitoring cycle down with it.
MAX_LOG_BYTES = 2_000_000

# A pattern that matches everything finds an error in every file. Rejected at
# configuration time rather than discovered at three in the morning.
FORBIDDEN_PATTERNS = ("", ".", ".*", ".+", "^", "$")


def validate_file_check(config):
    """Returns human-readable errors; empty means the configuration is usable."""
    errors = []
    path = (config or {}).get("path")
    if not str(path or "").strip():
        errors.append("A file check needs a path.")

    max_age = (config or {}).get("max_age_minutes")
    if max_age is not None:
        try:
            if int(max_age) <= 0:
                errors.append("max_age_minutes must be a positive number of minutes.")
        except (TypeError, ValueError):
            errors.append("max_age_minutes must be a number.")

    min_bytes = (config or {}).get("min_bytes")
    if min_bytes is not None:
        try:
            if int(min_bytes) < 0:
                errors.append("min_bytes cannot be negative.")
        except (TypeError, ValueError):
            errors.append("min_bytes must be a number.")

    pattern = (config or {}).get("pattern")
    if pattern is not None:
        if str(pattern).strip() in FORBIDDEN_PATTERNS:
            errors.append("That pattern matches everything, so every check would fail.")
        else:
            try:
                re.compile(str(pattern))
            except re.error as exc:
                errors.append(f"pattern is not a valid regular expression: {exc}")
    return errors


def _file_state(path):
    """(exists, size_bytes, modified_at)."""
    try:
        stat = os.stat(path)
    except OSError:
        return False, 0, None
    return True, stat.st_size, datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)


def run_file_check(config, now=None):
    """Existence, freshness and size. Returns (ok, message).

    Freshness is the point. "The file is there" is nearly always true; "the file
    is from today" is the question, and it is the one a stalled export answers
    badly while every other check still passes.
    """
    now = now or datetime.now(timezone.utc)
    path = str(config.get("path") or "")
    exists, size, modified = _file_state(path)

    if not exists:
        return False, f"{path} does not exist"

    min_bytes = config.get("min_bytes")
    if min_bytes is not None and size < int(min_bytes):
        # A zero-byte file is the classic half-finished export: created, then
        # abandoned when the job died.
        return False, f"{path} is {size} bytes, expected at least {min_bytes}"

    max_age = config.get("max_age_minutes")
    if max_age is not None and modified is not None:
        age = (now - modified).total_seconds() / 60
        if age > int(max_age):
            return False, (f"{path} was last written {int(age)} minutes ago, "
                           f"which is older than the {int(max_age)} allowed")

    detail = f"{path}: {size} bytes"
    if modified is not None:
        detail += f", written {int((now - modified).total_seconds() / 60)} minutes ago"
    return True, detail


def run_log_check(config, now=None):
    """Looks for a pattern in the tail of a log file. Returns (ok, message).

    Only the tail is read, and only the recent part of it: a log is append-only,
    the interesting lines are the newest, and reading a 4 GB file every five
    minutes would make the monitor the heaviest thing on the server.
    """
    path = str(config.get("path") or "")
    pattern = str(config.get("pattern") or "")
    threshold = int(config.get("max_matches") or 0)

    exists, size, _ = _file_state(path)
    if not exists:
        return False, f"{path} does not exist"

    try:
        with open(path, "rb") as handle:
            if size > MAX_LOG_BYTES:
                handle.seek(size - MAX_LOG_BYTES)
                handle.readline()      # discard the partial first line
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return False, f"could not read {path}: {exc}"

    try:
        matches = re.findall(pattern, tail, re.IGNORECASE | re.MULTILINE)
    except re.error as exc:
        # A bad pattern is a configuration fault, not an application outage.
        return False, f"pattern is not valid: {exc}"

    count = len(matches)
    if count > threshold:
        sample = str(matches[-1])[:120] if matches else ""
        return False, (f"{count} match(es) for '{pattern}' in the last "
                       f"{min(size, MAX_LOG_BYTES) // 1024} KB of {path}"
                       + (f" - most recent: {sample}" if sample else ""))
    return True, f"{count} match(es) for '{pattern}', within the {threshold} allowed"
