"""Watches the monitoring platform, from outside the monitoring platform.

On the night of 25 August both Windows services stopped. Nothing was checked
for sixteen hours, no alert was raised, and the dashboard went on showing the
last status every application had before the lights went out. Requirements §19
asks for exactly this: "the central platform monitors its own health through an
independent mechanism."

Independent is the whole point, so this script deliberately shares nothing with
what it watches:

  * it is not the monitor, not the platform, and not a Flask app - it is run by
    Windows Task Scheduler, which keeps running when our services do not
  * it imports nothing from backend/app, so a bug or a missing dependency that
    stops the platform cannot also stop the watchdog
  * it sends mail itself, over SMTP, rather than through the platform's
    notification pipeline - a queue nobody is draining is not an alert

Two questions, because the platform can fail in two different ways:

  1. Is the web application answering?          -> GET /api/health
  2. Is the monitoring cycle actually running?  -> how old is the timestamp the
                                                   cycle writes on every pass?

The second is the one that caught nobody's eye in August. The platform can
answer HTTP perfectly while the scheduler behind it is dead, and a dashboard
that loads is extremely convincing.

Run it:

    python monitoring\\watchdog.py

Schedule it (elevated Command Prompt, one line):

    schtasks /create /tn "AMNS Watchdog" /sc minute /mo 10 /ru SYSTEM ^
      /tr "\\"C:\\Python314\\python.exe\\" \\"<full path>\\monitoring\\watchdog.py\\""

Exit codes: 0 healthy, 1 a problem was found, 2 the watchdog itself could not run.
"""
import json
import os
import smtplib
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "backend" / ".env"

# Where the cycle records that it ran. Written by monitoring/health_checker.py
# on every pass, which is what makes it a usable dead-man's switch.
CYCLE_SETTING = "last_monitoring_cycle_at"

# How stale that timestamp may get before we call it a stall. Generous on
# purpose: a cycle that overruns once is not an outage, and a watchdog that
# cries wolf gets muted, which leaves us exactly where we started.
DEFAULT_MAX_CYCLE_AGE_SECONDS = 900

HEALTH_TIMEOUT_SECONDS = 15

# Remembers what was already reported, so a stall raises one email rather than
# one every ten minutes - and so recovery can be announced exactly once.
STATE_FILE = Path(os.environ.get("TEMP", str(ROOT))) / "amns_watchdog_state.json"


def load_env(path=ENV_FILE):
    """Minimal .env reader. Deliberately not python-dotenv: the watchdog should
    depend on as little as possible, since anything it needs is another thing
    that can be missing at the moment it is needed most."""
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    # Real environment wins, so a scheduled task can override the file.
    values.update({k: v for k, v in os.environ.items() if k in values or k.startswith(
        ("SMTP_", "EMAIL_", "WATCHDOG_", "DATABASE_URL"))})
    return values


def check_web(env):
    """Is the web application answering? Returns (ok, detail)."""
    url = env.get("WATCHDOG_HEALTH_URL") or "http://127.0.0.1:5000/api/health"
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return False, f"{url} returned HTTP {response.status}"
        return True, f"{url} answered 200"
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return False, f"{url} did not answer: {exc}"


def read_last_cycle(env):
    """Returns (timestamp, error). Reading it at all proves the database is up,
    which is why a failure here is reported rather than swallowed."""
    url = env.get("DATABASE_URL")
    if not url:
        return None, "DATABASE_URL is not set, so the watchdog cannot check the cycle."
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return None, "SQLAlchemy is not installed for this interpreter."

    try:
        engine = create_engine(url)
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT setting_value FROM system_settings WHERE setting_key = :k"),
                {"k": CYCLE_SETTING},
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - any failure here is itself the news
        return None, f"could not read the database: {type(exc).__name__}: {exc}"

    if not row or not row[0]:
        return None, "the monitoring cycle has never recorded a run."
    try:
        stamp = datetime.fromisoformat(str(row[0]))
    except ValueError:
        return None, f"the recorded cycle time is unreadable: {row[0]!r}"
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)), None


def check_cycle(env):
    """Is the monitoring cycle running? Returns (ok, detail)."""
    stamp, error = read_last_cycle(env)
    if error:
        return False, error

    max_age = int(env.get("WATCHDOG_MAX_CYCLE_AGE_SECONDS") or DEFAULT_MAX_CYCLE_AGE_SECONDS)
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if age > max_age:
        return False, (f"the last monitoring cycle ran {int(age // 60)} minutes ago "
                       f"({stamp.isoformat()}), which is past the {max_age // 60}-minute limit. "
                       f"Nothing is being monitored.")
    return True, f"last cycle {int(age)}s ago"


def send_alert(env, subject, body):
    """Sends the alert over SMTP directly. Returns True when it left the building."""
    host = env.get("SMTP_HOST")
    sender = env.get("EMAIL_FROM")
    recipients = [a.strip() for a in
                  (env.get("WATCHDOG_RECIPIENTS") or env.get("EMAIL_FROM") or "").split(",")
                  if a.strip()]
    if not (host and sender and recipients):
        print("Cannot send: SMTP_HOST, EMAIL_FROM or WATCHDOG_RECIPIENTS is not configured.")
        return False

    message = MIMEText(body, "plain")
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    try:
        with smtplib.SMTP(host, int(env.get("SMTP_PORT") or 25), timeout=20) as server:
            if str(env.get("SMTP_USE_TLS", "true")).lower() == "true":
                server.starttls()
            if env.get("SMTP_USERNAME"):
                server.login(env["SMTP_USERNAME"], env.get("SMTP_PASSWORD", ""))
            server.sendmail(sender, recipients, message.as_string())
        print(f"Alert sent to {', '.join(recipients)}")
        return True
    except Exception as exc:  # noqa: BLE001 - never let mail trouble hide the finding
        print(f"Could not send the alert: {type(exc).__name__}: {exc}")
        return False


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass  # A lost state file costs a duplicate email, nothing more.


def main():
    env = load_env()
    host = socket.gethostname()
    now = datetime.now(timezone.utc)

    checks = [("Web application", check_web(env)), ("Monitoring cycle", check_cycle(env))]
    failures = [(name, detail) for name, (ok, detail) in checks if not ok]

    for name, (ok, detail) in checks:
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {detail}")

    state = load_state()
    was_failing = bool(state.get("failing"))

    if failures:
        summary = "; ".join(f"{name}: {detail}" for name, detail in failures)
        if not was_failing:
            body = (
                f"The monitoring platform on {host} is not working.\n\n"
                + "\n\n".join(f"{name}\n  {detail}" for name, detail in failures)
                + "\n\nWhile this is the case, no server or application is being checked, "
                  "and the dashboard will keep showing the last status it recorded before "
                  "the problem started. Treat everything on it as out of date.\n\n"
                  "To fix, on that machine in an elevated PowerShell:\n"
                  "    Restart-Service AMNSMonitor\n"
                  "    Restart-Service AMNSAgent\n\n"
                  f"Checked at {now.isoformat()} by the watchdog, which runs outside the "
                  "platform on Windows Task Scheduler.\n"
            )
            send_alert(env, f"[MONITORING DOWN] {host} - the monitor is not running", body)
        else:
            print("Already reported; not sending a duplicate.")
        save_state({"failing": True, "since": state.get("since") or now.isoformat(),
                    "summary": summary})
        return 1

    if was_failing:
        since = state.get("since", "an earlier check")
        send_alert(
            env, f"[MONITORING RECOVERED] {host} - the monitor is running again",
            f"The monitoring platform on {host} is working again.\n\n"
            f"It had been failing since {since}.\n"
            f"Previously: {state.get('summary', 'not recorded')}\n\n"
            "Anything that broke while it was down was not detected, so it is worth a "
            "look at the dashboard for statuses that have not refreshed.\n",
        )
    save_state({"failing": False})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - a crashed watchdog must say so, loudly
        print(f"The watchdog itself failed: {type(exc).__name__}: {exc}")
        sys.exit(2)
