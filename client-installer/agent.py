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
import hashlib
import io
import json
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import psutil
import requests

import agent_config

AGENT_VERSION = "0.20.0"

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


# Asset identity never changes while the machine is running, so it is read once
# and reused. Across 200 PCs, re-reading the registry and asking WMI for a BIOS
# serial every 60 seconds would be pure waste.
_device_identity = None


def _read_registry(hive_path, value_name):
    """One registry string, or None. Windows only."""
    import winreg

    hive, path = hive_path
    try:
        with winreg.OpenKey(hive, path) as key:
            return str(winreg.QueryValueEx(key, value_name)[0]).strip()
    except OSError:
        return None


def _device_inventory():
    """The identity an asset register needs: what this machine IS (§7.2).

    Everything here is what Windows shows under Settings > System > About, so a
    row in the platform can be matched against a machine by anyone reading its
    screen. Device ID comes from SQMClient MachineId in the registry - not
    the WMI product UUID, which is a different value and does not match.

    Read once per agent start. None of it changes without a reboot, and a
    reboot restarts the agent.
    """
    global _device_identity
    if _device_identity is not None:
        return _device_identity

    identity = {"fqdn": socket.getfqdn() or None}
    if platform.system() == "Windows":
        import winreg

        identity.update({
            "device_id": (_read_registry(
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\SQMClient"), "MachineId")
                or "").strip("{}") or None,
            "product_id": _read_registry(
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"),
                "ProductId"),
            "manufacturer": _read_registry(
                (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS"),
                "SystemManufacturer"),
            "model": _read_registry(
                (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS"),
                "SystemProductName"),
            "bios_version": _read_registry(
                (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS"),
                "BIOSVersion"),
        })
        # The serial is what an asset register is keyed on and the only field
        # here the registry does not carry. One WMI call, once per start.
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-CimInstance Win32_BIOS).SerialNumber"],
                capture_output=True, text=True, timeout=30)
            serial = (out.stdout or "").strip()
            identity["serial_number"] = serial or None
        except Exception:
            identity["serial_number"] = None

    identity["cpu_model"] = platform.processor() or None
    identity["cpu_cores"] = psutil.cpu_count(logical=True)
    identity["ram_total_mb"] = round(psutil.virtual_memory().total / (1024 ** 2))
    identity["system_type"] = platform.machine() or None
    _device_identity = identity
    return identity

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
        "device_inventory": _device_inventory(),
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


# --- what each application is talking to ----------------------------------

# Which engine answers on a port. Not authoritative - anything can listen
# anywhere - but a process holding an ESTABLISHED connection to :1433 is
# talking to SQL Server often enough to be worth saying so.
DATABASE_PORTS = {
    1433: "SQL Server", 1434: "SQL Server", 3306: "MySQL/MariaDB",
    5432: "PostgreSQL", 1521: "Oracle", 27017: "MongoDB", 6379: "Redis",
    50000: "DB2", 3050: "Firebird",
}

# One row per (process, remote endpoint). A busy application opens dozens of
# connections to the same database and they are all the same fact.
MAX_DATABASE_LINKS = 40

# How long a link stays reported after it was last seen open.
#
# A heartbeat samples the socket table once a minute. An application that keeps
# a pooled connection open is caught every time; one that connects, queries and
# closes is caught almost never, and the first version of this reported nothing
# at all for a server plainly running four applications against two databases.
#
# So a link once observed is remembered. "This application talked to that
# database within the last six hours" is the fact worth having, and it does not
# stop being true between two samples.
DATABASE_LINK_RETAIN_SECONDS = 6 * 3600

# How often the socket table is read.
#
# Once per heartbeat was not enough and could not be: a request-scoped
# connection is open for milliseconds, so a sample every 60 seconds misses it
# every time. PS_QAS runs four applications against two local databases and
# reported nothing at all, correctly - there was nothing open at the instant it
# looked. Watching every few seconds catches them.
#
# One syscall plus a name lookup per database connection. Cheap enough to do
# often, not cheap enough to do in the heartbeat, so it runs on its own thread.
DATABASE_SAMPLE_SECONDS = 5

_database_link_history = {}
_database_link_lock = threading.Lock()
_database_sampler_started = False


def _database_connections():
    """Which local process is connected to which database server, right now.

    Answers "which database does this application use" without reading a single
    configuration file. A connection string is a secret; an established socket
    is an observation, and the observation is the one that is actually true -
    a config file lists what was intended, and stale entries in it have sent
    people looking at the wrong database more than once.

    Read-only and local: the agent looks at its own machine's socket table. It
    never connects to the database, never authenticates, and never sees a
    credential.
    """
    _sample_database_connections()
    now = time.time()
    with _database_link_lock:
        ordered = sorted(_database_link_history.values(),
                         key=lambda e: (-e.get("last_seen", 0), -e["connections"]))
        return [dict(entry, seconds_since_seen=int(now - entry.get("last_seen", now)))
                for entry in ordered[:MAX_DATABASE_LINKS]]


def _sample_database_connections():
    """Reads the socket table once and folds what it finds into the history."""
    now = time.time()
    current = {}
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != "ESTABLISHED" or not conn.raddr:
                continue
            engine = DATABASE_PORTS.get(conn.raddr.port)
            if not engine:
                continue
            name = None
            if conn.pid:
                try:
                    name = psutil.Process(conn.pid).name()
                except Exception:
                    name = None
            # Keyed so the same app-to-database pair collapses to one row
            # however many sockets it is holding open.
            key = f"{conn.pid}|{name}|{conn.raddr.ip}|{conn.raddr.port}"
            entry = current.setdefault(key, {
                "pid": conn.pid,
                "process_name": name,
                "local_port": conn.laddr.port if conn.laddr else None,
                "remote_host": conn.raddr.ip,
                "remote_port": conn.raddr.port,
                "engine": engine,
                "connections": 0,
            })
            entry["connections"] += 1
    except Exception:
        # Enumerating sockets can fail; the remembered links are still true.
        current = {}

    with _database_link_lock:
        for key, entry in current.items():
            entry["last_seen"] = now
            entry["open_now"] = True
            _database_link_history[key] = entry
        for key, entry in list(_database_link_history.items()):
            if key not in current:
                entry["open_now"] = False
            if now - entry.get("last_seen", 0) > DATABASE_LINK_RETAIN_SECONDS:
                del _database_link_history[key]


def _database_sampler():
    """Watches the socket table continuously, so short-lived connections are seen."""
    while True:
        try:
            _sample_database_connections()
        except Exception:      # noqa: BLE001 - a failed sample must not end the thread
            pass
        time.sleep(DATABASE_SAMPLE_SECONDS)


def start_database_sampler():
    """Starts the watcher once. Called from the heartbeat loop, not on import."""
    global _database_sampler_started
    with _database_link_lock:
        if _database_sampler_started:
            return
        _database_sampler_started = True
    threading.Thread(target=_database_sampler, daemon=True, name="db-links").start()

# --- FR-008: network, per-core and hardware -------------------------------

# Reachability is measured every few minutes, not every heartbeat: two pings and
# a DNS lookup take seconds, and the answer does not change between one minute
# and the next. A heartbeat that waits on the network to describe the network is
# a heartbeat the platform records as missed.
REACHABILITY_INTERVAL_SECONDS = 300
PING_COUNT = 3

_reachability_cache = {"at": 0.0, "value": {}}


def _default_gateway():
    """The gateway this machine actually routes through, or None."""
    if platform.system() != "Windows":
        return None
    try:
        out = subprocess.run(["route", "print", "0.0.0.0"], capture_output=True,
                             text=True, timeout=20)
    except Exception:
        return None
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        # 0.0.0.0  0.0.0.0  <gateway>  <interface>  <metric>
        if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            return parts[2] if parts[2].lower() != "on-link" else None
    return None


def _ping(target):
    """(latency_ms, packet_loss_percent) for a host, or (None, None)."""
    if not target:
        return None, None
    flag = "-n" if platform.system() == "Windows" else "-c"
    try:
        out = subprocess.run(["ping", flag, str(PING_COUNT), "-w", "2000", str(target)],
                             capture_output=True, text=True, timeout=30)
    except Exception:
        return None, None
    text = out.stdout or ""
    loss = re.search(r"\((\d+)%\s*loss\)", text) or re.search(r"(\d+)%\s*packet loss", text)
    latency = re.search(r"Average\s*=\s*(\d+)ms", text) or re.search(r"= [\d.]+/([\d.]+)/", text)
    return (float(latency.group(1)) if latency else None,
            int(loss.group(1)) if loss else None)


def _network_reachability(api_url=None):
    """DNS, gateway and platform reachability (§8 network).

    Separates three failures that all look like "the application is down" from
    a dashboard: the name does not resolve, the gateway is unreachable, or the
    path to the platform is lossy. Each has a different owner, and a monitoring
    agent that cannot say which is not much help at 3am.
    """
    now = time.monotonic()
    if _reachability_cache["value"] and now - _reachability_cache["at"] < REACHABILITY_INTERVAL_SECONDS:
        return _reachability_cache["value"]

    result = {}
    gateway = _default_gateway()
    result["gateway"] = gateway
    latency, loss = _ping(gateway)
    result["gateway_latency_ms"], result["gateway_packet_loss_percent"] = latency, loss
    result["gateway_reachable"] = None if loss is None else loss < 100

    # DNS is tested against the platform's own hostname - the one name this
    # machine must be able to resolve for monitoring to work at all.
    host = None
    if api_url:
        try:
            from urllib.parse import urlparse
            host = urlparse(api_url).hostname
        except Exception:
            host = None
    if host:
        began = time.perf_counter()
        try:
            socket.getaddrinfo(host, None)
            result["dns_host"] = host
            result["dns_ok"] = True
            result["dns_ms"] = round((time.perf_counter() - began) * 1000, 1)
        except socket.gaierror as exc:
            result.update({"dns_host": host, "dns_ok": False,
                           "dns_error": exc.strerror or str(exc)})
        latency, loss = _ping(host)
        result["platform_latency_ms"], result["platform_packet_loss_percent"] = latency, loss

    _reachability_cache.update({"at": now, "value": result})
    return result

def _disk_io():
    """Per-disk read/write counters (§7.1 "I/O").

    Cumulative since boot, not rates - the same choice as the network counters
    above, and for the same reason: only the platform knows how far apart two
    heartbeats were, and an agent computing rates would keep state it loses on
    every restart.

    Busy time is the one worth watching. A disk at 100% busy makes every
    application on the machine slow while CPU, RAM and free space all look
    perfectly healthy, which is exactly the outage nobody can explain.
    """
    try:
        counters = psutil.disk_io_counters(perdisk=True)
    except Exception:
        return []
    disks = []
    for name, io in (counters or {}).items():
        disks.append({
            "disk": name,
            "read_bytes": getattr(io, "read_bytes", None),
            "write_bytes": getattr(io, "write_bytes", None),
            "read_count": getattr(io, "read_count", None),
            "write_count": getattr(io, "write_count", None),
            # Windows reports these; Linux does on most filesystems. None
            # rather than 0 where it does not - "not measured" is not "idle".
            "read_ms": getattr(io, "read_time", None),
            "write_ms": getattr(io, "write_time", None),
            "busy_ms": getattr(io, "busy_time", None),
        })
    return disks


def _web_sites():
    """IIS sites and application pools (§7.2 "web server sites/application pools").

    Uses appcmd, which ships with IIS: no IIS, no appcmd, empty list - which is
    the correct answer for a machine running Apache or nothing at all.

    A stopped application pool is a genuinely invisible outage. Every service is
    running, the port is listening, and IIS answers 503 for one site while the
    rest of the machine looks perfect.
    """
    if platform.system() != "Windows":
        return []
    appcmd = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                          "system32", "inetsrv", "appcmd.exe")
    if not os.path.exists(appcmd):
        return []

    def _list(kind):
        try:
            out = subprocess.run([appcmd, "list", kind], capture_output=True, text=True,
                                 timeout=20)
        except Exception:
            return []
        rows = []
        for line in (out.stdout or "").splitlines():
            # appcmd prints:  SITE "Default Web Site" (id:1,bindings:http/*:80:,state:Started)
            name = re.search(r'"([^"]+)"', line)
            state = re.search(r"state:(\w+)", line)
            if not name:
                continue
            entry = {"name": name.group(1), "state": state.group(1) if state else None}
            bindings = re.search(r"bindings:([^,)]+)", line)
            if bindings:
                entry["bindings"] = bindings.group(1)
            rows.append(entry)
        return rows

    return [dict(row, kind="site") for row in _list("sites")] +            [dict(row, kind="apppool") for row in _list("apppools")]

def _network_counters():
    """Interface state and cumulative traffic, errors and drops.

    Counters are cumulative since boot, not rates. The platform turns them into
    rates by differencing consecutive heartbeats, which is the only place that
    knows how far apart they were - the agent would have to keep state it does
    not otherwise need and would lose on every restart.
    """
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    addrs = psutil.net_if_addrs()
    interfaces = []
    for name, stat in stats.items():
        if name.lower().startswith(("loopback", "lo")):
            continue
        io = counters.get(name)
        # AF_LINK is the link-layer family psutil reports the hardware (MAC)
        # address under - a fixed identifier a DHCP-leased IP is not, useful
        # for matching a machine against network/switch-port records.
        mac = next((a.address for a in addrs.get(name, []) if a.family == psutil.AF_LINK), None)
        interfaces.append({
            "name": name,
            "mac_address": mac,
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


# --- what is filling the disk (§8 storage) --------------------------------

# A full walk of a 200 GB volume takes minutes. Doing it on every heartbeat
# would make the agent the busiest thing on the server, so it runs rarely and
# the answer is reused in between. Disk usage does not change meaningfully in
# six hours; if it does, that is the alert, not the inventory.
DISK_SCAN_INTERVAL_SECONDS = 6 * 3600

# A hard stop per volume, because some directory somewhere is always
# pathological - a network mount, a deduplicated store, a folder with a million
# files. Per volume rather than shared: the first scan of PS_QAS spent its whole
# allowance on C: and never reached E: at all, which is a confident-looking
# answer to the wrong question.
#
# It can afford to be generous now because the scan no longer runs inside the
# heartbeat. At 90 seconds shared it timed out inside C:\Users and reported
# 0.47 GB for a folder that is plainly larger.
DISK_SCAN_BUDGET_SECONDS = 600

TOP_DIRECTORIES_PER_VOLUME = 8

_disk_usage_cache = {"at": 0.0, "value": []}
_disk_scan_lock = threading.Lock()
_disk_scan_running = False


def _directory_size(path, deadline):
    """Bytes under a directory, stopping when the time budget runs out."""
    total = 0
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            return total, False
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue          # never follow: junctions loop
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue              # locked, vanished, denied
        except OSError:
            continue
    return total, True


def _scan_disks():
    """Walks every fixed volume. Runs on a background thread; never in a heartbeat."""
    results = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        # Each volume gets the whole budget. Sharing one meant the first volume
        # consumed it and the rest were reported as empty, which is worse than
        # not reporting them.
        deadline = time.monotonic() + DISK_SCAN_BUDGET_SECONDS
        folders = []
        try:
            entries = list(os.scandir(part.mountpoint))
        except OSError:
            continue
        for entry in entries:
            if time.monotonic() > deadline:
                break
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            size, complete = _directory_size(entry.path, deadline)
            folders.append({"path": entry.path,
                            "gb": round(size / (1024 ** 3), 2),
                            "complete": complete})
        folders.sort(key=lambda f: f["gb"], reverse=True)
        top = folders[:TOP_DIRECTORIES_PER_VOLUME]

        # One level deeper into the biggest folder. "C:\Users is 80 GB" is where
        # the question starts, not where it ends, and every attempt to answer it
        # by hand ran for minutes and printed one line. The files were just
        # walked, so the directory cache is warm and this is cheap.
        if top:
            children, _ = [], None
            deeper_deadline = time.monotonic() + DISK_SCAN_BUDGET_SECONDS
            try:
                for entry in os.scandir(top[0]["path"]):
                    if time.monotonic() > deeper_deadline:
                        break
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    size, complete = _directory_size(entry.path, deeper_deadline)
                    children.append({"path": entry.path,
                                     "gb": round(size / (1024 ** 3), 2),
                                     "complete": complete})
            except OSError:
                pass
            children.sort(key=lambda f: f["gb"], reverse=True)
            top[0]["children"] = children[:TOP_DIRECTORIES_PER_VOLUME]

        results.append({"mount": part.mountpoint, "folders": top})
        # Published as each volume finishes rather than at the end, so a slow
        # volume cannot hide a fast one that is already answered.
        with _disk_scan_lock:
            _disk_usage_cache["value"] = list(results)
    return results


def _disk_scan_worker():
    global _disk_scan_running
    try:
        value = _scan_disks()
        with _disk_scan_lock:
            _disk_usage_cache["value"] = value
            _disk_usage_cache["at"] = time.monotonic()
    except Exception as exc:  # noqa: BLE001 - a failed scan must not kill the agent
        print(f"[disk scan failed] {exc}")
    finally:
        with _disk_scan_lock:
            _disk_scan_running = False


def _largest_directories():
    """The biggest folders on each volume, as of the last completed scan.

    Answers "what is filling this disk" without anyone logging in to look - the
    question came up on 31 August with a volume at 88% and nothing able to say
    what was on it.

    The walk happens on a background thread and this returns whatever finished
    last, because a heartbeat that waits minutes for a disk scan is a heartbeat
    the platform records as a missed one. The first scan therefore reports
    nothing, and the one after it reports everything.
    """
    global _disk_scan_running
    now = time.monotonic()
    with _disk_scan_lock:
        fresh = _disk_usage_cache["value"] and now - _disk_usage_cache["at"] < DISK_SCAN_INTERVAL_SECONDS
        if not fresh and not _disk_scan_running:
            _disk_scan_running = True
            threading.Thread(target=_disk_scan_worker, daemon=True, name="disk-scan").start()
        return _disk_usage_cache["value"]


# --- §7.1: the agent's own health ------------------------------------------

_agent_started_at = time.time()
_agent_failed_heartbeats = 0


def _agent_service_facts():
    """How this agent is installed, as facts rather than a compliance claim.

    §7.1 asks for automatic startup, version reporting, clean upgrade/rollback,
    uninstall protection and least privilege. A table in a document asserts
    those; this reports what is actually true on this machine, so a server
    installed by hand at 5pm with the wrong start type shows up as itself.
    """
    facts = {
        "install_dir": os.path.dirname(os.path.abspath(__file__)),
        "python": sys.executable,
        # Honest and deliberate: pywin32 installs as LocalSystem and nothing
        # stops a local administrator removing the service. Both are known
        # gaps; reporting them beats a document claiming otherwise.
        "uninstall_protected": False,
    }

    # A kept copy of the previous agent is the whole of the rollback story: if
    # one is not there, a bad update has nothing to go back to.
    try:
        directory = facts["install_dir"]
        backups = sorted(name for name in os.listdir(directory)
                         if name.startswith("agent.py.") or name.endswith(".bak"))
        facts["rollback_available"] = bool(backups)
        facts["previous_versions"] = backups[-3:]
    except OSError:
        facts["rollback_available"] = None

    if platform.system() != "Windows":
        return facts
    try:
        out = subprocess.run(["sc.exe", "qc", "AMNSAgent"], capture_output=True,
                             text=True, timeout=15)
        text = out.stdout or ""
        for key, pattern in (("start_type", r"START_TYPE\s*:\s*\d+\s+(\S+)"),
                             ("run_as", r"SERVICE_START_NAME\s*:\s*(.+)")):
            found = re.search(pattern, text)
            if found:
                facts[key] = found.group(1).strip()
        # Recovery actions are what turn a crash into a blip. PS_QAS went 65
        # minutes unmonitored because these were not set.
        failure = subprocess.run(["sc.exe", "qfailure", "AMNSAgent"], capture_output=True,
                                 text=True, timeout=15)
        facts["auto_restart_on_failure"] = "RESTART" in (failure.stdout or "")
    except Exception:
        pass
    return facts

def _crash_marker_path(config_path):
    return os.path.join(os.path.dirname(config_path), "last_crash.json")


def report_crash(config_path, exc):
    """Called by the Windows Service wrapper right before it lets an unhandled
    exception kill the process. Writes what happened beside the config so the
    NEXT start can carry it into its very first heartbeat.

    The one thing a dead process cannot report about itself is why it died -
    that has always meant Event Viewer on the actual machine, for every single
    occurrence, on however many hundred machines this runs on. The agent that
    comes back up (the service is configured to restart itself) can say what
    killed the one before it, so this shows up on the platform without anyone
    touching that PC.
    """
    try:
        with open(_crash_marker_path(config_path), "w", encoding="utf-8") as fh:
            json.dump({"error": str(exc), "at": datetime.now(timezone.utc).isoformat()}, fh)
    except OSError:
        pass


def _consume_last_crash(config_path):
    """Reads and deletes the crash marker left by a previous run, if any -
    reported exactly once, on the next start, then gone."""
    path = _crash_marker_path(config_path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        os.remove(path)
        return data
    except (OSError, ValueError):
        return None


def _agent_self_health(queue_path, last_crash=None):
    """What the agent knows about itself.

    §7.1 asks it to self-monitor for crashes, queue growth, high resource use
    and clock drift. Everything else here reports on the machine; without this
    the one component nobody is watching is the one doing the watching, and a
    silently degrading agent looks exactly like a healthy one right up to the
    moment it stops.

    Queue depth is the useful early signal: it grows when the platform cannot
    be reached, so a queue that never drains means heartbeats are being kept
    rather than delivered, even while the last one that got through looks fine.
    """
    health = {
        "agent_uptime_seconds": int(time.time() - _agent_started_at),
        "failed_heartbeats": _agent_failed_heartbeats,
        "queued_heartbeats": 0,
        "queue_bytes": 0,
        "last_crash": last_crash,
        # How it is installed, alongside how it is running. Both are "about the
        # agent", and carrying them together means no second column, no
        # migration, and one place the UI has to look.
        "service": _agent_service_facts(),
    }
    try:
        if os.path.exists(queue_path):
            health["queue_bytes"] = os.path.getsize(queue_path)
            health["queued_heartbeats"] = len(_load_queue(queue_path))
    except OSError:
        pass
    try:
        process = psutil.Process()
        health["agent_memory_mb"] = round(process.memory_info().rss / (1024 ** 2), 1)
        # Since the last call, not since boot: a lifetime average hides a spike
        # and is close to meaningless on a long-running process.
        health["agent_cpu_percent"] = round(process.cpu_percent(interval=None), 1)
    except Exception:  # noqa: BLE001 - psutil raises several unrelated types here
        pass
    return health


def collect_metrics(queue_path=None, api_url=None, last_crash=None):
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
        "disk_usage": safe(_largest_directories) or [],
        "database_links": safe(_database_connections) or [],
        "disk_io": safe(_disk_io) or [],
        "web_sites": safe(_web_sites) or [],
        "reachability": safe(lambda: _network_reachability(api_url)) or {},
        "agent_health": safe(lambda: _agent_self_health(queue_path, last_crash)) if queue_path else None,
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
        # A command is only ever acted on for the live heartbeat below, not a
        # backfilled one - it describes what the platform wants done now, and
        # a queued entry is minutes-to-hours old by the time it is retried.
        ok, _, _ = send_heartbeat(api, entry["server_id"], token, entry["metrics"])
        if not ok:
            remaining.append(entry)
    _save_queue(path, remaining)


def send_heartbeat(api, server_id, token, metrics):
    """Posts one heartbeat. Returns (ok, message, command) - never raises, so
    callers (the live loop and the queue flush) can both treat failure as
    data, not an exception to handle. command is whatever the platform wants
    this machine to do next (see RestartRequested), or None almost always."""
    try:
        resp = requests.post(
            f"{api}/servers/heartbeat",
            json={"server_id": server_id, **metrics},
            headers={"X-Agent-Token": token},
            timeout=10,
        )
        if resp.ok:
            command = None
            try:
                command = resp.json().get("data", {}).get("command")
            except ValueError:
                pass
            return True, "ok", command
        return False, f"{resp.status_code} {resp.text}", None
    except requests.exceptions.RequestException as exc:
        return False, str(exc), None


class RestartRequested(Exception):
    """Raised to deliberately end the heartbeat loop when the platform asked
    for a restart or an update - not a crash. agent_service.py lets this one
    escape rather than swallowing it like a real crash, so the service ends
    abnormally and its own configured crash-recovery (see Install.bat's `sc
    failure`) restarts it - reused rather than teaching the agent a second,
    parallel way to bring itself back up."""


def _apply_command(api, token, server_id, command):
    """Carries out a RESTART or UPDATE the platform asked for at the last
    heartbeat, then ends the loop either way via RestartRequested."""
    action = command.get("action")
    if action == "UPDATE":
        _download_update(api, token, server_id, command)
    if action in ("UPDATE", "RESTART"):
        raise RestartRequested(action)


def _download_update(api, token, server_id, command):
    """Downloads the new agent.py, verifies it against the hash the platform
    declared in the same reply that asked for this (a truncated or tampered
    download is refused, not run), keeps the current file as a rollback copy,
    and writes the new one in its place."""
    import shutil

    resp = requests.get(f"{api}/agent/download", params={"server_id": server_id},
                         headers={"X-Agent-Token": token}, timeout=30)
    resp.raise_for_status()
    content = resp.content
    digest = hashlib.sha256(content).hexdigest()
    if digest != command.get("sha256"):
        print(f"[update REJECTED] hash mismatch - expected {command.get('sha256')}, got {digest}")
        return

    here = os.path.dirname(os.path.abspath(__file__))
    current = os.path.abspath(__file__)
    backup = os.path.join(here, f"agent.py.{AGENT_VERSION}")
    if not os.path.exists(backup):
        shutil.copy2(current, backup)
    with open(current, "wb") as fh:
        fh.write(content)
    print(f"[update applied] now {command.get('version')} - restarting to run it")


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


# How many previous agents to keep beside the running one. Three is enough to
# get back past a bad update without turning the install folder into an archive.
KEEP_PREVIOUS_VERSIONS = 3


def _keep_rollback_copy():
    """Keeps a copy of this agent, so a bad update has something to go back to.

    §7.1 asks for rollback. Until now that meant "remember to copy the file
    first", which is exactly the step skipped at 5pm on the day it matters. The
    agent does it itself, on every start, for the version it is running.

    Restoring is deliberately manual: copy the wanted file over agent.py and
    restart the service. An agent that could roll itself back would need to
    decide when to, and a monitoring agent making that call unattended is a
    worse failure than the one it is recovering from.
    """
    import shutil

    try:
        here = os.path.dirname(os.path.abspath(__file__))
        source = os.path.abspath(__file__)
        target = os.path.join(here, f"agent.py.{AGENT_VERSION}")
        if not os.path.exists(target):
            shutil.copy2(source, target)
            print(f"[rollback copy kept] {os.path.basename(target)}")
        copies = sorted(name for name in os.listdir(here) if name.startswith("agent.py."))
        for stale in copies[:-KEEP_PREVIOUS_VERSIONS]:
            os.remove(os.path.join(here, stale))
    except Exception as exc:  # noqa: BLE001 - never let housekeeping stop the agent
        print(f"[rollback copy failed] {exc}")

def run(api, server_id, token, interval, config_path=agent_config.DEFAULT_CONFIG_PATH, stop_event=None):
    """Heartbeat loop: flush any queued failures, collect metrics, send,
    sleep, repeat. Runs until stop_event is set (Windows Service stop) or
    forever (Ctrl+C) when stop_event is None."""
    queue_path = _queue_path(config_path)
    print(f"Agent {AGENT_VERSION} starting. Heartbeat every {interval}s.")
    # Whatever killed the last run, said once, in the very first heartbeat.
    last_crash = _consume_last_crash(config_path)
    if last_crash:
        print(f"[previous run crashed] {last_crash.get('error')} at {last_crash.get('at')}")
    # Watches for database connections between heartbeats; see
    # DATABASE_SAMPLE_SECONDS for why once a minute cannot work.
    start_database_sampler()
    _keep_rollback_copy()
    while stop_event is None or not stop_event.is_set():
        cycle_started = time.monotonic()
        api, server_id, token, interval = _reload(config_path, api, server_id, token, interval)
        _flush_queue(api, token, queue_path)

        metrics = collect_metrics(queue_path, api, last_crash)
        last_crash = None  # said once; do not repeat it every cycle
        ok, message, command = send_heartbeat(api, server_id, token, metrics)
        if ok:
            print(f"[heartbeat OK] cpu={metrics['cpu_percent']}% ram={metrics['ram_percent']}% "
                  f"disk={metrics['disk_percent']}% "
                  f"services={len(metrics['discovered_services'])} ports={len(metrics['discovered_ports'])} "
                  f"processes={len(metrics['discovered_processes'])} "
                  f"programs={len(metrics['discovered_programs'])}")
        else:
            global _agent_failed_heartbeats
            _agent_failed_heartbeats += 1
            print(f"[heartbeat FAILED - queued, will retry next cycle] {message}")
            _queue_failed(queue_path, server_id, metrics)

        if command:
            _apply_command(api, token, server_id, command)

        # Sleep the remainder of the interval, not the whole of it. Sleeping
        # `interval` AFTER the work makes the real period interval + work: the
        # cycle costs a second for cpu_percent alone, more when the disk scan
        # or the reachability pings run, and heartbeats were arriving up to 66
        # seconds apart on a 60-second setting. The platform calls a heartbeat
        # stale at 1.5 intervals, so that drift was walking straight into a
        # "No fresh data" badge on a perfectly healthy machine.
        remaining = max(1.0, interval - (time.monotonic() - cycle_started))
        if stop_event is not None:
            stop_event.wait(remaining)
        else:
            time.sleep(remaining)


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
