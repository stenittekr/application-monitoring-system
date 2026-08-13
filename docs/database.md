# Database

Microsoft SQL Server, database name **`ApplicationMonitoringDB`**, accessed via
`pyodbc` + SQLAlchemy (`mssql+pyodbc://...`). Schema source of truth is the
scripts in [`../database/`](../database/):

| Script | Purpose |
|---|---|
| `001_create_database.sql` | Creates the `ApplicationMonitoringDB` database |
| `002_create_tables.sql` | Creates all 7 tables with foreign keys and CHECK constraints |
| `003_create_indexes.sql` | Creates the indexes listed below |
| `004_create_seed_data.sql` | One user per role + sample applications + default settings |

Run them in order with `scripts/setup_database.bat`, or manually in SSMS /
`sqlcmd`. `backend/app/models/*.py` mirrors this schema exactly via
SQLAlchemy - if you change one, change both (see `backend/migrations/README.md`).

## Tables

- **users** - id, name, email (unique), password_hash (bcrypt), role
  (`ADMIN`/`MANAGER`/`VIEWER`), is_active, created_at, updated_at, last_login_at.
- **applications** - the monitored apps: name, environment, owner/manager
  name+email, monitoring config (enabled/interval/timeout/retry_count/retry_delay/
  expected_status_code), current_status, last check timestamps, soft-delete.
  `health_check_type` is `HTTP`/`HTTPS`/`TCP`: HTTP/HTTPS checks use `url`;
  TCP checks use `server`+`port` instead (a raw socket connect, no `url`
  needed) - see `docs/monitoring.md`.
  via `deleted_at`.
- **health_checks** - one row per check *attempt* (including retries):
  application_id, checked_at, status, http_status_code, response_time (ms),
  success, error_message, attempt_number.
- **incidents** - one row per outage: application_id, status (`OPEN`/`RESOLVED`),
  started_at/detected_at/resolved_at, duration_seconds, reason, notification
  flags. Only one `OPEN` incident is allowed per application at a time.
- **notifications** - one row per email attempt: incident_id, application_id,
  notification_type (`DOWN`/`RECOVERY`/`REMINDER`), recipient/cc, subject,
  status (`PENDING`/`SENT`/`FAILED`), retry_count.
- **activity_logs** - the audit trail: user_id, action, entity_type/entity_id,
  description, ip_address, metadata (JSON text).
- **system_settings** - key/value config editable from the Settings page at
  runtime (reminder settings, SMTP settings - see below), instead of `.env`.

## Relationships

- `applications` 1 --- N `health_checks`
- `applications` 1 --- N `incidents`
- `incidents` 1 --- N `notifications`
- `users` 1 --- N `activity_logs`

## Indexes

`applications.current_status`, `applications.monitoring_enabled`,
`health_checks.application_id`, `health_checks.checked_at`,
`incidents.application_id`, `incidents.status`, `activity_logs.created_at`,
`notifications.status` (plus the primary/foreign keys, which SQL Server
indexes automatically).

## SMTP settings live in the database, not `.env`

`system_settings` holds `smtp_host`, `smtp_port`, `smtp_username`,
`smtp_password`, `smtp_use_tls`, `email_from` so an admin can set/rotate
credentials from the Settings page without redeploying. `app/services/email_service.py`
reads these first and falls back to the `.env`-backed Flask config for any
key not set in the database. The seed script intentionally leaves
`smtp_password` blank - set it once via the Settings page (as an ADMIN) after
the database is created, so the real credential never has to live in a file
that gets checked into source control.

## SQLite in tests

The test suite (`backend/tests/`) runs against an in-memory SQLite database
instead of SQL Server, so `pytest` needs no external services. One schema
detail differs between the two: `health_checks.id` and `activity_logs.id` are
declared as `BigInteger().with_variant(Integer, "sqlite")` because SQLite
only auto-increments plain `INTEGER` primary keys - production still gets a
real `BIGINT` on SQL Server.
