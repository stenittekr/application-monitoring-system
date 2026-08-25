"""Strips secrets out of text before it is stored, emailed, or logged.

Requirements §14 and §18: passwords, tokens and connection strings must be
redacted before transmission, and must never end up in profile text or logs.

Two prior leaks in this codebase were the same shape - a value that was correct
to *use* got copied into a message that was then persisted and mailed out:

  * a driver error quoted the whole connection string, expanded password included
  * process discovery captured a PowerShell `-command` argument verbatim

Both were fixed at their own call site. This module is the general form, so the
next path that formats an error into a string does not have to remember.

The rules are deliberately blunt. Over-redacting costs a reader some context;
under-redacting emails a production password to a distribution list.
"""
import os
import re

MASK = "***"

# Environment variables whose *values* must never appear in output. Matched by
# name so a new credential in .env is covered without touching this file.
_SECRET_NAME_RE = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN|APIKEY|API_KEY|_KEY)$", re.IGNORECASE)

# Shortest env value worth scrubbing. Below this, a "secret" is likely a flag
# like "1" or "true", and blanking every "1" in a message would destroy it.
_MIN_SECRET_LENGTH = 6

_PATTERNS = (
    # scheme://user:password@host  ->  scheme://user:***@host
    (re.compile(r"(?P<pre>[a-zA-Z][\w+.-]*://[^\s:/@]+:)[^\s@]+(?P<post>@)"), r"\g<pre>" + MASK + r"\g<post>"),
    # password=... / token: ... / api_key = ... in any common separator style
    (re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\b\s*[=:]\s*['\"]?[^\s'\";,&]+"),
     lambda m: f"{m.group(1)}={MASK}"),
    # Authorization: Bearer <jwt/opaque>
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/=]{8,}"), lambda m: f"{m.group(1)} {MASK}"),
    # ODBC/ADO style: PWD=secret;
    (re.compile(r"(?i)\b(pwd|uid)\s*=\s*[^;\s]+"), lambda m: f"{m.group(1)}={MASK}"),
    # A bare 32+ char hex run is an agent token or key, never prose.
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), MASK),
)


def secret_values():
    """Current secret values from the environment, longest first.

    Longest first matters: if one secret contains another as a substring,
    replacing the short one first would leave a fragment of the long one behind.
    """
    values = []
    for name, value in os.environ.items():
        if value and len(value) >= _MIN_SECRET_LENGTH and _SECRET_NAME_RE.search(name):
            values.append(value)
    return sorted(set(values), key=len, reverse=True)


def redact(value, extra=()):
    """Returns the text with credentials masked. Safe on None and non-strings.

    `extra` carries values known only to the caller - typically a password that
    was just expanded from an environment variable for a single connection.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)

    # Literal known secrets first: an exact value is the most reliable match,
    # and doing it before the patterns means a password containing "token=x"
    # cannot survive by looking like something the patterns already handled.
    for secret in list(extra) + secret_values():
        if secret and len(str(secret)) >= _MIN_SECRET_LENGTH:
            text = text.replace(str(secret), MASK)

    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter:
    """Logging filter so secrets cannot reach the log files either.

    Install with: logging.getLogger().addFilter(RedactingFilter())
    """

    def filter(self, record):  # noqa: A003 - name fixed by the logging API
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args) \
                    if isinstance(record.args, tuple) else record.args
        except Exception:  # pragma: no cover - logging must never raise
            pass
        return True
