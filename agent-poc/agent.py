"""
Real agent, v0.3 - enrolls a machine once, then heartbeats its CPU/RAM/disk,
plus discovered services, listening ports, running processes and installed programs,
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
import csv
import io
import json
import os
import platform
import socket
import subprocess
import time
from datetime import datetime, timezone

import psutil
import requests

import agent_config

AGENT_VERSION = "0.7.0"

# A heartbeat that fails to send is queued locally rather than dropped, so a
# blip in backend/network availability doesn't silently lose evidence that
# the agent was alive and trying. Bounded so a prolonged outage can't grow
# this file forever; anything older than the max age is stale enough
# (liveness-wise) that sending it late would be misleading, so it's dropped.
QUEUE_MAX_ENTRIES = 50
QUEUE_MAX_AGE_SECONDS = 24 * 3600


def _os_details():
    """Operating system name, a readable version, and the architecture.

    platform.release() alone gives "11" or "2022Server", which does not say
    which build or edition, and on Linux says nothing useful at all. This keeps
    the coarse family (Windows / Linux / Darwin) for grouping and adds a human
    string alongside it.
    """
    system = platform.system() or "Unknown"
    version, edition = platform.release(), None
    try:
        if system == "Windows":
            release, build, csd, _ptype = platform.win32_ver()
            try:
                edition = platform.win32_edition()          # 3.8+, absent on some builds
            except AttributeError:
                edition = None
            version = f"{release} (build {build})" if build else release
            if csd and csd.lower() != "servicepack 0":
                version = f"{version} {csd}"
        elif system == "Linux":
            # /etc/os-release is the standard across distributions.
            fields = {}
            with open("/etc/os-release", "r", encoding="utf-8") as handle:
                for line in handle:
                    if "=" in line:
                        key, _, value = line.partition("=")
                        fields[key.strip()] = value.strip().strip('"')
            edition = fields.get("ID")
            version = fields.get("PRETTY_NAME") or platform.release()
        elif system == "Darwin":
            version = f"macOS {platform.mac_ver()[0]}"
    except Exception:
        pass  # a thin answer beats no heartbeat
    return system, version, edition


def _ip_addresses():
    """Every non-loopback IPv4/IPv6 address, so a machine with several NICs is
    not reduced to whichever one gethostbyname happened to return."""
    addresses = []
    try:
        families = {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family in families and addr.address:
                    ip = addr.address.split("%")[0]
                    # Loopback, IPv4 link-local (APIPA - an adapter that failed
                    # to get a lease) and IPv6 link-local are not addresses
                    # anything reaches this machine on, and there are usually
                    # more of them than real ones.
                    if ip.startswith(("127.", "::1", "169.254.", "fe80:", "FE80:")):
                        continue
                    addresses.append({"interface": interface, "family": families[addr.family], "address": ip})
    except Exception:
        pass
    return addresses


def _domain():
    """AD domain or workgroup, where the OS exposes it."""
    try:
        if platform.system() == "Windows":
            return os.environ.get("USERDNSDOMAIN") or os.environ.get("USERDOMAIN")
        fqdn = socket.getfqdn()
        return fqdn.split(".", 1)[1] if "." in fqdn else None
    except Exception:
        return None


def collect_identity():
    """Server identity, sent with every heartbeat rather than only at enrolment.

    §7.2 asks for hostname, OS/version, IP addresses, domain and hardware
    summary. Enrolment-only meant a machine that was upgraded, renamed or given
    a new address kept reporting whatever was true on the day it enrolled - the
    IP on record here was three DHCP leases out of date.
    """
    system, version, edition = _os_details()
    return {
        "hostname": socket.gethostname(),
        "os_name": system,
        "os_version": version,
        "os_edition": edition,
        "os_architecture": platform.machine() or None,
        "domain": _domain(),
        "cpu_model": (platform.processor() or None),
        "ip_addresses": _ip_addresses(),
    }


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


# Processes whose *arguments* are the interesting part - "python.exe" alone
# tells you nothing about which of your scripts is running.
_INTERPRETERS = ("python", "pythonw", "node", "java", "php", "ruby", "perl", "powershell", "pwsh")

# ponytail: cap the per-heartbeat process list. A busy server has 200-400
# processes and this ships every 60s; interpreters are always kept, the rest is
# filled by memory. Raise it if something interesting hides below the cut.
MAX_PROCESSES = 150


def _is_inline_code_flag(flag):
    """True for flags whose value is code rather than a script path.

    Case-insensitive and prefix-tolerant on purpose: PowerShell writes
    "-command" in lower case and accepts any unambiguous abbreviation, so
    matching a literal "-Command" leaked VS Code's inline startup script into
    the reported inventory. Over-matching here only hides a script name;
    under-matching ships arbitrary code, which may carry credentials."""
    name = flag.lstrip("-/").lower()
    return bool(name) and any(
        full.startswith(name) for full in ("command", "encodedcommand")
    )


def _script_for(info):
    """Returns the script an interpreter process is running, or None.

    Only the script path is taken - never the full command line. Flags routinely
    carry passwords and tokens, and this value gets stored server-side and shown
    in the dashboard, so the whole argv must not travel with it.
    """
    name = (info.get("name") or "").lower()
    if not any(name.startswith(prefix) for prefix in _INTERPRETERS):
        return None
    previous = None
    for arg in (info.get("cmdline") or [])[1:]:
        if arg.startswith("-"):
            previous = arg
            continue  # skip flags like -m / -u to reach the script or module
        # -c/-e take inline code as their value. That code is not a script name
        # and can contain anything, secrets included, so it must not be sent.
        if previous and _is_inline_code_flag(previous):
            return f"{previous} (inline code)"
        return arg[:260]
    return None


# Where Windows records installed software: the 64-bit and 32-bit (WOW) hives
# plus per-user installs, which is how Programs and Features builds its list.
_UNINSTALL_KEYS = (
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)


def _discover_programs():
    """Lists installed programs - the same inventory Programs and Features shows.

    Read straight from the registry with stdlib winreg: no extra dependency, and
    no WMI (Win32_Product is slow and triggers an MSI self-repair per row)."""
    if platform.system() != "Windows":
        return []
    import winreg

    roots = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    seen = {}
    for root_name, path in _UNINSTALL_KEYS:
        try:
            with winreg.OpenKey(roots[root_name], path) as parent:
                for index in range(winreg.QueryInfoKey(parent)[0]):
                    try:
                        with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as entry:
                            def value(name):
                                try:
                                    return winreg.QueryValueEx(entry, name)[0]
                                except OSError:
                                    return None

                            display_name = value("DisplayName")
                            # Programs and Features hides system components and
                            # update entries; match it or the list is unreadable.
                            if not display_name or value("SystemComponent") or value("ParentKeyName"):
                                continue
                            seen[(display_name, value("DisplayVersion"))] = {
                                "name": display_name,
                                "version": value("DisplayVersion"),
                                "publisher": value("Publisher"),
                                "installed_on": value("InstallDate"),
                            }
                    except OSError:
                        continue  # unreadable entry - skip it, never fail the batch
        except OSError:
            continue  # hive absent (e.g. no WOW node on 32-bit) - not an error
    return sorted(seen.values(), key=lambda item: (item["name"] or "").lower())


def _discover_processes():
    """Lists running processes, with the script name for interpreters.

    Same contract as the other discovery helpers: returns [] rather than raising,
    because a discovery gap must never take the heartbeat down with it."""
    processes = []
    try:
        for proc in psutil.process_iter(["pid", "name", "username", "memory_info", "cmdline"]):
            try:
                info = proc.info
                memory = info.get("memory_info")
                processes.append({
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "user": info.get("username"),
                    "memory_mb": round((memory.rss if memory else 0) / (1024 * 1024), 1),
                    "script": _script_for(info),
                })
            except Exception:
                continue  # process died mid-iteration, or access denied - skip it
    except Exception:
        return processes

    # Keep every interpreter process regardless of size (that is the whole point
    # of this list), then spend what is left of the cap on the biggest others.
    scripted = [p for p in processes if p["script"]]
    others = sorted((p for p in processes if not p["script"]),
                    key=lambda p: p["memory_mb"], reverse=True)
    return scripted + others[: max(0, MAX_PROCESSES - len(scripted))]


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


# --- FR-008: network, per-core and hardware -------------------------------

def _network_counters():
    """Interface state and cumulative traffic, errors and drops.

    Counters are cumulative since boot, not rates. The platform turns them into
    rates by differencing consecutive heartbeats, which is the only place that
    knows how far apart they were - the agent would have to keep state it does
    not otherwise need and would lose on every restart.
    """
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    interfaces = []
    for name, stat in stats.items():
        if name.lower().startswith(("loopback", "lo")):
            continue
        io = counters.get(name)
        interfaces.append({
            "name": name,
            "up": bool(stat.isup),
            "speed_mbps": stat.speed or None,      # 0 means "not reported"
            "bytes_sent": getattr(io, "bytes_sent", None),
            "bytes_recv": getattr(io, "bytes_recv", None),
            "errors": (getattr(io, "errin", 0) + getattr(io, "errout", 0)) if io else None,
            "drops": (getattr(io, "dropin", 0) + getattr(io, "dropout", 0)) if io else None,
        })
    return interfaces


def _per_core_cpu():
    """Utilisation per logical core.

    An overall 25% across eight cores hides one core pinned at 100%, which is
    exactly what a single-threaded process maxing out looks like from outside.
    """
    return psutil.cpu_percent(interval=None, percpu=True)


def _hardware_health():
    """Temperature, fans and battery, where the OS exposes them at all.

    Section 8 is explicit that these are frequently unavailable - a virtual
    machine exposes almost none of it - and that the platform must show
    "Not available" rather than a comfortable zero. An absent key means
    exactly that, which is why nothing is defaulted here.
    """
    health = {}
    try:
        temps = psutil.sensors_temperatures()
        readings = [t.current for group in temps.values() for t in group if t.current]
        if readings:
            health["temperature_c"] = round(max(readings), 1)
    except (AttributeError, OSError):
        pass
    try:
        fans = psutil.sensors_fans()
        speeds = [f.current for group in fans.values() for f in group if f.current]
        if speeds:
            health["fan_rpm"] = max(speeds)
    except (AttributeError, OSError):
        pass
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            health["battery_percent"] = round(battery.percent)
            health["on_mains"] = bool(battery.power_plugged)
    except (AttributeError, OSError):
        pass
    return health


def _disk_volumes():
    """Every fixed volume, not only the system drive.

    A full D: stops an application just as effectively as a full C:, and the
    system drive is often the one with room to spare.
    """
    volumes = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        volumes.append({
            "mount": part.mountpoint,
            "fstype": part.fstype,
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "used_percent": usage.percent,
        })
    return volumes


# --- FR-009: scheduled tasks and containers -------------------------------

MAX_TASKS = 60


def _discover_scheduled_tasks():
    """Enabled scheduled tasks, with last result and next run time.

    Parses the CSV output of schtasks rather than using the COM interface: it
    needs no extra dependency, and a task list is not worth a pywin32 import
    that could fail on a machine where everything else works.

    Microsoft's own tasks are skipped. There are several hundred and nobody
    monitors them.
    """
    if platform.system() != "Windows":
        return []
    try:
        out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/v"],
                             capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0 or not out.stdout:
        return []

    tasks = []
    for row in csv.DictReader(io.StringIO(out.stdout)):
        name = (row.get("TaskName") or "").strip()
        if not name or name.lower().startswith("\\microsoft\\"):
            continue
        if (row.get("Scheduled Task State") or "").strip().lower() != "enabled":
            continue
        tasks.append({
            "name": name,
            "status": (row.get("Status") or "").strip(),
            "last_run": (row.get("Last Run Time") or "").strip(),
            "last_result": (row.get("Last Result") or "").strip(),
            "next_run": (row.get("Next Run Time") or "").strip(),
        })
        if len(tasks) >= MAX_TASKS:
            break
    return tasks


def _discover_containers():
    """Running containers, if this machine runs any.

    Returns an empty list both when Docker is absent and when it is present
    with nothing running. The platform tells those apart by whether a person
    said this host should be running containers - not by guessing from silence.
    """
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Image}}|{{.Status}}"],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []          # no Docker on this machine
    if out.returncode != 0:
        return []
    containers = []
    for line in out.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            containers.append({"name": parts[0], "image": parts[1], "status": parts[2]})
    return containers


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
        # The totals the percentages are percentages OF. "61%" is not actionable
        # on its own - 61% of 4 GB and 61% of 128 GB are different problems.
        "cpu_cores": safe(lambda: psutil.cpu_count(logical=True)),
        "ram_total_mb": safe(lambda: round(psutil.virtual_memory().total / (1024 ** 2))),
        "disk_total_gb": safe(lambda: round(
            psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/").total / (1024 ** 3), 1)),
        "agent_version": AGENT_VERSION,
        **(safe(collect_identity) or {}),
        "discovered_services": safe(_discover_services) or [],
        "discovered_ports": safe(_discover_ports) or [],
        "discovered_processes": safe(_discover_processes) or [],
        # ponytail: re-sent every heartbeat. Installed software changes rarely, so
        # this is redundant traffic - send only on change if payload ever matters.
        "discovered_programs": safe(_discover_programs) or [],
        "network_interfaces": safe(_network_counters) or [],
        "cpu_per_core": safe(_per_core_cpu) or [],
        "hardware": safe(_hardware_health) or {},
        "disk_volumes": safe(_disk_volumes) or [],
        "scheduled_tasks": safe(_discover_scheduled_tasks) or [],
        "containers": safe(_discover_containers) or [],
        # Section 19, "clock incorrect": the agent states when it thinks it sent
        # this, and the platform compares that with its own clock. Without it an
        # agent with a wrong clock silently reorders an incident timeline.
        "agent_time": datetime.now(timezone.utc).isoformat(),
    }


def enroll(api, admin_token, interval=60, config_path=agent_config.DEFAULT_CONFIG_PATH):
    """One-time: registers this machine and writes its id + secret to the
    config file (locked down, see agent_config.save_config) so no human ever
    has to copy-paste the token into a CLI arg or shell history again."""
    payload = {
        **collect_identity(),
        "ip_address": socket.gethostbyname(socket.gethostname()),
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


def _reload(config_path, api, server_id, token, interval):
    """Re-reads the config each cycle so a change takes effect without a restart.

    The hub address moved four times in a week; each move meant a remote session
    as Administrator on every server just to edit one line. Reading a 3KB file
    once a minute, next to a heartbeat that already crosses the network, costs
    nothing worth counting.

    A half-written or malformed file keeps the previous values: the agent going
    quiet is precisely the failure this is meant to prevent.
    """
    try:
        cfg = agent_config.load_config(config_path)
        new = (cfg["api"], cfg["server_id"], cfg["token"], cfg.get("interval", 60))
    except Exception as exc:  # noqa: BLE001 - keep running on the last good config
        print(f"[config unreadable, keeping previous] {exc}")
        return api, server_id, token, interval
    if new[0] != api:
        print(f"[config changed] hub {api} -> {new[0]}")
    if new[3] != interval:
        print(f"[config changed] interval {interval}s -> {new[3]}s")
    return new


def run(api, server_id, token, interval, config_path=agent_config.DEFAULT_CONFIG_PATH, stop_event=None):
    """Heartbeat loop: flush any queued failures, collect metrics, send,
    sleep, repeat. Runs until stop_event is set (Windows Service stop) or
    forever (Ctrl+C) when stop_event is None."""
    queue_path = _queue_path(config_path)
    print(f"Agent {AGENT_VERSION} starting. Heartbeat every {interval}s.")
    while stop_event is None or not stop_event.is_set():
        api, server_id, token, interval = _reload(config_path, api, server_id, token, interval)
        _flush_queue(api, token, queue_path)

        metrics = collect_metrics()
        ok, message = send_heartbeat(api, server_id, token, metrics)
        if ok:
            print(f"[heartbeat OK] cpu={metrics['cpu_percent']}% ram={metrics['ram_percent']}% "
                  f"disk={metrics['disk_percent']}% "
                  f"services={len(metrics['discovered_services'])} ports={len(metrics['discovered_ports'])} "
                  f"processes={len(metrics['discovered_processes'])} "
                  f"programs={len(metrics['discovered_programs'])}")
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
