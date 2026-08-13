"""
Real agent, v0.2 - enrolls a machine once, then heartbeats its CPU/RAM/disk
every interval. Can run from a terminal (dev/testing) or as a Windows Service
(see agent_service.py) for unattended, auto-starting operation.

Usage (dev/manual):
  python agent.py enroll --admin-token <JWT> --api http://127.0.0.1:5000/api
      -> enrolls this machine and writes C:\\ProgramData\\AMNS-Agent\\config.json
  python agent.py run
      -> reads that config file and starts heartbeating (Ctrl+C to stop)

  python agent.py run --server-id <id> --token <secret> --api <url>
      -> bypasses the config file entirely, for quick one-off testing
"""
import argparse
import json
import os
import platform
import socket
import time
from datetime import datetime, timezone

import psutil
import requests

import agent_config

AGENT_VERSION = "0.2.0"

# A heartbeat that fails to send is queued locally rather than dropped, so a
# blip in backend/network availability doesn't silently lose evidence that
# the agent was alive and trying. Bounded so a prolonged outage can't grow
# this file forever; anything older than the max age is stale enough
# (liveness-wise) that sending it late would be misleading, so it's dropped.
QUEUE_MAX_ENTRIES = 50
QUEUE_MAX_AGE_SECONDS = 24 * 3600


def _discover_services():
    """Lists running services. Returns [] rather than raising if unsupported/denied
    - a discovery gap must show as empty, never crash the whole heartbeat."""
    services = []
    if platform.system() != "Windows":
        return services
    for svc in psutil.win_service_iter():
        try:
            info = svc.as_dict()
            services.append({"name": info["name"], "display_name": info["display_name"], "status": info["status"]})
        except Exception:
            continue  # one bad service entry (a known psutil quirk) never blocks the rest
    return services


def _discover_ports():
    """Lists listening TCP/UDP ports and their owning process, where visible."""
    ports = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != "LISTEN" and conn.type.name != "SOCK_DGRAM":
                continue
            proc_name = None
            if conn.pid:
                try:
                    proc_name = psutil.Process(conn.pid).name()
                except Exception:
                    proc_name = None
            ports.append({
                "port": conn.laddr.port if conn.laddr else None,
                "protocol": "UDP" if conn.type.name == "SOCK_DGRAM" else "TCP",
                "pid": conn.pid,
                "process_name": proc_name,
            })
    except Exception:
        pass
    return ports


def collect_metrics():
    """Gathers the current CPU/RAM/disk/uptime/discovery snapshot - never raises,
    degrades to None/[] per field so one failing collector never blocks the rest."""
    def safe(fn):
        try:
            return fn()
        except Exception:
            return None

    return {
        "cpu_percent": safe(lambda: psutil.cpu_percent(interval=1)),
        "ram_percent": safe(lambda: psutil.virtual_memory().percent),
        "disk_percent": safe(lambda: psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/").percent),
        "uptime_seconds": safe(lambda: int(time.time() - psutil.boot_time())),
        "agent_version": AGENT_VERSION,
        "discovered_services": safe(_discover_services) or [],
        "discovered_ports": safe(_discover_ports) or [],
    }


def enroll(api, admin_token, interval=60, config_path=agent_config.DEFAULT_CONFIG_PATH):
    """One-time: registers this machine and writes its id + secret to the
    config file (locked down, see agent_config.save_config) so no human ever
    has to copy-paste the token into a CLI arg or shell history again."""
    payload = {
        "hostname": socket.gethostname(),
        "ip_address": socket.gethostbyname(socket.gethostname()),
        "os_name": platform.system(),
        "os_version": platform.release(),
        "agent_version": AGENT_VERSION,
        "heartbeat_interval_seconds": interval,
    }
    resp = requests.post(f"{api}/servers/enroll", json=payload,
                          headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()["data"]

    agent_config.save_config({
        "api": api,
        "server_id": data["id"],
        "token": data["token"],
        "interval": interval,
    }, path=config_path)

    print("Enrolled successfully.")
    print(f"  server_id = {data['id']}")
    print(f"  config saved to {config_path} (token stored there, not printed again)")


def _queue_path(config_path):
    return os.path.join(os.path.dirname(config_path), "heartbeat_queue.jsonl")


def _load_queue(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _save_queue(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _queue_failed(path, server_id, metrics):
    """Appends a failed heartbeat attempt, trimming to the configured cap."""
    entries = _load_queue(path)
    entries.append({"queued_at": datetime.now(timezone.utc).isoformat(),
                     "server_id": server_id, "metrics": metrics})
    entries = entries[-QUEUE_MAX_ENTRIES:]
    _save_queue(path, entries)


def _flush_queue(api, token, path):
    """Retries queued heartbeats oldest-first, stopping at the first failure
    (later entries stay queued for next cycle). Drops entries stale enough
    that resending them would misrepresent the server's current state."""
    entries = _load_queue(path)
    if not entries:
        return
    now = datetime.now(timezone.utc)
    remaining = []
    for entry in entries:
        queued_at = datetime.fromisoformat(entry["queued_at"])
        age = (now - queued_at).total_seconds()
        if age > QUEUE_MAX_AGE_SECONDS:
            continue  # too stale to usefully resend
        if remaining:
            remaining.append(entry)  # a previous entry this cycle already failed to send
            continue
        ok, _ = send_heartbeat(api, entry["server_id"], token, entry["metrics"])
        if not ok:
            remaining.append(entry)
    _save_queue(path, remaining)


def send_heartbeat(api, server_id, token, metrics):
    """Posts one heartbeat. Returns (ok, message) - never raises, so callers
    (the live loop and the queue flush) can both treat failure as data, not
    an exception to handle."""
    try:
        resp = requests.post(
            f"{api}/servers/heartbeat",
            json={"server_id": server_id, **metrics},
            headers={"X-Agent-Token": token},
            timeout=10,
        )
        if resp.ok:
            return True, "ok"
        return False, f"{resp.status_code} {resp.text}"
    except requests.exceptions.RequestException as exc:
        return False, str(exc)


def run(api, server_id, token, interval, config_path=agent_config.DEFAULT_CONFIG_PATH, stop_event=None):
    """Heartbeat loop: flush any queued failures, collect metrics, send,
    sleep, repeat. Runs until stop_event is set (Windows Service stop) or
    forever (Ctrl+C) when stop_event is None."""
    queue_path = _queue_path(config_path)
    print(f"Agent {AGENT_VERSION} starting. Heartbeat every {interval}s.")
    while stop_event is None or not stop_event.is_set():
        _flush_queue(api, token, queue_path)

        metrics = collect_metrics()
        ok, message = send_heartbeat(api, server_id, token, metrics)
        if ok:
            print(f"[heartbeat OK] cpu={metrics['cpu_percent']}% ram={metrics['ram_percent']}% "
                  f"disk={metrics['disk_percent']}% "
                  f"services={len(metrics['discovered_services'])} ports={len(metrics['discovered_ports'])}")
        else:
            print(f"[heartbeat FAILED - queued, will retry next cycle] {message}")
            _queue_failed(queue_path, server_id, metrics)

        if stop_event is not None:
            stop_event.wait(interval)
        else:
            time.sleep(interval)


def run_from_config(config_path=agent_config.DEFAULT_CONFIG_PATH, stop_event=None):
    """Entry point used by the Windows Service wrapper - everything it needs
    comes from the config file, never a CLI arg."""
    config = agent_config.load_config(config_path)
    run(config["api"], config["server_id"], config["token"], config.get("interval", 60),
        config_path=config_path, stop_event=stop_event)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_enroll = sub.add_parser("enroll")
    p_enroll.add_argument("--admin-token", required=True)
    p_enroll.add_argument("--api", default="http://127.0.0.1:5000/api")
    p_enroll.add_argument("--interval", default=60, type=int)
    p_enroll.add_argument("--config", default=agent_config.DEFAULT_CONFIG_PATH)

    p_run = sub.add_parser("run")
    p_run.add_argument("--config", default=agent_config.DEFAULT_CONFIG_PATH)
    p_run.add_argument("--server-id", type=int, help="Bypasses the config file for quick manual testing")
    p_run.add_argument("--token", help="Bypasses the config file for quick manual testing")
    p_run.add_argument("--api", default="http://127.0.0.1:5000/api")
    p_run.add_argument("--interval", default=60, type=int)

    args = parser.parse_args()
    if args.command == "enroll":
        enroll(args.api, args.admin_token, args.interval, args.config)
    else:
        if args.server_id and args.token:
            run(args.api, args.server_id, args.token, args.interval, config_path=args.config)
        else:
            run_from_config(args.config)
