"""FILE and LOG checks (FR-010).

A nightly export that stops being written passes every other check: the process
runs, the service is up, the URL answers, and the file the business needs is
yesterday's.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.services import file_check_service as fc


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "export.csv"
    path.write_text("id,name\n1,a\n2,b\n", encoding="utf-8")
    return str(path)


# ---- file checks ----------------------------------------------------------

def test_a_present_recent_file_passes(sample):
    ok, message = fc.run_file_check({"path": sample, "max_age_minutes": 60, "min_bytes": 1})
    assert ok, message


def test_a_missing_file_fails(tmp_path):
    ok, message = fc.run_file_check({"path": str(tmp_path / "nope.csv")})
    assert not ok
    assert "does not exist" in message


def test_a_stale_file_fails_even_though_it_exists(sample):
    """The whole point: "the file is there" is nearly always true."""
    old = time.time() - 3 * 3600
    os.utime(sample, (old, old))
    ok, message = fc.run_file_check({"path": sample, "max_age_minutes": 60})
    assert not ok
    assert "older than" in message


def test_an_empty_file_fails_a_minimum_size(tmp_path):
    """A zero-byte file is the classic half-finished export."""
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    ok, message = fc.run_file_check({"path": str(path), "min_bytes": 10})
    assert not ok
    assert "bytes" in message


# ---- log checks -----------------------------------------------------------

def _log(tmp_path, text):
    path = tmp_path / "app.log"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_clean_log_passes(tmp_path):
    path = _log(tmp_path, "INFO started\nINFO served 200\n")
    ok, _ = fc.run_log_check({"path": path, "pattern": "ERROR", "max_matches": 0})
    assert ok


def test_a_repeating_exception_fails_and_quotes_it(tmp_path):
    path = _log(tmp_path, "INFO ok\nERROR db timeout\nERROR db timeout\n")
    ok, message = fc.run_log_check({"path": path, "pattern": "ERROR.*", "max_matches": 1})
    assert not ok
    assert "2 match" in message
    assert "db timeout" in message, "the message has to say what was found"


def test_a_threshold_tolerates_the_expected_noise(tmp_path):
    """Most logs are never completely clean; the question is how many."""
    path = _log(tmp_path, "ERROR one\n")
    ok, _ = fc.run_log_check({"path": path, "pattern": "ERROR", "max_matches": 5})
    assert ok


def test_an_invalid_pattern_is_reported_not_raised(tmp_path):
    path = _log(tmp_path, "anything\n")
    ok, message = fc.run_log_check({"path": path, "pattern": "([unclosed", "max_matches": 0})
    assert not ok
    assert "not valid" in message


# ---- validation -----------------------------------------------------------

def test_a_pattern_matching_everything_is_rejected(sample):
    """It would find an error in every file, forever."""
    assert fc.validate_file_check({"path": sample, "pattern": ".*"})
    assert fc.validate_file_check({"path": sample, "pattern": ".+"})


def test_a_path_is_required():
    assert fc.validate_file_check({}) == ["A file check needs a path."]


def test_a_sane_configuration_validates(sample):
    assert fc.validate_file_check(
        {"path": sample, "max_age_minutes": 60, "min_bytes": 1, "pattern": "ERROR"}) == []
