"""Availability, downtime and response-time reporting."""
import csv
import io
from datetime import datetime, timezone

from sqlalchemy import func

from app.extensions import db
from app.models.application import Application
from app.models.health_check import HealthCheck
from app.models.incident import Incident


def availability_report(application_id=None, environment=None, date_from=None, date_to=None):
    """Availability % per application = (checks that succeeded / total checks) * 100,
    over the monitoring window. Using health-check counts is the practical proxy for
    uptime since checks run at a known cadence per application."""
    date_from = date_from or datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_to = date_to or datetime.now(timezone.utc)

    query = (
        db.session.query(
            Application.id,
            Application.name,
            Application.environment,
            func.count(HealthCheck.id).label("total_checks"),
            func.sum(func.cast(HealthCheck.success, db.Integer)).label("successful_checks"),
            func.avg(HealthCheck.response_time).label("avg_response_time"),
        )
        .join(HealthCheck, HealthCheck.application_id == Application.id)
        .filter(HealthCheck.checked_at >= date_from, HealthCheck.checked_at <= date_to)
        .filter(Application.deleted_at.is_(None))
    )
    if application_id:
        query = query.filter(Application.id == application_id)
    if environment:
        query = query.filter(Application.environment == environment)

    query = query.group_by(Application.id, Application.name, Application.environment)

    results = []
    for row in query.all():
        total = row.total_checks or 0
        successful = row.successful_checks or 0
        availability = round((successful / total) * 100, 2) if total else 0.0
        incident_count = (
            Incident.query.filter(
                Incident.application_id == row.id,
                Incident.started_at >= date_from,
                Incident.started_at <= date_to,
            ).count()
        )
        total_downtime = (
            db.session.query(func.coalesce(func.sum(Incident.duration_seconds), 0))
            .filter(
                Incident.application_id == row.id,
                Incident.started_at >= date_from,
                Incident.started_at <= date_to,
                Incident.status == "RESOLVED",
            )
            .scalar()
        )
        results.append({
            "application_id": row.id,
            "application_name": row.name,
            "environment": row.environment,
            "total_checks": total,
            "successful_checks": successful,
            "availability_percent": availability,
            "avg_response_time": round(row.avg_response_time, 2) if row.avg_response_time else None,
            "incident_count": incident_count,
            "avg_downtime_seconds": round(total_downtime / incident_count, 2) if incident_count else 0,
            "total_downtime_seconds": total_downtime,
        })
    return results


def daily_availability(application_id, date_from, date_to):
    """Per-day availability % for a single application, for charting."""
    rows = (
        db.session.query(
            func.cast(HealthCheck.checked_at, db.Date).label("day"),
            func.count(HealthCheck.id).label("total_checks"),
            func.sum(func.cast(HealthCheck.success, db.Integer)).label("successful_checks"),
        )
        .filter(
            HealthCheck.application_id == application_id,
            HealthCheck.checked_at >= date_from,
            HealthCheck.checked_at <= date_to,
        )
        .group_by(func.cast(HealthCheck.checked_at, db.Date))
        .order_by(func.cast(HealthCheck.checked_at, db.Date))
        .all()
    )
    result = []
    for row in rows:
        total = row.total_checks or 0
        successful = row.successful_checks or 0
        result.append({
            "date": row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day),
            "availability_percent": round((successful / total) * 100, 2) if total else 0.0,
            "total_checks": total,
        })
    return result


def failure_frequency(application_id=None, date_from=None, date_to=None):
    """Counts failed health checks per application over the given filters."""
    query = db.session.query(
        HealthCheck.application_id,
        Application.name,
        func.count(HealthCheck.id).label("failure_count"),
    ).join(Application, Application.id == HealthCheck.application_id).filter(HealthCheck.success.is_(False))
    if application_id:
        query = query.filter(HealthCheck.application_id == application_id)
    if date_from:
        query = query.filter(HealthCheck.checked_at >= date_from)
    if date_to:
        query = query.filter(HealthCheck.checked_at <= date_to)
    query = query.group_by(HealthCheck.application_id, Application.name)
    return [
        {"application_id": r.application_id, "application_name": r.name, "failure_count": r.failure_count}
        for r in query.all()
    ]


def _minutes_between(earlier, later):
    """Whole minutes between two timestamps, tolerant of naive values."""
    if not earlier or not later:
        return None
    if earlier.tzinfo is None:
        earlier = earlier.replace(tzinfo=timezone.utc)
    if later.tzinfo is None:
        later = later.replace(tzinfo=timezone.utc)
    seconds = (later - earlier).total_seconds()
    return seconds / 60 if seconds >= 0 else None


def response_metrics(application_id=None, environment=None, date_from=None, date_to=None):
    """MTTD, MTTA and MTTR over the window (FR-017, §11 step 16).

    Every timestamp these need is already on the incident row, so this is a
    query rather than new instrumentation:

      MTTD  started_at  -> detected_at      how long until we noticed
      MTTA  detected_at -> acknowledged_at  how long until a human picked it up
      MTTR  detected_at -> resolved_at      how long until service returned

    Each is averaged only over the incidents that actually reached that stage,
    and the count is reported alongside - an MTTA of 4 minutes drawn from one
    acknowledged incident out of forty is not a number to plan around.
    """
    query = Incident.query
    if application_id:
        query = query.filter(Incident.application_id == application_id)
    if date_from:
        query = query.filter(Incident.detected_at >= date_from)
    if date_to:
        query = query.filter(Incident.detected_at <= date_to)
    if environment:
        query = query.join(Application, Incident.application_id == Application.id)                      .filter(Application.environment == environment)

    incidents = query.all()
    buckets = {
        "mttd_minutes": [_minutes_between(i.started_at, i.detected_at) for i in incidents],
        "mtta_minutes": [_minutes_between(i.detected_at, i.acknowledged_at) for i in incidents],
        "mttr_minutes": [_minutes_between(i.detected_at, i.resolved_at) for i in incidents],
    }
    result = {"incidents": len(incidents)}
    for name, values in buckets.items():
        present = [v for v in values if v is not None]
        result[name] = round(sum(present) / len(present), 1) if present else None
        result[name.replace("_minutes", "_sample")] = len(present)

    result["unacknowledged"] = sum(1 for i in incidents if i.acknowledged_at is None)
    result["unresolved"] = sum(1 for i in incidents if i.resolved_at is None)
    return result


def export_availability_csv(rows):
    """Renders availability report rows as a CSV string."""
    buffer = io.StringIO()
    fieldnames = [
        "application_id", "application_name", "environment", "total_checks",
        "successful_checks", "availability_percent", "avg_response_time",
        "incident_count", "avg_downtime_seconds", "total_downtime_seconds",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()
