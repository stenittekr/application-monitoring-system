"""Remote-support sessions (screen + input, once Phase 2 lands) must not cross
the network in plaintext - these lock in that platform_service.py enforces
TLS by default and only runs without it when explicitly told to."""
import threading
import time

import pytest
import requests

from platform_service import _build_server


def _run(server):
    """Starts a real cheroot server on a background thread and gives it a
    moment to bind - a live handshake is the only way to actually prove the
    certificate wiring works, not just that it imports."""
    threading.Thread(target=server.start, daemon=True).start()
    time.sleep(0.5)


def test_serves_https_with_a_real_certificate(app):
    server, tls = _build_server(app, "127.0.0.1", 8543)
    assert tls is True
    _run(server)
    try:
        resp = requests.get("https://127.0.0.1:8543/api/health", verify=False, timeout=5)
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ok"
    finally:
        server.stop()


def test_refuses_to_start_without_a_certificate_or_explicit_opt_out(app, monkeypatch):
    monkeypatch.setenv("TLS_CERT_FILE", "nope.pem")
    monkeypatch.setenv("TLS_KEY_FILE", "nope-key.pem")
    monkeypatch.delenv("ALLOW_PLAINTEXT", raising=False)
    with pytest.raises(RuntimeError, match="TLS certificate"):
        _build_server(app, "127.0.0.1", 8544)


def test_allow_plaintext_opts_out_explicitly(app, monkeypatch):
    monkeypatch.setenv("TLS_CERT_FILE", "nope.pem")
    monkeypatch.setenv("TLS_KEY_FILE", "nope-key.pem")
    monkeypatch.setenv("ALLOW_PLAINTEXT", "1")
    server, tls = _build_server(app, "127.0.0.1", 8545)
    assert tls is False
    _run(server)
    try:
        resp = requests.get("http://127.0.0.1:8545/api/health", timeout=5)
        assert resp.status_code == 200
    finally:
        server.stop()
