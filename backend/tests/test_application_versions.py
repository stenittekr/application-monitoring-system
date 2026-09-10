"""Versioned profiles with rollback (FR-019, §19 configuration error).

A profile could be edited into a state that stopped alerting, and the only
record of what it had been was whoever remembered.
"""
import pytest

from app.extensions import db
from app.models.application_version import ApplicationVersion
from app.services import application_service


def test_an_edit_stores_what_the_profile_was_before_it(db, sample_application):
    """Before, not after: version 1 is what someone wants back."""
    original_url = sample_application.url
    application_service.update_application(sample_application, {"url": "https://changed.example"})

    version = ApplicationVersion.query.filter_by(application_id=sample_application.id).one()
    assert version.version == 1
    assert version.snapshot["url"] == original_url
    assert sample_application.url == "https://changed.example"


def test_versions_number_upwards(db, sample_application):
    for i in range(3):
        application_service.update_application(sample_application, {"description": f"edit {i}"})
    versions = [v.version for v in ApplicationVersion.query.filter_by(
        application_id=sample_application.id).all()]
    assert versions == [1, 2, 3]


def test_a_rollback_restores_the_earlier_profile(db, sample_application):
    original = sample_application.url
    application_service.update_application(sample_application, {"url": "https://broken.example"})
    assert sample_application.url == "https://broken.example"

    restored, error = application_service.rollback_application(sample_application, 1)
    assert error is None
    assert restored.url == original


def test_a_rollback_is_itself_reversible(db, sample_application):
    """Undo that cannot be undone is not a safety feature."""
    application_service.update_application(sample_application, {"url": "https://second.example"})
    application_service.rollback_application(sample_application, 1)

    # the rollback snapshotted the state it replaced
    notes = [v.change_note for v in ApplicationVersion.query.filter_by(
        application_id=sample_application.id).all()]
    assert any(n and "Before rollback" in n for n in notes)
    assert sample_application.url != "https://second.example"

    restored, error = application_service.rollback_application(sample_application, 2)
    assert error is None
    assert restored.url == "https://second.example"


def test_rolling_back_to_a_version_that_does_not_exist_is_refused(db, sample_application):
    restored, error = application_service.rollback_application(sample_application, 99)
    assert restored is None
    assert "does not exist" in error


def test_status_is_not_rolled_back_with_configuration(db, sample_application):
    """current_status describes what happened, not what was configured.
    Restoring it would rewrite history rather than configuration."""
    application_service.update_application(sample_application, {"description": "x"})
    sample_application.current_status = "DOWN"
    db.session.commit()

    application_service.rollback_application(sample_application, 1)
    assert sample_application.current_status == "DOWN"
