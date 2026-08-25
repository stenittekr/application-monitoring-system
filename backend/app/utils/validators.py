"""Input validation helpers for application/user forms."""
import re
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HEALTH_CHECK_TYPES = ("HTTP", "HTTPS", "TCP", "DATABASE")
# Dialects we ship a driver for: pyodbc (MSSQL) and PyMySQL (MySQL/MariaDB).
DATABASE_BACKENDS = ("mssql", "mysql")
MATURITY_STATUSES = ("DISCOVERED", "INFORMATION_REQUIRED", "PROFILE_DRAFT", "MONITORED", "MAINTENANCE", "RETIRED")


def is_valid_email(value):
    """Checks whether the given value looks like a valid email address."""
    return bool(value) and bool(EMAIL_RE.match(value.strip()))


def is_strong_password(value):
    """Minimum password policy: 8+ chars with at least one letter and one digit."""
    if not value or len(value) < 8:
        return False
    return bool(re.search(r"[A-Za-z]", value)) and bool(re.search(r"\d", value))


def is_valid_url(value):
    """Checks whether the given value is a valid HTTP or HTTPS URL."""
    if not value:
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_database_dsn(value):
    """Validates a DATABASE health-check DSN. Returns an error string, or None.

    The password must be an ${ENV_VAR} reference rather than a literal, so
    credentials live in the environment and never in the applications table
    (where they would also leak into the UI, the API and exported reports)."""
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    if not str(value or "").strip():
        return "A connection string is required for DATABASE health checks."
    try:
        url = make_url(value.strip())
    except (ArgumentError, ValueError):
        return "Connection string must be a valid SQLAlchemy URL, e.g. mysql+pymysql://user:${DB_PASSWORD}@host:3306/dbname"
    if url.get_backend_name() not in DATABASE_BACKENDS:
        return f"Database backend must be one of {DATABASE_BACKENDS}."
    if not url.host:
        return "Connection string must include a host."
    raw = value.strip()
    if url.password and not re.search(r"\$\{\w+\}|%\w+%", raw):
        return ("Put the password in an environment variable and reference it as "
                "${VAR_NAME} in the connection string - literal passwords are not stored.")
    return None


def validate_application_payload(data, partial=False):
    """Returns a list of human-readable error strings; empty list means valid."""
    errors = []

    if not partial and not str(data.get("name") or "").strip():
        errors.append("Application name is required.")

    # health_check_type governs whether a URL (HTTP/HTTPS) or a server+port
    # (TCP) is required. On create it always applies (defaulting to HTTP);
    # on a partial update it only applies if the caller is touching one of
    # these fields, so e.g. renaming an application doesn't re-demand a URL.
    touches_check_config = {"health_check_type", "url", "server", "port"} & data.keys()
    if not partial or touches_check_config:
        check_type = str(data.get("health_check_type") or "HTTP").upper()
        if check_type not in HEALTH_CHECK_TYPES:
            errors.append(f"Health check type must be one of {HEALTH_CHECK_TYPES}.")
        elif check_type in ("HTTP", "HTTPS"):
            if not data.get("url"):
                errors.append("URL is required for HTTP/HTTPS health checks.")
            elif not is_valid_url(data.get("url")):
                errors.append("URL must be a valid HTTP or HTTPS URL.")
        elif check_type == "DATABASE":
            error = validate_database_dsn(data.get("url"))
            if error:
                errors.append(error)
        elif check_type == "TCP":
            if not str(data.get("server") or "").strip():
                errors.append("Server/hostname is required for TCP health checks.")
            port = data.get("port")
            if not port:
                errors.append("Port is required for TCP health checks.")
            else:
                try:
                    if not (1 <= int(port) <= 65535):
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append("Port must be a number between 1 and 65535.")

    if not partial or "owner_email" in data:
        if not data.get("owner_email"):
            errors.append("Owner email is required.")
        elif not is_valid_email(data.get("owner_email")):
            errors.append("Owner email must be a valid email address.")

    if not partial or "manager_email" in data:
        if not data.get("manager_email"):
            errors.append("Manager email is required.")
        elif not is_valid_email(data.get("manager_email")):
            errors.append("Manager email must be a valid email address.")

    if "monitoring_interval" in data and data.get("monitoring_interval") is not None:
        try:
            if int(data["monitoring_interval"]) <= 0:
                errors.append("Monitoring interval must be positive.")
        except (TypeError, ValueError):
            errors.append("Monitoring interval must be a number.")

    if "timeout" in data and data.get("timeout") is not None:
        try:
            if int(data["timeout"]) <= 0:
                errors.append("Timeout must be positive.")
        except (TypeError, ValueError):
            errors.append("Timeout must be a number.")

    if "retry_count" in data and data.get("retry_count") is not None:
        try:
            if int(data["retry_count"]) < 0:
                errors.append("Retry count must be >= 0.")
        except (TypeError, ValueError):
            errors.append("Retry count must be a number.")

    if data.get("maturity_status") and str(data["maturity_status"]).upper() not in MATURITY_STATUSES:
        errors.append(f"Maturity status must be one of {MATURITY_STATUSES}.")

    if data.get("depends_on") is not None:
        deps = data["depends_on"]
        if not isinstance(deps, list) or not all(isinstance(d, int) for d in deps):
            errors.append("Dependencies must be a list of application IDs.")

    return errors
