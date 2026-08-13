def test_viewer_cannot_create_application(client, viewer_headers):
    resp = client.post("/api/applications", headers=viewer_headers, json={
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


def test_viewer_can_list_applications(client, viewer_headers, sample_application):
    resp = client.get("/api/applications", headers=viewer_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 1


def test_manager_only_sees_assigned_applications(client, db, manager_headers, sample_application):
    from app.models.application import Application

    other = Application(
        name="Other App", url="https://other.example.com", environment="Production",
        owner_name="X", owner_email="other-owner@test.com",
        manager_name="Y", manager_email="other-manager@test.com",
        current_status="UP",
    )
    db.session.add(other)
    db.session.commit()

    # sample_application's manager_email is manager@test.com, matching the manager fixture.
    resp = client.get("/api/applications", headers=manager_headers)
    names = [a["name"] for a in resp.get_json()["data"]]
    assert "Sample App" in names
    assert "Other App" not in names


def test_viewer_cannot_view_activity_logs(client, viewer_headers):
    resp = client.get("/api/activity-logs", headers=viewer_headers)
    assert resp.status_code == 403


def test_admin_can_view_activity_logs(client, admin_headers):
    resp = client.get("/api/activity-logs", headers=admin_headers)
    assert resp.status_code == 200
