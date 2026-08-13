from app.models.activity_log import ActivityLog


def test_creating_application_writes_activity_log(client, admin_headers, admin_user):
    client.post("/api/applications", headers=admin_headers, json={
        "name": "Logged App", "url": "https://example.com",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    entry = ActivityLog.query.filter_by(action="APPLICATION_CREATED").first()
    assert entry is not None
    assert entry.user_id == admin_user.id
    assert "Logged App" in entry.description


def test_login_and_logout_are_logged(client, admin_headers):
    client.post("/api/auth/logout", headers=admin_headers)
    actions = [row.action for row in ActivityLog.query.all()]
    assert "LOGIN" in actions
    assert "LOGOUT" in actions


def test_monitoring_toggle_is_logged(client, admin_headers, sample_application):
    client.post(f"/api/applications/{sample_application.id}/disable-monitoring", headers=admin_headers)
    entry = ActivityLog.query.filter_by(action="MONITORING_DISABLED").first()
    assert entry is not None
    assert entry.entity_id == sample_application.id
