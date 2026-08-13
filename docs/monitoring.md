# Monitoring Engine

## Where the logic lives

`backend/app/services/monitoring_service.py` is the single implementation of
"check one application" - used both by the API's manual "Run Check" button
and by the standalone worker (`monitoring/monitor.py`). There is no separate
copy of the retry/status logic anywhere else.

## Health check types

Each application has a `health_check_type`: `HTTP`, `HTTPS`, or `TCP`.

- **HTTP/HTTPS** - sends `GET <url>` with `requests`, using the application's
  `timeout`. HTTP status == `expected_status_code` and a fast response -> `UP`;
  slower than 3000ms -> `DEGRADED`; wrong status code, timeout, DNS failure,
  connection refused, SSL error, or any other request exception -> `DOWN`
  for that attempt.
- **TCP** - opens a raw `socket.create_connection((server, port), timeout=...)`
  instead (`_perform_tcp_attempt` in `monitoring_service.py`) - no HTTP
  request at all, just "can we open a TCP connection". A successful connect
  is `UP`/`DEGRADED` (same 3000ms threshold); a timeout, DNS failure, or
  refused/unreachable connection is `DOWN`. Use this for anything that isn't
  HTTP - a database listener, an SSH port, a raw TCP service.

## The check flow (`run_health_check(application)`)

1. Runs one attempt via the health-check type above.
2. Classifies the result into `UP` / `DEGRADED` / `DOWN` as described above.
3. **Retry logic**: repeats up to `retry_count` attempts total, sleeping
   `retry_delay` seconds between them, and **stops as soon as one attempt
   succeeds**. Every attempt is saved as its own `health_checks` row
   (`attempt_number` 1, 2, 3, ...). Only if *all* attempts in the cycle fail
   is the application marked `DOWN` - a single blip never triggers an alert.
4. Updates `applications.current_status` / `last_checked_at` /
   `last_successful_check_at` / `last_failed_check_at`.
5. Compares the previous status to the new one and drives the incident +
   notification lifecycle (see below).

## Incident lifecycle

- `UP/UNKNOWN/DEGRADED -> DOWN`: opens a new incident (`incident_service.open_incident`),
  **unless one is already open** for that application - so five consecutive
  failed cycles produce exactly one incident, not five. Sends the DOWN email.
- Still `DOWN` on a later cycle: no new incident; if reminders are enabled in
  Settings, sends a `REMINDER` email at most once per configured interval.
- `DOWN -> UP/DEGRADED`: resolves the open incident, calculates
  `duration_seconds`, sends the RECOVERY email.

## Notification spam prevention

Each `Notification` row is tied to one `Incident`. `Incident.notification_sent`
/ `recovery_notification_sent` flip to `true` only once the email actually
sends successfully - so a transient SMTP outage never causes a duplicate
alert, and a lost incident never happens: the incident row exists regardless
of whether the email succeeded. `notification_service.retry_failed_notifications()`
runs every monitoring cycle to retry `FAILED` notifications (up to 5 attempts).

## Standalone worker (`monitoring/`)

```
python monitoring/monitor.py
```

- Loads `backend/.env` (same config as the Flask API) via `monitoring/config.py`.
- Uses APScheduler's `BlockingScheduler` (`monitoring/scheduler.py`) with
  `max_instances=1`, so a slow cycle can never overlap with the next one -
  this is what prevents duplicate monitoring execution.
- Each cycle (`monitoring/health_checker.py::run_monitoring_cycle`) finds
  applications where `monitoring_enabled = true` and their own
  `monitoring_interval` has elapsed since `last_checked_at`, then checks each
  one independently: **one application's exception (bad URL, DB hiccup)
  never stops the rest of the fleet** from being checked.
- Runs completely independently of the Flask process and the browser - stop
  the API, close every browser tab, and the worker keeps checking and
  emailing on schedule.
- Logs to `monitoring/logs/monitor.log` (rotating, 5MB x 5 backups) and stdout.

## Status values

`UP`, `DOWN`, `DEGRADED`, `UNKNOWN` (never checked yet), `DISABLED`
(monitoring turned off by an admin).
