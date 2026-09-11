from app.services import server_service


def _enroll(hostname="CMD-HTTP-BOX"):
    return server_service.enroll({"hostname": hostname})


def test_only_admin_can_queue_an_agent_command(client, db, it_manager_headers):
    server, _ = _enroll()
    resp = client.post(f"/api/servers/{server.id}/agent-command", json={"action": "RESTART"},
                        headers=it_manager_headers)
    assert resp.status_code == 403


def test_admin_queues_a_restart_and_the_next_heartbeat_carries_it(client, db, admin_headers):
    server, token = _enroll()
    version, _, _ = server_service.current_agent_release()

    resp = client.post(f"/api/servers/{server.id}/agent-command", json={"action": "RESTART"},
                        headers=admin_headers)
    assert resp.status_code == 200, resp.get_json()

    hb = client.post("/api/servers/heartbeat", json={"server_id": server.id, "cpu_percent": 5,
                                                       "agent_version": version},
                      headers={"X-Agent-Token": token})
    body = hb.get_json()["data"]
    assert body["command"] == {"action": "RESTART"}

    # One-shot: a second heartbeat must not repeat the same command.
    hb2 = client.post("/api/servers/heartbeat", json={"server_id": server.id, "cpu_percent": 5,
                                                        "agent_version": version},
                       headers={"X-Agent-Token": token})
    assert hb2.get_json()["data"]["command"] is None


def test_an_outdated_agent_is_told_to_update_with_no_admin_action(client, db):
    """The whole point: a fleet-wide fix reaches every machine on its own next
    check-in, with nobody clicking anything."""
    server, token = _enroll()

    hb = client.post("/api/servers/heartbeat",
                      json={"server_id": server.id, "cpu_percent": 5, "agent_version": "0.0.1-ancient"},
                      headers={"X-Agent-Token": token})
    body = hb.get_json()["data"]
    assert body["command"]["action"] == "UPDATE"
    assert body["command"]["sha256"]


def test_invalid_action_is_rejected(client, db, admin_headers):
    server, _ = _enroll()
    resp = client.post(f"/api/servers/{server.id}/agent-command", json={"action": "DELETE_EVERYTHING"},
                        headers=admin_headers)
    assert resp.status_code == 422


def test_download_requires_a_valid_agent_token(client, db):
    server, token = _enroll()

    wrong = client.get(f"/api/agent/download?server_id={server.id}",
                        headers={"X-Agent-Token": "not-the-real-token"})
    assert wrong.status_code == 401

    ok = client.get(f"/api/agent/download?server_id={server.id}",
                     headers={"X-Agent-Token": token})
    assert ok.status_code == 200
    assert b"AGENT_VERSION" in ok.data


def test_download_content_matches_the_hash_an_update_command_declares(client, db):
    """What an updating agent actually checks itself against."""
    import hashlib

    server, token = _enroll()
    hb = client.post("/api/servers/heartbeat",
                      json={"server_id": server.id, "agent_version": "0.0.1-ancient"},
                      headers={"X-Agent-Token": token})
    declared_sha256 = hb.get_json()["data"]["command"]["sha256"]

    downloaded = client.get(f"/api/agent/download?server_id={server.id}",
                             headers={"X-Agent-Token": token}).data
    assert hashlib.sha256(downloaded).hexdigest() == declared_sha256
