"""Optional Active Directory login, mirroring the proven pattern already used
by AWGTC's Emergency-Mailer/PS APP against the same domain controller.

Only verifies a password for a user that already exists as a local account
(see routes/auth.py) - never creates, promotes, or role-maps a user from AD
group membership; this app's User.role is untouched either way.

Strategy:
1. Bind with the service account (LDAP_BIND_DN / LDAP_BIND_PASSWORD) to
   search for the user by sAMAccountName/employeeID/cn, then re-bind with
   their own password against the real userPrincipalName found.
2. If no service account is configured (or the search finds nothing), fall
   back to a direct bind trying each configured domain suffix.
"""
import logging

from flask import current_app

logger = logging.getLogger(__name__)

_AD_DOMAIN = "@ad.com"


def is_configured():
    """Returns whether an LDAP server is set up for this deployment."""
    return bool(current_app.config.get("LDAP_SERVER"))


def _clean_username(username):
    """Strips any @domain suffix so sAMAccountName-based search always works."""
    username = (username or "").strip()
    return username.split("@", 1)[0] if "@" in username else username


def verify_credentials(username, password):
    """Verifies an AD password via service-account search+re-bind, falling
    back to direct-bind across configured domain suffixes. Returns bool."""
    if not is_configured() or not password:
        return False

    from ldap3 import Server, Connection

    server_url = current_app.config["LDAP_SERVER"]
    port = current_app.config.get("LDAP_PORT") or 389
    base_dn = current_app.config.get("LDAP_BASE_DN") or ""
    bind_dn = current_app.config.get("LDAP_BIND_DN") or ""
    bind_password = current_app.config.get("LDAP_BIND_PASSWORD") or ""
    domains = current_app.config.get("LDAP_DOMAINS") or []

    clean_user = _clean_username(username)
    server = Server(server_url, port=port, get_info=None)

    if bind_dn and bind_password:
        if _search_and_rebind(server, base_dn, bind_dn, bind_password, clean_user, password):
            return True

    for suffix in [_AD_DOMAIN] + [d for d in domains if d != _AD_DOMAIN]:
        if _try_bind(server, f"{clean_user}{suffix}", password):
            return True
    return False


def _search_and_rebind(server, base_dn, bind_dn, bind_password, username, password):
    """Finds the user's real userPrincipalName via the service account, then
    confirms their password by binding as that UPN."""
    from ldap3 import Connection

    try:
        service_conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
    except Exception as exc:
        logger.warning("LDAP service-account bind failed: %s", exc)
        return False

    search_filter = (
        f"(|(sAMAccountName={username})(employeeID={username})"
        f"(employeeNumber={username})(cn={username}))"
    )
    try:
        service_conn.search(base_dn, search_filter, attributes=["userPrincipalName"])
    except Exception as exc:
        logger.warning("LDAP directory search failed: %s", exc)
        return False
    finally:
        service_conn.unbind()

    if not service_conn.entries:
        return False
    entry = service_conn.entries[0]
    real_upn = str(entry.userPrincipalName) if getattr(entry, "userPrincipalName", None) else None
    if not real_upn:
        return False
    return _try_bind(server, real_upn, password)


def _try_bind(server, upn, password):
    """Attempts a single LDAP bind as `upn`; returns True on success."""
    from ldap3 import Connection

    try:
        connection = Connection(server, user=upn, password=password, auto_bind=True)
        connection.unbind()
        return True
    except Exception as exc:
        # DEBUG not WARNING: trying multiple domain suffixes and having all
        # but one fail is the normal, expected shape of a successful login.
        logger.debug("LDAP bind failed for %s: %s", upn, exc)
        return False
