"""Blocked addresses must never receive mail, whatever asked for it.

Removing someone from the distribution list only holds until the next thing
that builds a recipient from an owner field, a manager field or an escalation
path. send_email is the choke point every message passes through, so the block
belongs here rather than in each caller.
"""
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.system_setting import SystemSetting
from app.services.email_service import EmailSendError, send_email


@pytest.fixture
def blocked(db):
    db.session.add(SystemSetting(setting_key="alert_blocked_recipients",
                                 setting_value="removed.one@example.com, removed.two@example.com"))
    db.session.commit()


def _sent(mock_smtp):
    """Returns (envelope_recipients, headers) from the patched SMTP session."""
    call = mock_smtp.return_value.__enter__.return_value.sendmail.call_args
    return call[0][1], call[0][2]


def test_a_blocked_address_is_dropped_from_cc(db, blocked):
    with patch("app.services.email_service.smtplib.SMTP") as smtp:
        send_email("stenitte@awgtc.com", "s", "b",
                   cc_addr="ajoy@awgtc.com, removed.one@example.com, removed.two@example.com")
    recipients, raw = _sent(smtp)
    assert "removed.one@example.com" not in recipients
    assert "removed.two@example.com" not in recipients
    assert "removed.one" not in raw, "and not in the headers either"
    assert recipients == ["stenitte@awgtc.com", "ajoy@awgtc.com"]


def test_a_blocked_address_is_dropped_from_to(db, blocked):
    with patch("app.services.email_service.smtplib.SMTP") as smtp:
        send_email("stenitte@awgtc.com, removed.one@example.com", "s", "b")
    recipients, _ = _sent(smtp)
    assert recipients == ["stenitte@awgtc.com"]


def test_nothing_is_sent_when_every_to_address_is_blocked(db, blocked):
    """Promoting a CC into To would deliver exactly the mail the block stops."""
    with patch("app.services.email_service.smtplib.SMTP") as smtp:
        with pytest.raises(EmailSendError):
            send_email("removed.one@example.com", "s", "b", cc_addr="ajoy@awgtc.com")
    assert not smtp.return_value.__enter__.return_value.sendmail.called


def test_multiple_to_addresses_each_get_their_own_envelope_entry(db):
    """A comma-separated To used to be passed as one malformed recipient."""
    with patch("app.services.email_service.smtplib.SMTP") as smtp:
        send_email("stenitte@awgtc.com, m.nizar@awgtc.com", "s", "b",
                   cc_addr="ajoy@awgtc.com, raam@awgtc.com")
    recipients, raw = _sent(smtp)
    assert recipients == ["stenitte@awgtc.com", "m.nizar@awgtc.com",
                          "ajoy@awgtc.com", "raam@awgtc.com"]
    assert "To: stenitte@awgtc.com, m.nizar@awgtc.com" in raw
    assert "Cc: ajoy@awgtc.com, raam@awgtc.com" in raw


def test_no_block_list_configured_changes_nothing(db):
    with patch("app.services.email_service.smtplib.SMTP") as smtp:
        send_email("stenitte@awgtc.com", "s", "b", cc_addr="ajoy@awgtc.com")
    recipients, _ = _sent(smtp)
    assert recipients == ["stenitte@awgtc.com", "ajoy@awgtc.com"]


def test_a_cc_address_already_in_to_is_not_repeated(db):
    """Delivered either way; a name on both lines only reads as a mistake."""
    with patch("app.services.email_service.smtplib.SMTP") as smtp:
        send_email("stenitte@awgtc.com, m.nizar@awgtc.com", "s", "b",
                   cc_addr="ajoy@awgtc.com, m.nizar@awgtc.com")
    recipients, raw = _sent(smtp)
    assert recipients == ["stenitte@awgtc.com", "m.nizar@awgtc.com", "ajoy@awgtc.com"]
    assert "Cc: ajoy@awgtc.com" in raw
