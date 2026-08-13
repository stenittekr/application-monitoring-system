"""Manual/on-demand health-check trigger used by the Flask API.

The actual check + retry + incident/notification logic lives in
app.services.monitoring_service, so the API and the standalone
monitoring/ worker process share one implementation.
"""
from app.services.monitoring_service import run_health_check

__all__ = ["run_health_check"]
