# Centralized Server & Application Monitoring Platform

Automates what was previously a manual process: checking whether internal and
external company applications are up, alerting the right people the moment
one goes down, and tracking incidents/history/availability over time.

## What it does

- Stores every monitored application (URL, owner, manager, environment,
  per-app monitoring settings).
- Checks each application's URL on its own schedule, with retries before
  declaring it down (so one blip never triggers a false alarm).
- Opens exactly one incident per outage, emails the owner (CC manager), and
  resolves the incident + emails a recovery notice + calculates downtime
  automatically when it comes back.
- Keeps full health-check history, incident history, and an audit log of who
  changed what.
- Serves a dashboard and availability/downtime/incident reports (with CSV
  export and charts) from real data - nothing here is mocked.

See [`docs/architecture.md`](docs/architecture.md) for the full picture.

## Technology

| Layer | Tech |
|---|---|
| Frontend | HTML5, CSS3, vanilla JavaScript, Bootstrap 5, Chart.js, Fetch API |
| Backend | Python, Flask, Flask-SQLAlchemy, Flask-JWT-Extended, Flask-Bcrypt |
| Database | Microsoft SQL Server, via pyodbc |
| Monitoring | Standalone Python process (APScheduler + `requests`) |
| Email | SMTP (stdlib `smtplib`), config stored in the DB |

## Requirements

- Python 3.10+
- Microsoft SQL Server 2017+ and the **ODBC Driver 17 (or 18) for SQL Server**
- An SMTP mailbox/relay for outbound email

## Quick start (Windows)

```
scripts\setup_database.bat      REM creates ApplicationMonitoringDB + seed data
scripts\start_backend.bat       REM Flask API on http://localhost:5000
scripts\start_monitor.bat       REM standalone monitoring worker (separate window)
```

Then open `frontend/index.html` in a browser (or serve the `frontend/`
folder with any static server). Log in with a seeded account:

| Role | Email | Password |
|---|---|---|
| ADMIN | admin@example.com | Admin@123 |
| MANAGER | manager@example.com | Manager@123 |
| VIEWER | viewer@example.com | Viewer@123 |

**Change these passwords immediately** - they're for local development only.

### Manual setup (any OS)

```bash
# 1. Database - run in order via sqlcmd or SSMS:
#    database/001_create_database.sql
#    database/002_create_tables.sql
#    database/003_create_indexes.sql
#    database/004_create_seed_data.sql

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # edit with your SQL Server + JWT/secret values
python run.py

# 3. Monitoring worker (separate terminal, same .env)
python monitoring/monitor.py

# 4. Frontend
cd ../frontend
python -m http.server 8080   # then open http://localhost:8080
```

## Roles

- **ADMIN** - full control: manage applications, monitoring settings, users,
  system settings, run manual checks, view everything.
- **MANAGER** - views applications they own/manage, incidents, health-check
  history, and reports.
- **VIEWER** - read-only: application status, basic incidents, basic health
  history.

All of the above is enforced **in the Flask API** (`@roles_required` on every
write endpoint and on ADMIN/MANAGER-only reads), not just hidden in the UI.

## Running tests

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
pytest tests/ -v
```

Tests run against an in-memory SQLite database with mocked HTTP/SMTP calls,
so no SQL Server or real network access is required. 39 tests cover auth,
authorization, application CRUD + validation, health checks (timeouts,
5xx, retries), DOWN detection, duplicate-incident prevention, recovery,
notification spam prevention (and that a failed email never loses an
incident), activity logging, and reports.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) - how the pieces fit together
- [`docs/database.md`](docs/database.md) - schema, relationships, indexes
- [`docs/api.md`](docs/api.md) - every endpoint, roles, validation rules
- [`docs/monitoring.md`](docs/monitoring.md) - retry logic, incident lifecycle, the worker
- [`docs/deployment.md`](docs/deployment.md) - production setup checklist
- [`docs/troubleshooting.md`](docs/troubleshooting.md) - common issues and fixes
