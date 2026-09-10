"""SMTP email delivery.

Configuration is read from the system_settings DB table first (so an admin
can set/rotate SMTP credentials from the Settings page without touching
server files or restarting anything), falling back to the .env-backed Flask
config for any key an admin hasn't set yet. Credentials are never hard-coded
or logged.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app

logger = logging.getLogger(__name__)

_SETTING_KEYS = {
    "SMTP_HOST": "smtp_host",
    "SMTP_PORT": "smtp_port",
    "SMTP_USERNAME": "smtp_username",
    "SMTP_PASSWORD": "smtp_password",
    "SMTP_USE_TLS": "smtp_use_tls",
    "EMAIL_FROM": "email_from",
}


class EmailSendError(Exception):
    pass


def _get_smtp_config():
    """Builds the effective SMTP config, letting DB-stored settings override .env defaults."""
    from app.models.system_setting import SystemSetting  # local import avoids a circular import

    cfg = dict(current_app.config)
    db_rows = {row.setting_key: row.setting_value for row in SystemSetting.query.filter(
        SystemSetting.setting_key.in_(_SETTING_KEYS.values())
    ).all()}

    for config_key, setting_key in _SETTING_KEYS.items():
        value = db_rows.get(setting_key)
        if value not in (None, ""):
            cfg[config_key] = value

    cfg["SMTP_PORT"] = int(cfg["SMTP_PORT"])
    cfg["SMTP_USE_TLS"] = str(cfg["SMTP_USE_TLS"]).strip().lower() == "true"
    return cfg


BLOCKED_SETTING = "alert_blocked_recipients"



def _addresses(value):
    """Splits a comma-separated field into individual addresses.

    To and Cc are single strings everywhere upstream, but a header may legally
    hold several addresses - and smtplib needs them one per envelope entry, or
    the whole string is treated as one malformed recipient and nothing arrives.
    """
    return [a.strip() for a in (value or "").split(",") if a.strip()]


def _blocked():
    """Addresses that must never receive mail, whatever asked for it.

    Removing someone from a distribution list only holds until the next thing
    that builds a recipient from an owner field, a manager field or an
    escalation path. This is the choke point every email passes through, so a
    block here is the one that actually holds.
    """
    from app.models.system_setting import SystemSetting

    row = SystemSetting.query.filter_by(setting_key=BLOCKED_SETTING).first()
    return {a.lower() for a in _addresses(row.setting_value if row else "")}


def send_email(to_addr, subject, body_text, cc_addr=None):
    """Sends a plain-text email. Raises EmailSendError on failure (caller decides how to record it)."""
    cfg = _get_smtp_config()

    blocked = _blocked()
    to_list = [a for a in _addresses(to_addr) if a.lower() not in blocked]
    already = {a.lower() for a in to_list}
    cc_list = [a for a in _addresses(cc_addr)
               if a.lower() not in blocked and a.lower() not in already]
    if not to_list:
        # Everyone in To was blocked. Promoting a CC into To would deliver the
        # mail the block was meant to stop, so nothing is sent.
        raise EmailSendError("No permitted recipients remain after the block list.")

    msg = MIMEMultipart()
    msg["From"] = cfg["EMAIL_FROM"]
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))

    recipients = to_list + cc_list

    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as server:
            if cfg.get("SMTP_USE_TLS"):
                server.starttls()
            if cfg.get("SMTP_USERNAME"):
                server.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
            server.sendmail(cfg["EMAIL_FROM"], recipients, msg.as_string())
    except Exception as exc:
        # Never log credentials or full message content - just the failure reason.
        logger.error("Email delivery failed to %s: %s", to_addr, exc)
        raise EmailSendError(str(exc)) from exc
