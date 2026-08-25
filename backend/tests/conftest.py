import sys
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from app.config import Config
from app.extensions import db as _db
from app.models.user import User


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key-at-least-32-bytes-long"
    JWT_SECRET_KEY = "test-jwt-secret-key-at-least-32-bytes-long"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    EMAIL_FROM = "monitoring@example.com"
    SMTP_HOST = "localhost"


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _single_check_alerting(app):
    """Most tests are about something other than alert confirmation, and want one
    failed check to be enough. Production requires 2 consecutive failures; the
    tests that are actually about that set it explicitly."""
    from app.models.system_setting import SystemSetting

    _db.session.add(SystemSetting(setting_key="failed_checks_before_incident", setting_value="1"))
    _db.session.commit()
    yield


@pytest.fixture()
def db(app):
    return _db


def _make_user(db, name, email, password, role):
    user = User(name=name, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def admin_user(db):
    return _make_user(db, "Admin", "admin@test.com", "Passw0rd!", "ADMIN")


@pytest.fixture()
def it_manager_user(db):
    return _make_user(db, "IT Manager", "itmanager@test.com", "Passw0rd!", "IT_MANAGER")


@pytest.fixture()
def app_owner_user(db):
    return _make_user(db, "App Owner", "appowner@test.com", "Passw0rd!", "APP_OWNER")


@pytest.fixture()
def operator_user(db):
    return _make_user(db, "Operator", "operator@test.com", "Passw0rd!", "OPERATOR")


@pytest.fixture()
def auditor_user(db):
    return _make_user(db, "Auditor", "auditor@test.com", "Passw0rd!", "AUDITOR")


def _auth_header(client, email, password):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    token = resp.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return _auth_header(client, "admin@test.com", "Passw0rd!")


@pytest.fixture()
def it_manager_headers(client, it_manager_user):
    return _auth_header(client, "itmanager@test.com", "Passw0rd!")


@pytest.fixture()
def app_owner_headers(client, app_owner_user):
    return _auth_header(client, "appowner@test.com", "Passw0rd!")


@pytest.fixture()
def operator_headers(client, operator_user):
    return _auth_header(client, "operator@test.com", "Passw0rd!")


@pytest.fixture()
def auditor_headers(client, auditor_user):
    return _auth_header(client, "auditor@test.com", "Passw0rd!")


@pytest.fixture()
def sample_application(db, admin_user):
    from app.models.application import Application

    application = Application(
        name="Sample App",
        url="https://example.com",
        environment="Production",
        owner_name="Owner",
        owner_email="owner@test.com",
        manager_name="Manager",
        manager_email="appowner@test.com",
        monitoring_enabled=True,
        monitoring_interval=60,
        timeout=5,
        retry_count=3,
        retry_delay=0,  # no real sleeping in tests
        expected_status_code=200,
        current_status="UP",
    )
    db.session.add(application)
    db.session.commit()
    return application
