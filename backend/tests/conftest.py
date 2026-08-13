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
def manager_user(db):
    return _make_user(db, "Manager", "manager@test.com", "Passw0rd!", "MANAGER")


@pytest.fixture()
def viewer_user(db):
    return _make_user(db, "Viewer", "viewer@test.com", "Passw0rd!", "VIEWER")


def _auth_header(client, email, password):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    token = resp.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return _auth_header(client, "admin@test.com", "Passw0rd!")


@pytest.fixture()
def manager_headers(client, manager_user):
    return _auth_header(client, "manager@test.com", "Passw0rd!")


@pytest.fixture()
def viewer_headers(client, viewer_user):
    return _auth_header(client, "viewer@test.com", "Passw0rd!")


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
        manager_email="manager@test.com",
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
