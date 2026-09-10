"""Why is this application not working - answered as a chain, not a status.

UP and DOWN are verdicts. They do not say whether the name resolves, whether
anything is listening, whether the page came back as the application or as an
error, or whether the machine it lives on is even reporting. Every one of those
has a different fix and a different person to call, and the platform already
holds most of the evidence.

So this walks the same path a request does, in order, and stops being useful the
moment it lies - each step reports what it found and whether the next step is
still worth trying:

    name -> address -> something listening -> it answers -> it answers as itself

then adds what is known about the machine underneath: is its agent reporting, is
the process actually listening, which database is it talking to.

Read-only and on demand. The monitoring cycle is not the place for this - it
runs five probes per application and nobody needs that every 60 seconds.
"""
import json
import socket
import time
from urllib.parse import urlparse

import requests

from app.utils.redaction import redact

DNS_TIMEOUT_SECONDS = 5
CONNECT_TIMEOUT_SECONDS = 5
HTTP_TIMEOUT_SECONDS = 15
MAX_BODY_INSPECTED = 200_000

OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"


def _json_column(raw):
    """A stored JSON list, or an empty one. Malformed text is not worth raising over."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _step(name, state, detail, **extra):
    return {"step": name, "state": state, "detail": detail, **extra}


def _target(application):
    """(host, port, scheme) from whichever field this check type uses."""
    if application.health_check_type == "TCP":
        return (application.server or "").strip(), application.port, None
    parsed = urlparse(application.url or "")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port, parsed.scheme


def diagnose(application, server=None):
    """Returns the chain plus what is known about the host. Never raises."""
    steps = []
    host, port, scheme = _target(application)

    if application.health_check_type == "DATABASE":
        # A DSN is not a URL and its host is not always reachable by name from
        # here. Saying so beats running four probes against a parsed guess.
        return {"steps": [_step("target", SKIPPED,
                                "Database checks connect through a driver; the chain below "
                                "does not apply. The check's own error message is the evidence.")],
                "host": _host_facts(application, server)}

    if not host:
        return {"steps": [_step("target", FAILED, "No host or URL is configured for this check.")],
                "host": _host_facts(application, server)}

    # --- does the name resolve ---------------------------------------------
    address = None
    try:
        socket.setdefaulttimeout(DNS_TIMEOUT_SECONDS)
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        addresses = sorted({info[4][0] for info in infos})
        address = addresses[0]
        detail = f"{host} resolves to {', '.join(addresses)}"
        # An IP literal did not resolve, it just is. Saying "resolves to
        # itself" invites someone to go and check DNS for no reason.
        steps.append(_step("dns", OK, detail if address != host else f"{host} is a literal address",
                           addresses=addresses))
    except socket.gaierror as exc:
        steps.append(_step("dns", FAILED,
                           f"{host} does not resolve ({exc.strerror or exc}). "
                           "This is DNS or a typo in the hostname, not the application."))
        return {"steps": steps, "host": _host_facts(application, server)}
    except Exception as exc:  # noqa: BLE001 - a broken probe is not an outage
        steps.append(_step("dns", FAILED, f"could not resolve {host}: {exc}"))
        return {"steps": steps, "host": _host_facts(application, server)}
    finally:
        socket.setdefaulttimeout(None)

    # --- is anything listening ---------------------------------------------
    began = time.perf_counter()
    try:
        with socket.create_connection((address, port), timeout=CONNECT_TIMEOUT_SECONDS):
            steps.append(_step("tcp", OK, f"{address}:{port} accepted a connection in "
                                          f"{int((time.perf_counter() - began) * 1000)} ms"))
    except socket.timeout:
        steps.append(_step("tcp", FAILED,
                           f"{address}:{port} did not answer within {CONNECT_TIMEOUT_SECONDS}s. "
                           "A firewall dropping the packet looks like this; so does a machine "
                           "that is switched off."))
        return {"steps": steps, "host": _host_facts(application, server)}
    except OSError as exc:
        steps.append(_step("tcp", FAILED,
                           f"{address}:{port} refused the connection ({exc.strerror or exc}). "
                           "The host is up and nothing is listening on that port - usually the "
                           "application is not running, or is bound to 127.0.0.1 only."))
        return {"steps": steps, "host": _host_facts(application, server)}

    if application.health_check_type == "TCP":
        return {"steps": steps, "host": _host_facts(application, server)}

    # --- does it answer, and as itself -------------------------------------
    try:
        began = time.perf_counter()
        response = requests.get(application.url, timeout=HTTP_TIMEOUT_SECONDS,
                                allow_redirects=True, verify=application.verify_ssl)
        elapsed = int((time.perf_counter() - began) * 1000)
        expected = application.expected_status_code or 200
        state = OK if response.status_code == expected else FAILED
        detail = f"HTTP {response.status_code} in {elapsed} ms (expected {expected})"
        if response.history:
            detail += f", after {len(response.history)} redirect(s) to {response.url}"
        steps.append(_step("http", state, detail, status_code=response.status_code,
                           response_time_ms=elapsed))

        body = response.text[:MAX_BODY_INSPECTED].lower()
        needle = (application.expect_contains or "").strip()
        forbidden = (application.expect_absent or "").strip()
        if not needle and not forbidden:
            steps.append(_step("content", SKIPPED,
                               "No content rule is set, so a maintenance page or a login screen "
                               "would still count as healthy. Set one on the application."))
        elif needle and needle.lower() not in body:
            steps.append(_step("content", FAILED,
                               f"the page answered but did not contain '{needle}' - something "
                               "is serving on this port, but not this application"))
        elif forbidden and forbidden.lower() in body:
            steps.append(_step("content", FAILED,
                               f"the page contained '{forbidden}'"))
        else:
            steps.append(_step("content", OK, "the page says what it should"))
    except requests.exceptions.SSLError as exc:
        steps.append(_step("http", FAILED, f"TLS failed: {redact(str(exc))}"))
    except requests.exceptions.Timeout:
        steps.append(_step("http", FAILED,
                           f"connected, but no response within {HTTP_TIMEOUT_SECONDS}s. The "
                           "port is open and the application is not answering - usually "
                           "a hung worker or a database it cannot reach."))
    except Exception as exc:  # noqa: BLE001
        steps.append(_step("http", FAILED, redact(str(exc))))

    return {"steps": steps, "host": _host_facts(application, server)}


def _host_facts(application, server):
    """What the agent knows about the machine this application is meant to run on."""
    if not application.hosted_on_server_id:
        return {"known": False,
                "detail": "No server is recorded for this application, so nothing can be said "
                          "about the machine it runs on. Set \"Hosted on\" when editing it."}
    if not server:
        return {"known": False, "detail": "The recorded server no longer exists."}

    facts = {
        "known": True,
        "hostname": server.hostname,
        "server_status": server.current_status,
        "agent_version": server.agent_version,
        "last_heartbeat_at": server.last_heartbeat_at.isoformat() if server.last_heartbeat_at else None,
    }

    _, port, _ = _target(application)
    # These columns are stored as JSON text and only parsed in to_dict; there is
    # no model property for them, unlike disk_usage and database_links.
    ports = _json_column(server.discovered_ports_json)
    processes = _json_column(server.discovered_processes_json)

    listener = next((row for row in ports
                     if row.get("port") == port and row.get("protocol") == "TCP" and row.get("pid")),
                    None)
    if listener:
        process = next((p for p in processes if p.get("pid") == listener["pid"]), None)
        facts["process"] = {
            "pid": listener["pid"],
            "name": (process or {}).get("name"),
            "script": (process or {}).get("script"),
            "memory_mb": (process or {}).get("memory_mb"),
        }
        facts["databases"] = [link for link in (server.database_links or [])
                              if link.get("pid") == listener["pid"]]
    else:
        # The distinction matters: a silent agent means we do not know, and an
        # agent reporting no listener means we do know, and the answer is no.
        facts["process"] = None
        facts["databases"] = []
        facts["process_detail"] = (
            "The agent is not reporting, so whether the process is running is unknown."
            if server.current_status in ("AGENT_DOWN", "DOWN", "UNKNOWN")
            else f"The agent reports nothing listening on port {port} - the application "
                 "is not running on this machine.")
    return facts
