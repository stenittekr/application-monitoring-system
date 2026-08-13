# Architecture

```
             +----------------------+
             |       Browser        |
             |  HTML/CSS/JavaScript |
             |     (Bootstrap 5)    |
             +----------+-----------+
                        |
                        | REST API (fetch, JWT Bearer)
                        v
             +----------------------+
             |      Flask API       |
             |       Python         |
             +----------+-----------+
                        |
                        v
             +----------------------+
             |     SQL Server       |
             |  ApplicationMonitor  |
             |         DB           |
             +----------------------+
                        ^
                        |
             +----------+-----------+
             | Monitoring Service    |
             |  (standalone Python   |
             |   process, APScheduler)|
             +----------+-----------+
                        |
                        v
                 Application URLs
                        |
                        v
                 Email Notification
                        |
                        v
                  Owner + Manager
```

## Processes

There are **two independent Python processes**, both talking to the same SQL Server database:

1. **`backend/` (Flask API)** - serves the REST API the frontend calls, and also
   exposes a "run check now" endpoint for manual health checks from the UI.
2. **`monitoring/` (standalone worker)** - runs forever in the background
   (`python monitoring/monitor.py`), independent of whether the Flask API or
   the browser is open, polling applications on their configured interval.

Both processes share the exact same business logic. `monitoring/health_checker.py`,
`incident_manager.py` and `notification_manager.py` are thin wrappers around
`backend/app/services/monitoring_service.py`, `incident_service.py` and
`notification_service.py` - there is exactly one implementation of "what
happens when a check succeeds or fails", used by both the API and the worker.

## Backend layout

```
backend/app/
  models/       SQLAlchemy models (one file per table)
  routes/       Flask Blueprints - HTTP layer only, no business logic
  services/     Business logic (application/monitoring/incident/notification/email/report/audit)
  auth/         JWT role-based access decorator
  utils/        Validators + the {success,data}/{success,message,error_code} response envelope
  monitoring/   Re-exports services.monitoring_service for the "manual check" API route
  notifications/Re-exports services.notification_service for the API layer
```

Routes never talk to the database directly - they call a service function,
which is the single place that logic lives (so the API and the standalone
worker never disagree on behavior).

## Frontend layout

Plain HTML/CSS/vanilla JavaScript + Bootstrap 5, no build step. `js/api.js` is
the one shared file every page loads first: it wraps `fetch` with JWT auth
handling, builds the sidebar/topbar shell (`initLayout()`), and provides
toast/modal/formatting helpers. Every other `js/*.js` file owns one feature
area and talks to the Flask API exclusively via `js/api.js`'s `api.get/post/put/del`.

## Why two "monitoring" folders?

`backend/app/monitoring/` and `backend/app/notifications/` exist (per the
required project layout) as thin re-export modules for the Flask API layer.
`monitoring/` at the repo root is the actual standalone worker process. Both
import from `backend/app/services/*`, which is where the real logic lives -
this avoids two copies of the retry/incident/notification rules drifting
apart over time.
