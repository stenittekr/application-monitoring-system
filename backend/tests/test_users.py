from app.models.user import User


def test_create_user_without_password_succeeds_with_a_local_hash(client, db, admin_headers):
    """No password is how you add an AD-only user (auth.py falls back to LDAP) -
    they still need a stored hash, since password_hash is NOT NULL, but it must
    not be blank/guessable."""
    resp = client.post("/api/users", json={
        "name": "Ajoy", "email": "ajoy@test.com", "role": "ADMIN",
    }, headers=admin_headers)
    assert resp.status_code == 201, resp.get_json()

    user = User.query.filter_by(email="ajoy@test.com").first()
    assert user is not None
    assert user.password_hash
    assert not user.check_password("")
    assert not user.check_password("password")


def test_create_user_with_weak_password_is_rejected(client, admin_headers):
    resp = client.post("/api/users", json={
        "name": "Weak", "email": "weak@test.com", "role": "AUDITOR", "password": "abc",
    }, headers=admin_headers)
    assert resp.status_code == 422
