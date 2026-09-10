"""§21: authorised users can acknowledge, comment, assign, resolve and report
incidents; unauthorised users cannot modify them."""
from app.models.incident import Incident
from app.models.incident_note import IncidentNote
from app.services import incident_service


def _incident(db, sample_application):
    from datetime import datetime, timezone
    incident, _ = incident_service.open_incident(
        sample_application, detected_at=datetime.now(timezone.utc), reason="Test outage")
    return incident


def test_a_note_records_who_and_when(db, sample_application, admin_user):
    incident = _incident(db, sample_application)
    incident_service.add_note(incident, admin_user.id, "Checked the app pool, recycled it.")

    note = IncidentNote.query.one()
    assert note.user_id == admin_user.id
    assert note.created_at is not None
    assert note.to_dict()["user_name"] == admin_user.name


def test_manual_resolve_records_the_cause_and_the_person(db, sample_application, admin_user):
    incident = _incident(db, sample_application)
    incident_service.resolve_manually(incident, admin_user.id,
                                      category="Configuration", note="Wrong port in config.")
    assert incident.status == "RESOLVED"
    assert incident.resolved_by_id == admin_user.id
    assert incident.resolution_category == "Configuration"
    assert incident.duration_seconds is not None


def test_reopening_keeps_the_original_detection_time(db, sample_application, admin_user):
    """The outage began when it began. Rewriting that corrupts every
    availability figure this incident feeds."""
    incident = _incident(db, sample_application)
    original_detected = incident.detected_at
    original_started = incident.started_at

    incident_service.resolve_manually(incident, admin_user.id, category="Fixed")
    incident_service.reopen(incident, admin_user.id, "Still failing for users in Kabul")

    assert incident.status == "OPEN"
    assert incident.resolved_at is None
    assert incident.reopened_count == 1
    assert incident.detected_at == original_detected
    assert incident.started_at == original_started
    assert "Reopened:" in IncidentNote.query.order_by(IncidentNote.id.desc()).first().note


def test_reopening_allows_the_recovery_email_to_fire_again(db, sample_application, admin_user):
    incident = _incident(db, sample_application)
    incident.recovery_notification_sent = True
    incident_service.resolve_manually(incident, admin_user.id)
    incident_service.reopen(incident, admin_user.id, "not actually fixed")
    assert incident.recovery_notification_sent is False


def test_an_auditor_cannot_add_a_note(client, auditor_headers, db, sample_application):
    """Read-only means read-only (§4)."""
    incident = _incident(db, sample_application)
    response = client.post(f"/api/incidents/{incident.id}/notes",
                           json={"note": "trying to comment"}, headers=auditor_headers)
    assert response.status_code == 403
    assert IncidentNote.query.count() == 0


def test_an_operator_can_comment_and_resolve(client, operator_headers, db, sample_application):
    incident = _incident(db, sample_application)
    assert client.post(f"/api/incidents/{incident.id}/notes",
                       json={"note": "Restarted the service"}, headers=operator_headers).status_code == 201
    assert client.post(f"/api/incidents/{incident.id}/resolve",
                       json={"category": "Service restart"}, headers=operator_headers).status_code == 200
    assert db.session.get(Incident, incident.id).status == "RESOLVED"


def test_an_empty_note_is_rejected(client, admin_headers, db, sample_application):
    incident = _incident(db, sample_application)
    response = client.post(f"/api/incidents/{incident.id}/notes",
                           json={"note": "   "}, headers=admin_headers)
    assert response.status_code == 422


def test_reopen_requires_a_reason(client, admin_headers, db, sample_application, admin_user):
    incident = _incident(db, sample_application)
    incident_service.resolve_manually(incident, admin_user.id)
    response = client.post(f"/api/incidents/{incident.id}/reopen", json={}, headers=admin_headers)
    assert response.status_code == 422
