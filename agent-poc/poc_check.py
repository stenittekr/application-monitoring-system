"""
Proof-of-concept: what can this server tell us WITHOUT assuming any special
permission? Run this on any server (this machine, or a target server once you
have access) with: pip install psutil && python poc_check.py

It tries every metric one at a time, catches whatever error happens, and
prints a plain PASS/FAIL line for each - so you get real evidence of what's
actually available on THIS machine, not a guess.
"""
import platform
import socket
import time

try:
    import psutil
except ImportError:
    print("Missing dependency. Run: pip install psutil")
    raise SystemExit(1)

AGENT_VERSION = "0.1.0-poc"

results = []  # list of (metric_name, ok, detail)


def check(name, fn):
    """Runs one collector, records PASS/FAIL, never lets one failure stop the rest."""
    try:
        value = fn()
        results.append((name, True, value))
    except PermissionError as exc:
        results.append((name, False, f"permission denied: {exc}"))
    except Exception as exc:
        results.append((name, False, f"{type(exc).__name__}: {exc}"))


def get_hostname():
    return socket.gethostname()


def get_ip():
    return socket.gethostbyname(socket.gethostname())


def get_os():
    return f"{platform.system()} {platform.release()} ({platform.version()})"


def get_cpu():
    return f"{psutil.cpu_percent(interval=1)}%"


def get_ram():
    m = psutil.virtual_memory()
    return f"{m.percent}% used ({m.used // (1024**2)} MB / {m.total // (1024**2)} MB)"


def get_disk():
    d = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
    return f"{d.percent}% used ({d.used // (1024**3)} GB / {d.total // (1024**3)} GB)"


def get_uptime():
    seconds = time.time() - psutil.boot_time()
    hours = int(seconds // 3600)
    return f"{hours} hours ({int(seconds)}s)"


def get_processes():
    procs = list(psutil.process_iter(["pid", "name"]))
    visible = sum(1 for p in procs if p.info.get("name"))
    denied = len(procs) - visible
    return f"{visible} processes visible" + (f", {denied} denied detail" if denied else "")


def get_services():
    if platform.system() == "Windows":
        count = 0
        for svc in psutil.win_service_iter():
            svc.as_dict()  # forces a read; raises if denied
            count += 1
        return f"{count} Windows services enumerated"
    else:
        import subprocess
        out = subprocess.run(["systemctl", "list-units", "--type=service", "--no-pager"],
                              capture_output=True, text=True, timeout=5)
        return f"systemctl reachable, exit code {out.returncode}"


def get_ports():
    conns = psutil.net_connections(kind="inet")
    listening = [c for c in conns if c.status == "LISTEN"]
    with_pid = sum(1 for c in listening if c.pid)
    return f"{len(listening)} listening ports, {with_pid} with an owning PID visible"


def get_agent_version():
    return AGENT_VERSION


check("Hostname", get_hostname)
check("IP address", get_ip)
check("OS / version", get_os)
check("CPU usage", get_cpu)
check("RAM usage", get_ram)
check("Disk usage", get_disk)
check("Uptime", get_uptime)
check("Agent version", get_agent_version)
check("Process list", get_processes)
check("Service list", get_services)
check("Listening ports", get_ports)

print("=" * 70)
print(f"POC RESULTS -- {socket.gethostname()} -- {platform.system()}")
print("=" * 70)
for name, ok, detail in results:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name:<16} {detail}")
print("=" * 70)
passed = sum(1 for _, ok, _ in results if ok)
print(f"{passed}/{len(results)} checks succeeded with NO elevated privileges.")
