"""Email notification triggers used by the Flask API.

The DOWN/RECOVERY/REMINDER templates and SMTP delivery live in
app.services.notification_service / app.services.email_service, so the
API and the standalone monitoring/ worker share one implementation.
"""
from app.services.notification_service import (
    send_down_notification,
    send_recovery_notification,
    maybe_send_reminder,
    retry_failed_notifications,
)

__all__ = [
    "send_down_notification",
    "send_recovery_notification",
    "maybe_send_reminder",
    "retry_failed_notifications",
]
