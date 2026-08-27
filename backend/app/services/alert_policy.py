"""Decides how urgent an alert is, and therefore who hears about it and when.

Every alert was the same alert: a disk at 82% woke the same four people, in the
same way, at the same hour, as a production outage. Sixty emails went out in a
week and most of them were things nobody needed to read at 03:00. An alert
nobody can act on right now is not information, it is interruption, and the
credit it spends is what a real outage needs.

Three questions, in order:

  severity_of()  how bad is this?
  route()        given that, does it go out now, wait for the digest, or not go?
  recipients()   and to whom, at this hour?

All four decisions are settings, so they change without a deploy. The defaults
send everything except LOW immediately, to the existing list - so nothing is
quieter than before until someone chooses it, except the resource warnings that
prompted this.
"""
import logging
from datetime import datetime, time, timezone

logger = logging.getLogger(__name__)

CRITICAL, HIGH, MEDIUM, LOW = "CRITICAL", "HIGH", "MEDIUM", "LOW"
ORDER = (LOW, MEDIUM, HIGH, CRITICAL)

EMAIL, DIGEST, NONE = "EMAIL", "DIGEST", "NONE"

# What happens to each severity when it is raised. LOW defaults to the digest
# because that is the noise this exists to remove; everything else keeps
# behaving as it did.
ROUTE_DEFAULTS = {CRITICAL: EMAIL, HIGH: EMAIL, MEDIUM: EMAIL, LOW: DIGEST}

# Outside support hours, only these reach a person. The rest wait for morning.
DEFAULT_OUT_OF_HOURS_MINIMUM = HIGH

# "08:00-18:00", or "24x7" for anything that matters at any hour.
DEFAULT_SUPPORT_HOURS = "24x7"


def _setting(key, default=None):
    from app.models.system_setting import SystemSetting

    row = SystemSetting.query.filter_by(setting_key=key).first()
    return row.setting_value if row and row.setting_value else default


def severity_of(incident, entity=None):
    """How bad is this, on the evidence available?

    Derived rather than configured per rule: a severity someone has to set by
    hand on every application is a severity that ends up wrong everywhere, and
    the facts needed to judge it - what kind of failure, how far past the
    threshold, whether the thing is in Production - are already recorded.
    """
    kind = (incident.kind or "REACHABILITY").upper()
    reason = (incident.reason or "").lower()

    if kind == "RESOURCE":
        # A warning threshold is a heads-up; a critical one is a real risk of
        # the machine stopping. They should not arrive the same way.
        severity = HIGH if "critical" in reason else LOW
    elif kind == "COMPONENT":
        severity = MEDIUM
    else:  # REACHABILITY - something is unreachable
        severity = HIGH

    # Production raises the floor: the same failure matters more where the
    # business is actually running.
    environment = getattr(entity, "environment", None)
    criticality = (getattr(entity, "criticality", None) or "").upper()
    if criticality == "CRITICAL" or (severity == HIGH and environment == "Production"):
        severity = CRITICAL if severity == HIGH else severity
    return severity


def _parse_hours(value):
    """'08:00-18:00' -> (time(8), time(18)). None means always."""
    text = (value or DEFAULT_SUPPORT_HOURS).strip().lower()
    if text in ("24x7", "24/7", "", "always"):
        return None
    try:
        start, _, end = text.partition("-")
        sh, _, sm = start.strip().partition(":")
        eh, _, em = end.strip().partition(":")
        return time(int(sh), int(sm or 0)), time(int(eh), int(em or 0))
    except ValueError:
        logger.warning("Unreadable support hours %r - treating as 24x7.", value)
        return None


def in_support_hours(entity, now=None):
    """Is this inside the thing's support hours right now?

    Uses local time deliberately: support hours are a human schedule, and the
    people they describe work in one timezone, not UTC.
    """
    window = _parse_hours(getattr(entity, "support_hours", None)
                          or _setting("default_support_hours", DEFAULT_SUPPORT_HOURS))
    if window is None:
        return True
    now = (now or datetime.now(timezone.utc)).astimezone()
    start, end = window
    if start <= end:
        return start <= now.time() <= end
    return now.time() >= start or now.time() <= end  # window crossing midnight


def route(severity, entity=None, now=None):
    """EMAIL now, hold for the DIGEST, or NONE. Returns (action, reason)."""
    action = (_setting(f"route_{severity.lower()}", ROUTE_DEFAULTS.get(severity, EMAIL)) or EMAIL).upper()
    if action not in (EMAIL, DIGEST, NONE):
        action = EMAIL

    if action == EMAIL and not in_support_hours(entity, now):
        minimum = (_setting("out_of_hours_minimum_severity", DEFAULT_OUT_OF_HOURS_MINIMUM) or HIGH).upper()
        if ORDER.index(severity) < ORDER.index(minimum if minimum in ORDER else HIGH):
            return DIGEST, f"{severity} outside support hours - held for the digest"
    return action, None


def recipients(severity, now=None, entity=None):
    """Who hears about this at this hour, or None to use the usual list.

    The on-call list only displaces the usual one out of hours, and only for
    what is worth waking someone for. In hours, everyone gets what they always
    got - a rota that quietly narrows the daytime audience is how an outage
    reaches one person on annual leave.
    """
    if in_support_hours(entity, now):
        return None
    if ORDER.index(severity) < ORDER.index(HIGH):
        return None
    return _setting("oncall_recipients") or None
