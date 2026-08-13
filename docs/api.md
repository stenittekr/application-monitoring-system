# API Reference

Base URL: `http://localhost:5000/api`. All endpoints except `/auth/login` and
`/health` require `Authorization: Bearer <token>`. Every response is JSON:

```json
// success
{ "success": true, "data": { ... } }
// error
{ "success": false, "message": "Application not found.", "error_code": "APPLICATION_NOT_FOUND" }
```

Role enforcement happens **server-side** via `@roles_required(...)` (see
`backend/app/auth/decorators.py`) - the frontend hides buttons a role can't
use, but the API rejects unauthorized calls independently (403 `FORBIDDEN`).

## Auth

| Method | Path | Roles | Notes |
|---|---|---|---|
| POST | `/auth/login` | public | `{email, password}` -> `{access_token, user}` |
| POST | `/auth/logout` | any | logs the LOGOUT activity entry |
| GET | `/auth/me` | any | current user profile |

## Applications

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/applications` | any | MANAGER only sees apps where they're owner or manager |
| POST | `/applications` | ADMIN | validated (see below) |
| GET | `/applications/<id>` | any | 404 if soft-deleted |
| PUT | `/applications/<id>` | ADMIN | partial update |
| DELETE | `/applications/<id>` | ADMIN | soft delete (`deleted_at`), disables monitoring |
| POST | `/applications/<id>/check` | ADMIN | runs a real health check synchronously, with retries |
| POST | `/applications/<id>/enable-monitoring` | ADMIN | |
| POST | `/applications/<id>/disable-monitoring` | ADMIN | sets status to `DISABLED` |
| GET | `/applications/<id>/health-checks` | any | `?limit=` (default 100, max 1000) |
| GET | `/applications/<id>/incidents` | any | |

**Validation** (`VALIDATION_ERROR`, 422): name required; `health_check_type`
(`HTTP`/`HTTPS`/`TCP`, default `HTTP`) determines what else is required -
`HTTP`/`HTTPS` need a valid `http(s)://...` URL, `TCP` needs `server` +
`port` (1-65535) instead; owner/manager email required and RFC-shaped;
monitoring_interval/timeout must be > 0; retry_count must be >= 0.

## Incidents

| Method | Path | Roles |
|---|---|---|
| GET | `/incidents?application_id=&status=&environment=&date_from=&date_to=` | any |
| GET | `/incidents/<id>` | any |

## Health checks

| Method | Path | Roles |
|---|---|---|
| GET | `/health-checks?application_id=&status=&success=&date_from=&date_to=&limit=` | any |

## Reports (ADMIN, MANAGER only)

| Method | Path |
|---|---|
| GET | `/reports/availability?application_id=&environment=&date_from=&date_to=` |
| GET | `/reports/availability/daily?application_id=&date_from=&date_to=` |
| GET | `/reports/failure-frequency?application_id=&date_from=&date_to=` |
| GET | `/reports/availability/export` | CSV download |

## Activity logs, Users, Settings (ADMIN only)

| Method | Path |
|---|---|
| GET | `/activity-logs?user_id=&entity_type=&action=&date_from=&limit=` |
| GET | `/users` |
| POST | `/users` `{name, email, password, role}` |
| PUT | `/users/<id>` `{name?, role?, is_active?, password?}` |
| GET | `/settings` | password-like values masked as `********` |
| PUT | `/settings/<key>` `{setting_value}` |
