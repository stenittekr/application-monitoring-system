"""Builds and sends DOWN / RECOVERY / REMINDER emails, with spam prevention.

Exactly one DOWN email and one RECOVERY email are sent per outage. Reminder
emails are opt-in via system_settings and rate-limited by interval.

Nothing is emailed on a quiet day (weekends by default). Those notifications
are held as PENDING and delivered on the next working day by
retry_failed_notifications, so a weekend outage is delayed, never lost.
"""
import logging
from datetime import datetime, timezone

import requests

from app.extensions import db
from app.services import alert_policy
from app.models.notification import Notification
from app.models.system_setting import SystemSetting
from app.services.email_service import send_email, EmailSendError
from app.utils.redaction import redact

logger = logging.getLogger(__name__)

MAX_NOTIFICATION_RETRIES = 5
WEBHOOK_TIMEOUT_SECONDS = 5
ESCALATION_MINUTES_DEFAULT = "30"
# Weekday numbers (Mon=0 .. Sun=6) on which no notification is emailed.
# Override with: INSERT INTO system_settings (setting_key, setting_value)
#               VALUES ('quiet_days', '');   -- empty = never quiet
QUIET_DAYS_DEFAULT = "5,6"  # Sat, Sun


def _alert_cc(*extra):
    """Builds the CC list: the application's manager plus the standing
    distribution list in system_settings. Kept as a setting, not a constant, so
    the list can change without a code deploy. Deduplicated and order-stable."""
    raw = _get_setting("alert_cc_recipients", "") or ""
    addresses = [a.strip() for a in raw.split(",") if a.strip()]
    addresses = list(extra) + addresses
    seen, unique = set(), []
    for address in addresses:
        key = (address or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(address.strip())
    return ", ".join(unique) or None


def _get_setting(key, default=None):
    """Reads one value from the system_settings table, or returns the default if unset."""
    row = SystemSetting.query.filter_by(setting_key=key).first()
    return row.setting_value if row else default


def _in_quiet_days():
    """True when today is a configured quiet day - no email or webhook goes out.
    Health checks still run, incidents still open, and the notification row is
    still written as PENDING; delivery just waits for the next working day."""
    # ponytail: server local time is the business time zone. Add a tz
    # setting only if the worker ever runs somewhere other than the office.
    days = _get_setting("quiet_days", QUIET_DAYS_DEFAULT) or ""
    return str(datetime.now().weekday()) in {d.strip() for d in days.split(",") if d.strip()}


def _post_webhook(text):
    """Best-effort Slack/Teams alert alongside email - a missing/unreachable
    webhook must never block the email flow or the incident lifecycle."""
    url = _get_setting("slack_webhook_url")
    if not url or _in_quiet_days():
        return
    try:
        # Slack/Teams is transmission too - §14 applies here as much as to email.
        requests.post(url, json={"text": redact(text)}, timeout=WEBHOOK_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        logger.warning("Webhook notification failed: %s", exc)


def _create_and_send(incident, application, notification_type, subject, body):
    """Creates a Notification row and immediately attempts to email it."""
    notification = Notification(
        incident_id=incident.id,
        application_id=application.id,
        notification_type=notification_type,
        recipient=application.owner_email,
        cc=_alert_cc(application.manager_email),
        subject=redact(subject),
        body=redact(body),
        status="PENDING",
    )
    db.session.add(notification)
    db.session.commit()
    _attempt_send(notification, body)
    return notification


def _entity_for(notification):
    """The application or server an alert is about, for severity and hours."""
    if notification.application_id:
        from app.models.application import Application
        return db.session.get(Application, notification.application_id)
    if notification.server_id:
        from app.models.server import Server
        return db.session.get(Server, notification.server_id)
    return None


def _routing_for(notification):
    """(action, why) from the alert policy. Recovery always goes out with the
    alert it closes: telling someone it broke and never that it was fixed is
    worse than not telling them at all."""
    if notification.notification_type == "RECOVERY":
        return alert_policy.EMAIL, None   # still subject to alerts_enabled() above
    from app.models.incident import Incident

    incident = db.session.get(Incident, notification.incident_id) if notification.incident_id else None
    if incident is None:
        return alert_policy.EMAIL, None
    entity = _entity_for(notification)
    severity = incident.severity or alert_policy.severity_of(incident, entity)
    if incident.severity != severity:
        incident.severity = severity
        db.session.commit()
    override = alert_policy.recipients(severity, entity=entity)
    if override:
        notification.recipient = override
    return alert_policy.route(severity, entity=entity)


ALERTS_ENABLED_SETTING = "incident_alerts_enabled"


def alerts_enabled():
    """Is the platform allowed to email about incidents at all?

    A separate thing from quiet days. Quiet days *hold* mail and deliver it
    later, which on 31 August meant a weekend of alerts arriving in one burst on
    Monday morning - most of them about a database that was never down. This
    switch discards instead, so turning it back on cannot produce a flood.

    Incidents are still opened, recorded and shown on the dashboard. Only the
    emailing stops.
    """
    return (_get_setting(ALERTS_ENABLED_SETTING, "true") or "true").strip().lower() != "false"


def _attempt_send(notification, body):
    """Sends the notification email, marking it SENT or FAILED and bumping retry_count on failure."""
    if not alerts_enabled():
        # Suppressed, not held: a paused queue is a flood waiting to happen.
        notification.status = "SUPPRESSED"
        notification.error_message = "Incident alert email is switched off."
        db.session.commit()
        return

    if _in_quiet_days():
        # Left PENDING with retry_count untouched - retry_failed_notifications
        # picks it up on the next working day and sends the stored body.
        logger.debug("Quiet day - holding notification #%s for the next working day.", notification.id)
        return
    # Severity decides whether this interrupts someone now, waits for the
    # morning digest, or is recorded and not sent at all.
    action, why = _routing_for(notification)
    if action == alert_policy.NONE:
        notification.status = "SUPPRESSED"
        notification.error_message = why or "Routing policy: not sent."
        db.session.commit()
        return
    if action == alert_policy.DIGEST:
        notification.status = "DIGEST"
        notification.error_message = why
        db.session.commit()
        logger.debug("Notification #%s held for the daily digest.", notification.id)
        return

    entity = _entity_for(notification)
    if getattr(entity, "alerts_muted", False):
        # This machine is set to send nothing. Still recorded, still on the
        # dashboard - it simply does not reach anyone's inbox.
        notification.status = "SUPPRESSED"
        notification.error_message = "Alerts for this server are switched off."
        db.session.commit()
        return

    if getattr(entity, "owner_only_alerts", False):
        # Monitoring infrastructure. Its owner needs to know; nobody else does.
        notification.cc = None
    elif not notification.cc:
        # Server DOWN, server RECOVERY and ESCALATION each built their own
        # Notification and none of them set a CC, so those three went to one
        # person while application alerts went to the whole list. Defaulting it
        # here rather than at each call site means the next notification type
        # cannot forget in the same way.
        notification.cc = _alert_cc()
    try:
        # Last line of defence before anything leaves the building.
        send_email(notification.recipient, redact(notification.subject), redact(body),
                   cc_addr=notification.cc)
        notification.status = "SENT"
        notification.sent_at = datetime.now(timezone.utc)
        notification.error_message = None
    except EmailSendError as exc:
        notification.status = "FAILED"
        notification.error_message = redact(str(exc))
        notification.retry_count += 1
    db.session.commit()


def send_down_notification(incident, application, http_status_code, error_message):
    """Sends the one-time DOWN email and Slack alert for a newly opened incident."""
    if incident.notification_sent:
        return None
    subject = f"[ALERT] Application Down - {application.name}"
    body = (
        f"Application Name: {application.name}\n"
        f"URL: {application.url}\n"
        f"Environment: {application.environment}\n"
        f"Detected Time: {incident.detected_at.isoformat()}\n"
        f"HTTP Status: {http_status_code if http_status_code is not None else 'N/A'}\n"
        # The reason was collected and then discarded: the alert announced that
        # an application was down without ever saying what happened when we
        # tried it, which is the first thing anyone reading it wants to know.
        f"Reason: {error_message or incident.reason or 'Health check failed'}\n"
        f"Attempts: {application.retry_count} per check, failing consecutively "
        f"before this alert was raised\n"
    )
    notification = _create_and_send(incident, application, "DOWN", subject, body)
    _post_webhook(f"*{application.name}* is DOWN - {error_message or 'health check failed'}")
    if notification.status == "SENT":
        incident.notification_sent = True
        db.session.commit()
    return notification


def send_recovery_notification(incident, application):
    """Sends the one-time RECOVERY email and Slack alert once an incident is resolved."""
    if incident.recovery_notification_sent:
        return None
    subject = f"[RECOVERY] Application Restored - {application.name}"
    downtime = incident.duration_seconds or 0
    hours, remainder = divmod(downtime, 3600)
    minutes, seconds = divmod(remainder, 60)
    body = (
        f"Application Name: {application.name}\n"
        f"URL: {application.url}\n"
        f"Environment: {application.environment}\n"
        f"Outage Start: {incident.started_at.isoformat()}\n"
        f"Recovery Time: {incident.resolved_at.isoformat() if incident.resolved_at else 'N/A'}\n"
        f"Total Downtime: {hours}h {minutes}m {seconds}s\n"
        f"Previous Error: {incident.error_message or 'N/A'}\n"
        f"Incident ID: {incident.id}\n"
    )
    notification = _create_and_send(incident, application, "RECOVERY", subject, body)
    _post_webhook(f"*{application.name}* recovered - downtime {hours}h {minutes}m {seconds}s")
    if notification.status == "SENT":
        incident.recovery_notification_sent = True
        db.session.commit()
    return notification


def send_server_down_notification(incident, server, error_message):
    """Sends the one-time DOWN email/Slack alert for a server that missed its heartbeat."""
    if incident.notification_sent:
        return None
    if not server.owner_email:
        # No owner assigned yet (e.g. a freshly self-enrolled agent) - this is the
        # same "Information Required" gap the requirements doc calls for, just not
        # a full workflow yet. Still post to Slack/Teams if configured, skip email.
        logger.warning("Server %s has no owner_email - skipping DOWN email.", server.hostname)
        _post_webhook(f"*{server.hostname}* needs attention - {error_message} (no owner assigned yet)")
        return None
    # The subject has to match what happened. A CPU threshold alert titled
    # "Server Unreachable" is worse than no alert: the machine was answering
    # perfectly, and anyone reading the subject goes looking for a dead server.
    headline = {
        "RESOURCE": "Server Resource Warning",
        "COMPONENT": "Server Component Failed",
    }.get(incident.kind, "Server Unreachable")
    subject = f"[ALERT] {headline} - {server.hostname}"
    body = (
        f"Server: {server.hostname}\n"
        f"IP Address: {server.ip_address or 'N/A'}\n"
        f"Detected Time: {incident.detected_at.isoformat()}\n"
        f"Reason: {error_message}\n"
    )
    notification = Notification(
        incident_id=incident.id, server_id=server.id, notification_type="DOWN",
        recipient=server.owner_email, subject=subject, body=body, status="PENDING",
    )
    db.session.add(notification)
    db.session.commit()
    _attempt_send(notification, body)
    _post_webhook(f"*{server.hostname}*: {error_message}")
    if notification.status == "SENT":
        incident.notification_sent = True
        db.session.commit()
    return notification


def send_server_recovery_notification(incident, server):
    """Sends the one-time RECOVERY email/Slack alert once a server resumes heartbeats."""
    if incident.recovery_notification_sent:
        return None
    if not server.owner_email:
        logger.warning("Server %s has no owner_email - skipping RECOVERY email.", server.hostname)
        _post_webhook(f"*{server.hostname}* is reachable again (no owner assigned yet)")
        return None
    # Mirrors the DOWN subject: "Reachable Again" for a CPU alert reads as if
    # the machine had been off, and the pair has to tell the same story.
    headline = {
        "RESOURCE": "Server Resource Back to Normal",
        "COMPONENT": "Server Component Restored",
    }.get(incident.kind, "Server Reachable Again")
    subject = f"[RECOVERY] {headline} - {server.hostname}"
    downtime = incident.duration_seconds or 0
    hours, remainder = divmod(downtime, 3600)
    minutes, seconds = divmod(remainder, 60)
    body = (
        f"Server: {server.hostname}\n"
        f"Outage Start: {incident.started_at.isoformat()}\n"
        f"Recovery Time: {incident.resolved_at.isoformat() if incident.resolved_at else 'N/A'}\n"
        f"Total Downtime: {hours}h {minutes}m {seconds}s\n"
    )
    notification = Notification(
        incident_id=incident.id, server_id=server.id, notification_type="RECOVERY",
        recipient=server.owner_email, subject=subject, body=body, status="PENDING",
    )
    db.session.add(notification)
    db.session.commit()
    _attempt_send(notification, body)
    _post_webhook(f"*{server.hostname}* is reachable again - downtime {hours}h {minutes}m {seconds}s")
    if notification.status == "SENT":
        incident.recovery_notification_sent = True
        db.session.commit()
    return notification


def maybe_send_reminder(incident, application):
    """Sends a REMINDER email if reminders are enabled and the interval has elapsed
    since the last notification for this incident."""
    if _get_setting("reminder_notifications_enabled", "false").lower() != "true":
        return None
    if _in_quiet_days():
        # Nothing is lost: the DOWN email already went out, and the next
        # working day the interval has long elapsed so a reminder fires then.
        return None

    interval_minutes = int(_get_setting("reminder_interval_minutes", "60"))
    last = (
        Notification.query.filter_by(incident_id=incident.id)
        .order_by(Notification.created_at.desc())
        .first()
    )
    now = datetime.now(timezone.utc)
    if last:
        last_created = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
        elapsed_minutes = (now - last_created).total_seconds() / 60
        if elapsed_minutes < interval_minutes:
            return None

    subject = f"[REMINDER] Application Still Down - {application.name}"
    body = (
        f"Application Name: {application.name}\n"
        f"URL: {application.url}\n"
        f"Environment: {application.environment}\n"
        f"Down Since: {incident.started_at.isoformat()}\n"
        f"Incident ID: {incident.id}\n"
        "This application is still unavailable.\n"
    )
    return _create_and_send(incident, application, "REMINDER", subject, body)


def check_escalations():
    """Re-notifies for OPEN incidents that have gone unacknowledged past the
    configured escalation window - fires once per incident (escalated_at),
    so this doesn't repeat every monitoring cycle."""
    from app.models.incident import Incident

    if _in_quiet_days():
        # escalated_at stays NULL, so the escalation fires the next working day.
        return

    interval_minutes = int(_get_setting("escalation_minutes", ESCALATION_MINUTES_DEFAULT))
    now = datetime.now(timezone.utc)
    candidates = Incident.query.filter_by(
        status="OPEN", escalated_at=None, notification_sent=True, acknowledged_at=None
    ).all()
    for incident in candidates:
        detected = incident.detected_at
        if detected.tzinfo is None:
            detected = detected.replace(tzinfo=timezone.utc)
        if (now - detected).total_seconds() < interval_minutes * 60:
            continue
        _send_escalation(incident)


def _send_escalation(incident):
    """Sends the one-time escalation notice for an incident nobody has acknowledged."""
    if incident.application_id:
        from app.models.application import Application
        entity = db.session.get(Application, incident.application_id)
        recipient = (entity.manager_email or entity.owner_email) if entity else None
        label = entity.name if entity else f"application #{incident.application_id}"
    else:
        from app.models.server import Server
        entity = db.session.get(Server, incident.server_id)
        recipient = entity.owner_email if entity else None
        label = entity.hostname if entity else f"server #{incident.server_id}"

    if not recipient:
        # Nothing to notify - mark escalated anyway so this doesn't get
        # re-evaluated every cycle forever with no recipient to send to.
        logger.warning("Cannot escalate incident #%s - no recipient configured.", incident.id)
        incident.escalated_at = datetime.now(timezone.utc)
        db.session.commit()
        return

    subject = f"[ESCALATION] Unacknowledged incident - {label}"
    body = (
        f"Incident #{incident.id} for {label} has been open and unacknowledged since "
        f"{incident.detected_at.isoformat()}.\n"
        f"Reason: {incident.reason or incident.error_message or 'N/A'}\n"
    )
    notification = Notification(
        incident_id=incident.id, application_id=incident.application_id, server_id=incident.server_id,
        notification_type="ESCALATION", recipient=recipient, subject=subject, body=body, status="PENDING",
    )
    db.session.add(notification)
    db.session.commit()
    _attempt_send(notification, body)
    _post_webhook(f"*{label}* incident #{incident.id} still unacknowledged - escalating.")
    incident.escalated_at = datetime.now(timezone.utc)
    db.session.commit()


def retry_failed_notifications():
    """Delivers everything still undelivered: FAILED notifications (up to
    MAX_NOTIFICATION_RETRIES) and PENDING ones held over a quiet day. Called each
    monitoring cycle so transient SMTP outages and weekends both self-heal."""
    if not alerts_enabled():
        # Anything that queued before the switch was thrown is defused here
        # rather than left primed for whenever it is thrown back.
        stale = Notification.query.filter(Notification.status.in_(("PENDING", "FAILED"))).all()
        for row in stale:
            row.status = "SUPPRESSED"
            row.error_message = "Incident alert email is switched off."
        if stale:
            db.session.commit()
            logger.info("Alert email is off - %d queued notification(s) discarded.", len(stale))
        return

    if _in_quiet_days():
        return
    pending = Notification.query.filter(
        Notification.status.in_(("PENDING", "FAILED")),
        Notification.retry_count < MAX_NOTIFICATION_RETRIES,
    ).all()
    for notification in pending:
        try:
            send_email(notification.recipient, notification.subject,
                       notification.body or "(retry) See original alert details.",
                       cc_addr=notification.cc)
            notification.status = "SENT"
            notification.sent_at = datetime.now(timezone.utc)
            notification.error_message = None
            if notification.notification_type == "DOWN":
                notification.incident.notification_sent = True
            elif notification.notification_type == "RECOVERY":
                notification.incident.recovery_notification_sent = True
        except EmailSendError as exc:
            notification.retry_count += 1
            notification.error_message = redact(str(exc))
        db.session.commit()


DIGEST_HOUR_DEFAULT = "8"
LAST_DIGEST_SETTING = "last_digest_sent_at"


def _digest_body(rows):
    """One readable summary of everything held back since the last digest."""
    lines = [f"{len(rows)} monitoring event(s) since the last digest.", ""]
    for row in rows:
        when = row.created_at.strftime("%d %b %H:%M") if row.created_at else "unknown time"
        lines.append(f"- {when}  [{row.notification_type}]  {row.subject}")
    lines += [
        "",
        "These were not sent individually because their severity routes to the digest.",
        "Anything urgent was emailed at the time it happened.",
        "",
        "Open the dashboard for current status; some of these may already be resolved.",
    ]
    return "\n".join(lines)


def send_daily_digest(now=None):
    """Sends one summary of everything held for the digest. Returns the count sent.

    Called every cycle; sends at most once a day, at the configured hour. A
    digest is the answer to alerts that are worth recording and not worth
    interrupting anyone for - a disk creeping past a warning line is real, but
    it is not a 3am fact.
    """
    now = now or datetime.now(timezone.utc)
    if _in_quiet_days():
        return 0

    try:
        hour = int(_get_setting("digest_hour", DIGEST_HOUR_DEFAULT))
    except ValueError:
        hour = int(DIGEST_HOUR_DEFAULT)
    local_now = now.astimezone()
    if local_now.hour < hour:
        return 0

    last = _get_setting(LAST_DIGEST_SETTING)
    if last:
        try:
            previous = datetime.fromisoformat(last)
            previous = previous if previous.tzinfo else previous.replace(tzinfo=timezone.utc)
            if previous.astimezone().date() == local_now.date():
                return 0  # already sent today
        except ValueError:
            pass

    rows = Notification.query.filter_by(status="DIGEST").order_by(Notification.created_at.asc()).all()
    _stamp_digest(now)
    if not rows:
        return 0  # nothing held back is not worth an email saying so

    # No Notification row of its own: a digest is about many incidents and the
    # table requires one, and every row it covers already records that it was
    # sent. Inventing a parent incident to satisfy a column would put a
    # misleading entry in that incident's history.
    body = _digest_body(rows)
    subject = f"[MONITORING DIGEST] {len(rows)} event(s) - {local_now:%d %b %Y}"
    try:
        send_email(rows[0].recipient, subject, body, cc_addr=_alert_cc())
    except EmailSendError as exc:
        # Left as DIGEST so the next run picks them up rather than losing them.
        logger.warning("Daily digest could not be sent: %s", redact(str(exc)))
        return 0
    for row in rows:
        row.status = "SENT"
        row.sent_at = now
    db.session.commit()
    logger.info("Daily digest sent covering %d event(s).", len(rows))
    return len(rows)


def _stamp_digest(now):
    row = SystemSetting.query.filter_by(setting_key=LAST_DIGEST_SETTING).first()
    if row:
        row.setting_value = now.isoformat()
    else:
        db.session.add(SystemSetting(setting_key=LAST_DIGEST_SETTING, setting_value=now.isoformat()))
    db.session.commit()
