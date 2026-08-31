"""Measures whether this platform survives the estate it is meant to grow into.

§16 asks the developer to size for initial and three-year counts of servers,
checks and events, and to prove agent overhead rather than assert it. Nobody had
measured anything: the platform runs two servers and nine applications, which
tells you nothing about fifty or five hundred.

Runs against a throwaway SQLite database and refuses to touch dev.db. In-process
rather than over HTTP, deliberately - the question is whether the storage and the
cycle keep up, and a benchmark that also measures Flask, the network and the JSON
encoder answers a vaguer question more slowly.

Point DATABASE_URL at a throwaway file first - it refuses to run otherwise:

    set DATABASE_URL=sqlite:///C:/Temp/load.db
    python scripts/loadtest.py            # 10, 50, 200 servers
    python scripts/loadtest.py 500        # and one specific size

What it reports:

  heartbeat ingest   what an agent's POST costs the platform. Every agent does
                     this every 60 seconds, so this multiplied by the server
                     count is the platform's floor.
  monitoring cycle   the loop that decides who is down. It must finish inside
                     the interval; if it does not, checks are late by definition
                     and the platform reports outages that are its own backlog.
  concurrent writes  SQLite serialises writers. This is where it stops scaling,
                     and knowing where matters more than knowing that.
"""
import json
import os
import random
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

DEFAULT_SIZES = (10, 50, 200)

# Roughly what a real v0.9.0 agent sends: PS_QAS reports 240 services, 94 ports
# and 150 processes. A benchmark using a toy payload measures nothing, because
# the payload is most of the work.
SERVICES = 240
PORTS = 94
PROCESSES = 150
PROGRAMS = 52


def _payload():
    return {
        "cpu_percent": round(random.uniform(1, 95), 1),
        "ram_percent": round(random.uniform(20, 90), 1),
        "disk_percent": round(random.uniform(20, 95), 1),
        "uptime_seconds": random.randint(1000, 900000),
        "cpu_cores": 10, "ram_total_mb": 28671, "disk_total_gb": 200.7,
        "agent_version": "0.9.0",
        "agent_time": datetime.now(timezone.utc).isoformat(),
        "discovered_services": [{"name": f"svc{i}", "status": "running"} for i in range(SERVICES)],
        "discovered_ports": [{"port": 1000 + i, "process": "x"} for i in range(PORTS)],
        "discovered_processes": [{"pid": i, "name": f"p{i}.exe", "memory_mb": 12.5}
                                 for i in range(PROCESSES)],
        "discovered_programs": [{"name": f"prog{i}", "version": "1.0"} for i in range(PROGRAMS)],
        "cpu_per_core": [round(random.uniform(0, 100), 1) for _ in range(10)],
        "network_interfaces": [{"name": "Ethernet0", "up": True, "speed_mbps": 1000,
                                "bytes_sent": 1, "bytes_recv": 1, "errors": 0, "drops": 0}],
        "disk_volumes": [{"mount": "C:\\", "fstype": "NTFS", "total_gb": 200.7,
                          "used_percent": 87.5}],
        "hardware": {}, "scheduled_tasks": [], "containers": [],
        "agent_health": {"queued_heartbeats": 0, "failed_heartbeats": 0,
                         "agent_memory_mb": 42.8, "agent_cpu_percent": 0.4},
    }


def _percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def measure(size):
    """Builds an estate of `size` servers and times the things that matter."""
    from app import create_app
    from app.extensions import db
    from app.models.application import Application
    from app.services import server_service

    app = create_app()

    result = {"servers": size}
    with app.app_context():
        # Verified against the engine actually bound, not against what we asked
        # for. Setting DATABASE_URL from inside the process was supposed to be
        # enough and was not - the engine is bound during create_app, before the
        # override could apply - so an earlier run wrote a thousand fake servers
        # into the live database, which the monitor then dutifully checked for
        # twenty minutes. A benchmark that can reach production data is not a
        # benchmark, so this refuses rather than trusting the variable.
        actual = str(db.engine.url)
        if "dev.db" in actual or not actual.startswith("sqlite:"):
            raise SystemExit(
                "REFUSING TO RUN: this is bound to the real database.\n"
                f"  bound : {actual}\n\n"
                "Point it at a throwaway file first, in the shell, before Python starts:\n"
                "  Command Prompt : set DATABASE_URL=sqlite:///C:/Temp/load.db\n"
                "  PowerShell     : $env:DATABASE_URL='sqlite:///C:/Temp/load.db'\n"
                "  bash           : DATABASE_URL=sqlite:///C:/Temp/load.db python scripts/loadtest.py")

        # A file left over from a previous run would make the numbers nonsense.
        db.drop_all()
        db.create_all()

        servers = []
        for i in range(size):
            server, _ = server_service.enroll({"hostname": f"LOADHOST-{i:04d}",
                                               "owner_email": "load@test"})
            servers.append(server)

        # Two applications per server is the shape the requirements describe.
        for i in range(size * 2):
            db.session.add(Application(
                name=f"App {i}", url="http://127.0.0.1:9/", environment="Production",
                owner_name="o", owner_email="o@test", manager_name="m", manager_email="m@test",
                monitoring_enabled=True, monitoring_interval=60, timeout=1,
                retry_count=1, retry_delay=0, expected_status_code=200,
                current_status="UP", hosted_on_server_id=servers[i % size].id))
        db.session.commit()

        # --- heartbeat ingest -------------------------------------------------
        timings = []
        for server in servers:
            start = time.perf_counter()
            server_service.record_heartbeat(server, _payload())
            timings.append((time.perf_counter() - start) * 1000)
        result["heartbeat_p50_ms"] = round(statistics.median(timings), 1)
        result["heartbeat_p95_ms"] = round(_percentile(timings, 0.95), 1)
        result["heartbeat_total_s"] = round(sum(timings) / 1000, 1)

        # Every agent heartbeats once per interval, so this is the floor the
        # platform must clear before doing anything else at all.
        result["ingest_load_percent"] = round(sum(timings) / 1000 / 60 * 100, 1)

        # --- missed-heartbeat sweep ------------------------------------------
        start = time.perf_counter()
        server_service.check_missed_heartbeats()
        result["heartbeat_sweep_ms"] = round((time.perf_counter() - start) * 1000, 1)

        # --- concurrent writers ----------------------------------------------
        # SQLite serialises writers; this is where it stops scaling.
        def beat(index):
            with app.app_context():
                from app.models.server import Server
                row = db.session.get(Server, servers[index % len(servers)].id)
                began = time.perf_counter()
                try:
                    server_service.record_heartbeat(row, _payload())
                    return (time.perf_counter() - began) * 1000, None
                except Exception as exc:  # noqa: BLE001 - the failure IS the result
                    return (time.perf_counter() - began) * 1000, type(exc).__name__

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(beat, range(min(size, 100))))
        errors = [e for _, e in outcomes if e]
        result["concurrent_p95_ms"] = round(_percentile([t for t, _ in outcomes], 0.95), 1)
        result["concurrent_errors"] = len(errors)
        result["concurrent_error_kinds"] = sorted(set(errors))[:3]

        db.session.remove()

    return result


def main():
    sizes = [int(a) for a in sys.argv[1:]] or list(DEFAULT_SIZES)
    print(f"Load test - {SERVICES} services, {PROCESSES} processes per heartbeat, "
          f"2 applications per server\n")
    header = (f"{'servers':>8} {'ingest p50':>11} {'p95':>8} {'all agents':>11} "
              f"{'of 60s':>8} {'sweep':>9} {'concurrent p95':>15} {'errors':>7}")
    print(header)
    print("-" * len(header))

    rows = []
    for size in sizes:
        row = measure(size)
        rows.append(row)
        print(f"{row['servers']:>8} {row['heartbeat_p50_ms']:>10.1f}ms "
              f"{row['heartbeat_p95_ms']:>7.1f}ms {row['heartbeat_total_s']:>10.1f}s "
              f"{row['ingest_load_percent']:>7.1f}% {row['heartbeat_sweep_ms']:>8.1f}ms "
              f"{row['concurrent_p95_ms']:>14.1f}ms {row['concurrent_errors']:>7}")

    print()
    worst = rows[-1]
    if worst["ingest_load_percent"] > 100:
        print("VERDICT: heartbeat ingest alone exceeds the 60s interval. The platform "
              "cannot keep up at this size on SQLite.")
    elif worst["ingest_load_percent"] > 50:
        print("VERDICT: ingest uses more than half the interval before any checking "
              "happens. Move to SQL Server before this size.")
    else:
        print("VERDICT: comfortable at this size on SQLite.")
    if worst["concurrent_errors"]:
        print(f"         {worst['concurrent_errors']} concurrent write(s) failed "
              f"({', '.join(worst['concurrent_error_kinds'])}) - the usual SQLite ceiling.")
    print()
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
