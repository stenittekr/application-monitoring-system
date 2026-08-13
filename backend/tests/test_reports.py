from unittest.mock import patch


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_availability_report_reflects_health_checks(client, admin_headers, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(200)):
        client.post(f"/api/applications/{sample_application.id}/check", headers=admin_headers)

    resp = client.get("/api/reports/availability", headers=admin_headers)
    assert resp.status_code == 200
    rows = resp.get_json()["data"]
    assert len(rows) == 1
    assert rows[0]["application_name"] == "Sample App"
    assert rows[0]["availability_percent"] == 100.0


def test_availability_export_returns_csv(client, admin_headers, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(200)):
        client.post(f"/api/applications/{sample_application.id}/check", headers=admin_headers)

    resp = client.get("/api/reports/availability/export", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"Sample App" in resp.data


def test_failure_frequency_counts_failed_checks(client, admin_headers, sample_application):
    with patch("app.services.monitoring_service.requests.get", return_value=FakeResponse(500)):
        with patch("app.services.notification_service.send_email"):
            client.post(f"/api/applications/{sample_application.id}/check", headers=admin_headers)

    resp = client.get("/api/reports/failure-frequency", headers=admin_headers)
    rows = resp.get_json()["data"]
    assert rows[0]["failure_count"] >= 1
