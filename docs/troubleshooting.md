# Troubleshooting

**`pyodbc.InterfaceError` / "Data source name not found"**
The ODBC driver named in `SQL_DRIVER` (`.env`) isn't installed. Check
installed drivers: `python -c "import pyodbc; print(pyodbc.drivers())"` and
set `SQL_DRIVER` to match one exactly (e.g. `ODBC Driver 17 for SQL Server`).

**Login fails with correct credentials**
Check `users.is_active` - a disabled account gets `ACCOUNT_DISABLED` (403).
Passwords are bcrypt-hashed; there is no way to "look up" a password, only reset it.

**Frontend shows "Could not reach the server"**
The Flask API isn't running, or `API_BASE_URL` in `frontend/js/api.js` (or
`window.AMNS_API_BASE_URL`) doesn't match where it's actually listening.
Check the browser console/network tab for the exact failing URL.

**401 errors right after logging in**
Token expired (`JWT_ACCESS_TOKEN_EXPIRES_SECONDS`, default 8h) or clock skew
between client/server. `api.js` clears the session and redirects to login
automatically on any 401.

**Emails never send**
Check `system_settings` (Settings page, ADMIN) - `smtp_password` is left
blank by the seed script on purpose and must be set once manually. Check
`notifications.error_message` for the exact SMTP failure. A failed email
never loses the incident - it's retried automatically (up to 5 times) every
monitoring cycle by `retry_failed_notifications()`.

**Getting alert emails on every failed check instead of one per outage**
This would mean `incidents.notification_sent` isn't being set - check that
`monitoring_service.run_health_check` and the standalone worker are pointing
at the *same* database (both read `backend/.env`), and that only one
monitoring worker process is running against it (the scheduler already
guards against overlapping runs with `max_instances=1`, but two separate
`monitor.py` processes started manually would double up).

**Monitoring worker isn't checking anything**
Confirm the application has `monitoring_enabled = 1` and isn't soft-deleted
(`deleted_at IS NULL`). Check `monitoring/logs/monitor.log` for "Could not
query applications" (DB unreachable) or per-application exceptions.

**Tests fail with `NOT NULL constraint failed: health_checks.id` (SQLite only)**
This was a real issue during development: `BigInteger` primary keys don't
auto-increment under SQLite the way `INTEGER` does. Fixed by declaring those
columns as `db.BigInteger().with_variant(db.Integer, "sqlite")` in
`health_check.py` / `activity_log.py` - SQL Server still gets a real BIGINT.
If you add another `BigInteger` primary key, use the same pattern or its
tests will hit this again.

**"Device or resource busy" moving/renaming the project folder on Windows**
Some process (an editor, an indexer, a running venv) is holding a file handle
open inside the folder. Close editors/terminals with that folder open, or
copy the folder to the new location and delete the original instead of a
direct move.
