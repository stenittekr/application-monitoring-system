"""
Real agent, v0.1 - enrolls this machine once, then heartbeats its CPU/RAM/disk
every interval. Not yet packaged as a Windows service; run it in a terminal
for now (Task Scheduler "run at startup" comes once this is proven).

Usage:
  python agent.py enroll --admin-token <JWT> --api http://127.0.0.1:5000/api
  python agent.py run    --server-id <id> --token <secret> --api http://127.0.0.1:5000/api
"""
import argparse
import json
import platform
import socket
import time

import psutil
import requests

AGENT_VERSION = "0.1.0"


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


def enroll(api, admin_token):
    """One-time: registers this machine and prints the id + secret to save for `run`."""
    payload = {
        "hostname": socket.gethostname(),
        "ip_address": socket.gethostbyname(socket.gethostname()),
        "os_name": platform.system(),
        "os_version": platform.release(),
        "agent_version": AGENT_VERSION,
        "heartbeat_interval_seconds": 60,
    }
    resp = requests.post(f"{api}/servers/enroll", json=payload,
                          headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()["data"]
    print("Enrolled successfully. SAVE THESE - the token is shown only once:")
    print(f"  server_id = {data['id']}")
    print(f"  token     = {data['token']}")


def run(api, server_id, token, interval):
    """Heartbeat loop: collect metrics, POST them, sleep, repeat - forever."""
    print(f"Agent {AGENT_VERSION} starting. Heartbeat every {interval}s. Ctrl+C to stop.")
    while True:
        metrics = collect_metrics()
        try:
            resp = requests.post(
                f"{api}/servers/heartbeat",
                json={"server_id": server_id, **metrics},
                headers={"X-Agent-Token": token},
                timeout=10,
            )
            if resp.ok:
                print(f"[heartbeat OK] cpu={metrics['cpu_percent']}% ram={metrics['ram_percent']}% "
                      f"disk={metrics['disk_percent']}% "
                      f"services={len(metrics['discovered_services'])} ports={len(metrics['discovered_ports'])}")
            else:
                print(f"[heartbeat REJECTED] {resp.status_code} {resp.text}")
        except requests.exceptions.RequestException as exc:
            print(f"[heartbeat FAILED - will retry next cycle] {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_enroll = sub.add_parser("enroll")
    p_enroll.add_argument("--admin-token", required=True)
    p_enroll.add_argument("--api", default="http://127.0.0.1:5000/api")

    p_run = sub.add_parser("run")
    p_run.add_argument("--server-id", required=True, type=int)
    p_run.add_argument("--token", required=True)
    p_run.add_argument("--api", default="http://127.0.0.1:5000/api")
    p_run.add_argument("--interval", default=15, type=int)

    args = parser.parse_args()
    if args.command == "enroll":
        enroll(args.api, args.admin_token)
    else:
        run(args.api, args.server_id, args.token, args.interval)
