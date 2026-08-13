def test_auditor_cannot_create_application(client, auditor_headers):
    resp = client.post("/api/applications", headers=auditor_headers, json={
        "name": "New App", "url": "https://example.com",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    assert resp.status_code == 403


def test_admin_can_create_application(client, admin_headers):
    resp = client.post("/api/applications", headers=admin_headers, json={
        "name": "New App", "url": "https://example.com",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    assert resp.status_code == 201


def test_it_manager_can_create_application(client, it_manager_headers):
    resp = client.post("/api/applications", headers=it_manager_headers, json={
        "name": "New App", "url": "https://example.com",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    assert resp.status_code == 201


def test_auditor_can_list_all_applications(client, auditor_headers, sample_application):
    resp = client.get("/api/applications", headers=auditor_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 1


def test_it_manager_sees_all_applications(client, db, it_manager_headers, sample_application):
    from app.models.application import Application

    other = Application(
        name="Other App", url="https://other.example.com", environment="Production",
        owner_name="X", owner_email="other-owner@test.com",
        manager_name="Y", manager_email="other-manager@test.com",
        current_status="UP",
    )
    db.session.add(other)
    db.session.commit()

    resp = client.get("/api/applications", headers=it_manager_headers)
    names = [a["name"] for a in resp.get_json()["data"]]
    assert "Sample App" in names
    assert "Other App" in names


def test_app_owner_only_sees_assigned_applications(client, db, app_owner_headers, sample_application):
    from app.models.application import Application

    other = Application(
        name="Other App", url="https://other.example.com", environment="Production",
        owner_name="X", owner_email="other-owner@test.com",
        manager_name="Y", manager_email="other-manager@test.com",
        current_status="UP",
    )
    db.session.add(other)
    db.session.commit()

    # sample_application's manager_email is appowner@test.com, matching the app_owner fixture.
    resp = client.get("/api/applications", headers=app_owner_headers)
    names = [a["name"] for a in resp.get_json()["data"]]
    assert "Sample App" in names
    assert "Other App" not in names


def test_app_owner_cannot_view_unowned_application_by_id(client, db, app_owner_headers, sample_application):
    from app.models.application import Application

    other = Application(
        name="Other App", url="https://other.example.com", environment="Production",
        owner_name="X", owner_email="other-owner@test.com",
        manager_name="Y", manager_email="other-manager@test.com",
        current_status="UP",
    )
    db.session.add(other)
    db.session.commit()

    resp = client.get(f"/api/applications/{other.id}", headers=app_owner_headers)
    assert resp.status_code == 403


def test_operator_cannot_view_activity_logs(client, operator_headers):
    resp = client.get("/api/activity-logs", headers=operator_headers)
    assert resp.status_code == 403


def test_auditor_can_view_activity_logs(client, auditor_headers):
    resp = client.get("/api/activity-logs", headers=auditor_headers)
    assert resp.status_code == 200


def test_admin_can_view_activity_logs(client, admin_headers):
    resp = client.get("/api/activity-logs", headers=admin_headers)
    assert resp.status_code == 200


def test_app_owner_cannot_view_servers(client, app_owner_headers):
    resp = client.get("/api/servers", headers=app_owner_headers)
    assert resp.status_code == 403


def test_operator_can_view_servers(client, operator_headers):
    resp = client.get("/api/servers", headers=operator_headers)
    assert resp.status_code == 200
