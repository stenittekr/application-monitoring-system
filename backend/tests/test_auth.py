def test_login_success(client, admin_user):
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "Passw0rd!"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["success"] is True
    assert body["data"]["access_token"]
    assert body["data"]["user"]["role"] == "ADMIN"


def test_login_wrong_password(client, admin_user):
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.get_json()["success"] is False


def test_login_missing_fields(client):
    resp = client.post("/api/auth/login", json={"email": "admin@test.com"})
    assert resp.status_code == 400


def test_login_disabled_account(client, db, admin_user):
    admin_user.is_active = False
    db.session.commit()
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "Passw0rd!"})
    assert resp.status_code == 403


def test_me_requires_token(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user(client, admin_headers):
    resp = client.get("/api/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["email"] == "admin@test.com"
