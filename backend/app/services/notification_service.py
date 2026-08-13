"""Builds and sends DOWN / RECOVERY / REMINDER emails, with spam prevention.

Exactly one DOWN email and one RECOVERY email are sent per outage. Reminder
emails are opt-in via system_settings and rate-limited by interval.
"""
import logging
from datetime import datetime, timezone

import requests

from app.extensions import db
from app.models.notification import Notification
from app.models.system_setting import SystemSetting
from app.services.email_service import send_email, EmailSendError

logger = logging.getLogger(__name__)

MAX_NOTIFICATION_RETRIES = 5
WEBHOOK_TIMEOUT_SECONDS = 5


def _get_setting(key, default=None):
    """Reads one value from the system_settings table, or returns the default if unset."""
    row = SystemSetting.query.filter_by(setting_key=key).first()
    return row.setting_value if row else default


def _post_webhook(text):
    """Best-effort Slack/Teams alert alongside email - a missing/unreachable
    webhook must never block the email flow or the incident lifecycle."""
    url = _get_setting("slack_webhook_url")
    if not url:
        return
    try:
        requests.post(url, json={"text": text}, timeout=WEBHOOK_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        logger.warning("Webhook notification failed: %s", exc)


def _create_and_send(incident, application, notification_type, subject, body):
    """Creates a Notification row and immediately attempts to email it."""
    notification = Notification(
        incident_id=incident.id,
        application_id=application.id,
        notification_type=notification_type,
        recipient=application.owner_email,
        cc=application.manager_email,
        subject=subject,
        status="PENDING",
    )
    db.session.add(notification)
    db.session.commit()
    _attempt_send(notification, body)
    return notification


def _attempt_send(notification, body):
    """Sends the notification email, marking it SENT or FAILED and bumping retry_count on failure."""
    try:
        send_email(notification.recipient, notification.subject, body, cc_addr=notification.cc)
        notification.status = "SENT"
        notification.sent_at = datetime.now(timezone.utc)
        notification.error_message = None
    except EmailSendError as exc:
        notification.status = "FAILED"
        notification.error_message = str(exc)
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
        _post_webhook(f"*{server.hostname}* is unreachable - {error_message} (no owner assigned yet)")
        return None
    subject = f"[ALERT] Server Unreachable - {server.hostname}"
    body = (
        f"Server: {server.hostname}\n"
        f"IP Address: {server.ip_address or 'N/A'}\n"
        f"Detected Time: {incident.detected_at.isoformat()}\n"
        f"Reason: {error_message}\n"
    )
    notification = Notification(
        incident_id=incident.id, server_id=server.id, notification_type="DOWN",
        recipient=server.owner_email, subject=subject, status="PENDING",
    )
    db.session.add(notification)
    db.session.commit()
    _attempt_send(notification, body)
    _post_webhook(f"*{server.hostname}* is unreachable - {error_message}")
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
    subject = f"[RECOVERY] Server Reachable Again - {server.hostname}"
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
        recipient=server.owner_email, subject=subject, status="PENDING",
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


def retry_failed_notifications():
    """Retries FAILED notifications up to MAX_NOTIFICATION_RETRIES. Called each
    monitoring cycle so transient SMTP outages self-heal without losing incidents."""
    failed = Notification.query.filter(
        Notification.status == "FAILED", Notification.retry_count < MAX_NOTIFICATION_RETRIES
    ).all()
    for notification in failed:
        try:
            send_email(notification.recipient, notification.subject,
                       "(retry) See original alert details.", cc_addr=notification.cc)
            notification.status = "SENT"
            notification.sent_at = datetime.now(timezone.utc)
            notification.error_message = None
            if notification.notification_type == "DOWN":
                notification.incident.notification_sent = True
            elif notification.notification_type == "RECOVERY":
                notification.incident.recovery_notification_sent = True
        except EmailSendError as exc:
            notification.retry_count += 1
            notification.error_message = str(exc)
        db.session.commit()
