# Deployment

## Requirements

- Python 3.10+ (tested with 3.10 and 3.14)
- Microsoft SQL Server (2017+) reachable from the app server
- ODBC Driver 17 (or 18) for SQL Server installed on the machine running the
  backend/monitoring processes
- An SMTP relay / mailbox for outbound email (e.g. Office 365, an internal relay)

## 1. Database

1. Install SQL Server + the ODBC driver.
2. Run `scripts\setup_database.bat` (Windows) or execute the four scripts in
   `database/` in order via `sqlcmd`/SSMS.
3. Log in once as `admin@example.com` / `Admin@123` and change the password
   immediately (Users page). Delete/rename the sample seed applications.

## 2. Backend (Flask API)

```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
REM edit .env: SQL_SERVER, SQL_DATABASE, SQL_USERNAME/PASSWORD, SECRET_KEY, JWT_SECRET_KEY
python run.py
```

Or just run `scripts\start_backend.bat`, which does the above. For real
deployment (not `python run.py`'s dev server), put it behind a production
WSGI server (e.g. `waitress` on Windows) and a reverse proxy.

## 3. Monitoring worker

Runs as a **separate, always-on process** - a Windows service or a Scheduled
Task that restarts on failure is the recommended way to keep it running
unattended:

```
scripts\start_monitor.bat
```

It reads the same `backend/.env`, so set it up after step 2.

## 4. Frontend

The frontend is static files (`frontend/`) - no build step. Two options:

- Open `frontend/index.html` directly, or
- Serve the folder with any static file server, e.g. `python -m http.server 8080`
  from inside `frontend/`.

Either way, it calls the Flask API at the URL in `window.AMNS_API_BASE_URL`
(defaults to `http://localhost:5000/api` - set this global before `api.js`
loads, or edit the constant, if the API runs elsewhere). CORS is controlled
by `CORS_ORIGINS` in `backend/.env`.

## 5. Email

Set SMTP host/port/username/from-address as seed data or via `.env`
(non-secret). Set the SMTP **password** once, after first login, from the
Settings page as an ADMIN - it's stored in the `system_settings` table, not
in any file, so it's never at risk of being committed to source control.

## Production hardening checklist

- Change `SECRET_KEY` / `JWT_SECRET_KEY` to long random values.
- Change every seeded password.
- Set `CORS_ORIGINS` to the real frontend origin instead of `*`.
- Put the Flask app behind HTTPS (reverse proxy / load balancer).
- Run the monitoring worker as a service that auto-restarts on crash.
- Point `SQLALCHEMY_DATABASE_URI` (via env vars) at the production SQL Server,
  using a least-privilege SQL login.
