from app.services import application_service
from app.utils.validators import validate_application_payload

_DEFAULTS = {"interval": 60, "timeout": 10, "retry_count": 3, "retry_delay": 5}


def _create(db, **overrides):
    data = {
        "name": "App A", "url": "https://a.example.com",
        "owner_email": "owner@test.com", "manager_email": "manager@test.com",
        **overrides,
    }
    return application_service.create_application(data, _DEFAULTS)


def test_new_application_defaults_to_monitored(db):
    app_row = _create(db)
    assert app_row.maturity_status == "MONITORED"
    assert app_row.depends_on == []
    assert app_row.to_dict()["baseline_notes"] is None


def test_health_profile_fields_round_trip(db):
    db_app = _create(db, maturity_status="discovered", baseline_notes="~200ms normally")
    dependent = _create(db, name="App B")
    application_service.update_application(db_app, {"depends_on": [dependent.id]})

    assert db_app.maturity_status == "DISCOVERED"
    assert db_app.depends_on == [dependent.id]
    d = db_app.to_dict()
    assert d["baseline_notes"] == "~200ms normally"
    assert d["depends_on"] == [dependent.id]


def test_application_cannot_depend_on_itself(db):
    """Regression guard: selecting yourself in the Depends On list must be silently dropped, not stored."""
    app_row = _create(db)
    application_service.update_application(app_row, {"depends_on": [app_row.id]})
    assert app_row.depends_on == []


def test_validator_rejects_bad_maturity_status():
    errors = validate_application_payload({
        "name": "X", "url": "https://x.example.com",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
        "maturity_status": "NOT_A_REAL_STATUS",
    })
    assert any("Maturity status" in e for e in errors)


def test_validator_rejects_non_list_depends_on():
    errors = validate_application_payload({
        "name": "X", "url": "https://x.example.com",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
        "depends_on": "not-a-list",
    })
    assert any("Dependencies" in e for e in errors)
