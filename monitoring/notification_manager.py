"""Re-exports email-notification logic for the standalone worker.

Kept as its own module (per the monitoring/ service layout) but backed by
app.services.notification_service / email_service so templates and SMTP
delivery are defined in exactly one place.
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
