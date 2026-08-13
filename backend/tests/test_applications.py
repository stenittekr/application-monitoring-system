def test_create_application_requires_name(client, admin_headers):
    resp = client.post("/api/applications", headers=admin_headers, json={
        "url": "https://example.com", "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    assert resp.status_code == 422


def test_create_application_rejects_invalid_url(client, admin_headers):
    resp = client.post("/api/applications", headers=admin_headers, json={
        "name": "Bad URL App", "url": "not-a-url",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    assert resp.status_code == 422


def test_create_application_rejects_invalid_email(client, admin_headers):
    resp = client.post("/api/applications", headers=admin_headers, json={
        "name": "Bad Email App", "url": "https://example.com",
        "owner_email": "not-an-email", "manager_email": "m@test.com",
    })
    assert resp.status_code == 422


def test_create_application_rejects_non_positive_interval(client, admin_headers):
    resp = client.post("/api/applications", headers=admin_headers, json={
        "name": "Bad Interval App", "url": "https://example.com",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
        "monitoring_interval": 0,
    })
    assert resp.status_code == 422


def test_update_application(client, admin_headers, sample_application):
    resp = client.put(f"/api/applications/{sample_application.id}", headers=admin_headers,
                       json={"monitoring_interval": 120})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["monitoring_interval"] == 120


def test_delete_application_soft_deletes(client, admin_headers, sample_application):
    resp = client.delete(f"/api/applications/{sample_application.id}", headers=admin_headers)
    assert resp.status_code == 200

    resp = client.get(f"/api/applications/{sample_application.id}", headers=admin_headers)
    assert resp.status_code == 404  # soft-deleted apps are excluded from lookups


def test_enable_disable_monitoring(client, admin_headers, sample_application):
    resp = client.post(f"/api/applications/{sample_application.id}/disable-monitoring", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["monitoring_enabled"] is False
    assert resp.get_json()["data"]["current_status"] == "DISABLED"

    resp = client.post(f"/api/applications/{sample_application.id}/enable-monitoring", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["monitoring_enabled"] is True


def test_get_missing_application_returns_404(client, admin_headers):
    resp = client.get("/api/applications/99999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "APPLICATION_NOT_FOUND"


def test_create_tcp_application_requires_server_and_port(client, admin_headers):
    resp = client.post("/api/applications", headers=admin_headers, json={
        "name": "TCP App", "health_check_type": "TCP",
        "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    assert resp.status_code == 422


def test_create_tcp_application_rejects_invalid_port(client, admin_headers):
    resp = client.post("/api/applications", headers=admin_headers, json={
        "name": "TCP App", "health_check_type": "TCP", "server": "db.internal", "port": 70000,
        "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    assert resp.status_code == 422


def test_create_tcp_application_succeeds_without_url(client, admin_headers):
    resp = client.post("/api/applications", headers=admin_headers, json={
        "name": "TCP App", "health_check_type": "TCP", "server": "db.internal", "port": 1433,
        "owner_email": "o@test.com", "manager_email": "m@test.com",
    })
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["url"] is None
    assert data["server"] == "db.internal"
    assert data["port"] == 1433
