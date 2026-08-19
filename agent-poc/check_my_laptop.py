"""Stand-alone, offline check: what services and ports are running on THIS
machine right now. No enrollment, no platform connection, no admin rights
needed - reuses the same discovery code the real agent uses."""
from agent import _discover_services, _discover_ports

services = _discover_services()
ports = _discover_ports()

running = [s for s in services if s["status"] == "running"]
print(f"=== Services: {len(running)} running / {len(services)} total ===")
for s in running:
    print(f"  RUNNING  {s['display_name']}  ({s['name']})")

print(f"\n=== Listening ports: {len(ports)} ===")
for p in sorted(ports, key=lambda x: x["port"] or 0):
    proc = p["process_name"] or "unknown"
    print(f"  {p['protocol']:<4} {p['port']:<6} {proc}")
