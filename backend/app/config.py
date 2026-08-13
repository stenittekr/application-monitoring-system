"""Application configuration, read entirely from environment variables."""
import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Config:
    """Application configuration values, loaded from environment variables with sane defaults."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRES_SECONDS", 28800))  # 8h
    JWT_TOKEN_LOCATION = ["headers"]

    SQL_SERVER = os.environ.get("SQL_SERVER", "localhost")
    SQL_DATABASE = os.environ.get("SQL_DATABASE", "ApplicationMonitoringDB")
    SQL_USERNAME = os.environ.get("SQL_USERNAME", "")
    SQL_PASSWORD = os.environ.get("SQL_PASSWORD", "")
    SQL_DRIVER = os.environ.get("SQL_DRIVER", "ODBC Driver 17 for SQL Server")

    @property
    def SQLALCHEMY_DATABASE_URI(self):
        """Builds the SQL Server connection string, or uses DATABASE_URL if it's set."""
        override = os.environ.get("DATABASE_URL")
        if override:
            return override
        driver = quote_plus(self.SQL_DRIVER)
        if self.SQL_USERNAME:
            auth = f"{quote_plus(self.SQL_USERNAME)}:{quote_plus(self.SQL_PASSWORD)}@"
        else:
            auth = ""
        return (
            f"mssql+pyodbc://{auth}{self.SQL_SERVER}/{self.SQL_DATABASE}"
            f"?driver={driver}&TrustServerCertificate=yes"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 25))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "monitoring@example.com")

    MONITOR_INTERVAL = int(os.environ.get("MONITOR_INTERVAL", 30))
    DEFAULT_TIMEOUT = int(os.environ.get("DEFAULT_TIMEOUT", 10))
    DEFAULT_RETRY_COUNT = int(os.environ.get("DEFAULT_RETRY_COUNT", 3))
    DEFAULT_RETRY_DELAY = int(os.environ.get("DEFAULT_RETRY_DELAY", 5))

    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

    LDAP_SERVER = os.environ.get("LDAP_SERVER", "")
    LDAP_PORT = int(os.environ.get("LDAP_PORT", 389))
    LDAP_BASE_DN = os.environ.get("LDAP_BASE_DN", "")
    LDAP_BIND_DN = os.environ.get("LDAP_BIND_DN", "")
    LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "")
    LDAP_DOMAINS = [d.strip() for d in os.environ.get("LDAP_DOMAINS", "").split(",") if d.strip()]


# SQLALCHEMY_DATABASE_URI must be resolvable as a class attribute for Flask's
# app.config.from_object(); instantiate once and copy it across.
Config.SQLALCHEMY_DATABASE_URI = Config().SQLALCHEMY_DATABASE_URI
