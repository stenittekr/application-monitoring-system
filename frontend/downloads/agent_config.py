"""Loads/saves the agent's config file (API URL, server id, token, interval).

Kept separate from agent.py so the Windows service wrapper can load config
without dragging in argparse, and so the ACL lockdown logic lives in one place.
"""
import getpass
import json
import os
import subprocess

DEFAULT_CONFIG_PATH = r"C:\ProgramData\AMNS-Agent\config.json"


def load_config(path=DEFAULT_CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config, path=DEFAULT_CONFIG_PATH):
    """Writes the config (which includes the agent's secret token) and locks
    the file down to Administrators/SYSTEM only - a service running as
    LocalSystem can still read it, but an ordinary logged-in user can't."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    _restrict_permissions(path)


def _restrict_permissions(path):
    """Best-effort ACL lockdown via icacls - never fatal if it fails (e.g. not
    on Windows, or the current user can't change ACLs on this path).

    Grants Administrators/SYSTEM (so the Windows Service, which runs as
    LocalSystem, can always read it) plus whoever is running this script
    right now (so `agent.py run` still works for manual/dev use). Any other
    logged-in account on the box is locked out - that's the actual goal,
    not "only SYSTEM can ever read it"."""
    try:
        subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r",
             "Administrators:F", "SYSTEM:F", f"{getpass.getuser()}:F"],
            check=True, capture_output=True,
        )
    except Exception:
        pass
