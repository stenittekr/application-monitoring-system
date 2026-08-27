"""Disk growth rate and days-until-full (§8 "growth trend", §19 "disk fills rapidly").

A static threshold tells you a disk is 85% full. It cannot tell you whether it
took two years to get there or two days, and those need different responses on
different timescales. §19 asks for the rate specifically, because the warning
that matters arrives before the threshold does.

PS_QAS went 82.0 -> 83.8% in four days. At that rate the critical line is weeks
away, which is worth a calendar entry and not a page - and that distinction is
exactly what a rate gives you and a percentage does not.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.server_metric import ServerMetric

logger = logging.getLogger(__name__)

# How far back to look. Long enough to see through a day's noise, short enough
# that a change of behaviour last week still shows up.
WINDOW_DAYS = 14

# Below this the reading is drift, not growth. Without it, a disk oscillating
# by a tenth of a percent produces a confident forecast built on rounding.
MIN_GROWTH_PERCENT_PER_DAY = 0.05

# Beyond this the number stops being a forecast and starts being a guess.
MAX_FORECAST_DAYS = 365


def record_disk_reading(server, now=None):
    """Stores one disk reading, at most once an hour.

    Hourly, not per heartbeat: a minute-by-minute series answers no question
    that a daily trend does not, and it is 60 times the rows to keep and purge.
    """
    if server.disk_percent is None:
        return None
    now = now or datetime.now(timezone.utc)
    latest = (ServerMetric.query
              .filter_by(server_id=server.id)
              .order_by(ServerMetric.recorded_at.desc())
              .first())
    if latest:
        last = latest.recorded_at
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        if (now - last) < timedelta(hours=1):
            return None

    row = ServerMetric(server_id=server.id, recorded_at=now,
                       disk_percent=server.disk_percent,
                       disk_total_gb=server.disk_total_gb)
    db.session.add(row)
    db.session.commit()
    return row


def disk_forecast(server, now=None):
    """Growth per day and days until full, or None when there is not enough to say.

    Deliberately refuses to answer rather than answering badly: two readings an
    hour apart, or a disk that is shrinking, produce no forecast at all. A
    made-up number here would be acted on.
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    rows = (ServerMetric.query
            .filter(ServerMetric.server_id == server.id, ServerMetric.recorded_at >= since)
            .order_by(ServerMetric.recorded_at.asc())
            .all())
    if len(rows) < 2:
        return None

    first, last = rows[0], rows[-1]
    start = first.recorded_at if first.recorded_at.tzinfo else first.recorded_at.replace(tzinfo=timezone.utc)
    end = last.recorded_at if last.recorded_at.tzinfo else last.recorded_at.replace(tzinfo=timezone.utc)
    days = (end - start).total_seconds() / 86400
    if days < 1:
        return None          # less than a day of history says nothing about a trend

    growth = (last.disk_percent - first.disk_percent) / days
    forecast = {
        "growth_percent_per_day": round(growth, 3),
        "current_percent": last.disk_percent,
        "observed_days": round(days, 1),
        "readings": len(rows),
    }
    if growth < MIN_GROWTH_PERCENT_PER_DAY:
        # Flat or shrinking. Saying "never fills" would be a promise; saying
        # nothing is the honest answer.
        forecast["days_until_full"] = None
        return forecast

    remaining = max(0.0, 100.0 - last.disk_percent)
    days_left = int(remaining / growth)
    forecast["days_until_full"] = days_left if days_left <= MAX_FORECAST_DAYS else None
    if days_left <= MAX_FORECAST_DAYS:
        forecast["full_on"] = (now + timedelta(days=days_left)).date().isoformat()
    return forecast
