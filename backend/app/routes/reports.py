from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, Response

from app.auth.decorators import roles_required
from app.services import report_service
from app.utils.responses import success_response, error_response

bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def _parse_date(value, default=None):
    """Parses an ISO 8601 date string, falling back to a default when missing or invalid."""
    if not value:
        return default
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return default


def _get_filters():
    """Reads the common application/environment/date-range filters from the query string."""
    application_id = request.args.get("application_id", type=int)
    environment = request.args.get("environment")
    date_from = _parse_date(request.args.get("date_from"), datetime.now(timezone.utc) - timedelta(days=30))
    date_to = _parse_date(request.args.get("date_to"), datetime.now(timezone.utc))
    return application_id, environment, date_from, date_to


@bp.get("/availability")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR")
def availability():
    """Returns the availability report for the requested application and date range."""
    application_id, environment, date_from, date_to = _get_filters()
    rows = report_service.availability_report(application_id, environment, date_from, date_to)
    return success_response(rows)


@bp.get("/availability/daily")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR")
def daily_availability():
    """Returns day-by-day availability figures for a single application."""
    application_id = request.args.get("application_id", type=int)
    if not application_id:
        return error_response("application_id is required.", "MISSING_APPLICATION_ID", 400)
    _, _, date_from, date_to = _get_filters()
    rows = report_service.daily_availability(application_id, date_from, date_to)
    return success_response(rows)


@bp.get("/response-metrics")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR")
def response_metrics():
    """Mean time to detect, acknowledge and restore over the selected window."""
    return success_response(report_service.response_metrics(
        application_id=request.args.get("application_id", type=int),
        environment=request.args.get("environment"),
        date_from=_parse_date(request.args.get("date_from")),
        date_to=_parse_date(request.args.get("date_to")),
    ))


@bp.get("/failure-frequency")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR")
def failure_frequency():
    """Returns how often failures occurred for the requested application and date range."""
    application_id, _, date_from, date_to = _get_filters()
    rows = report_service.failure_frequency(application_id, date_from, date_to)
    return success_response(rows)


@bp.get("/availability/export")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR")
def export_availability():
    """Exports the availability report as a downloadable CSV file."""
    application_id, environment, date_from, date_to = _get_filters()
    rows = report_service.availability_report(application_id, environment, date_from, date_to)
    csv_text = report_service.export_availability_csv(rows)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=availability_report.csv"},
    )


@bp.get("/availability/export.xlsx")
@roles_required("ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR")
def export_availability_xlsx():
    """Exports the availability report as an Excel workbook (FR-024).

    Carries a second sheet stating the range, the timezone and how each figure
    was calculated. §17 requires that, and a spreadsheet is exactly where those
    caveats get separated from the numbers if they are not attached to them.
    """
    from datetime import datetime, timezone

    application_id, environment, date_from, date_to = _get_filters()
    rows = report_service.availability_report(application_id, environment, date_from, date_to)
    meta = {
        "Report": "Availability by application",
        "From": date_from.isoformat(),
        "To": date_to.isoformat(),
        "Timezone": "UTC",
        "Environment filter": environment or "all",
        "Generated": datetime.now(timezone.utc).isoformat(),
        "Applications included": len(rows),
    }
    workbook = report_service.export_availability_xlsx(rows, meta)
    return Response(
        workbook,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=availability_report.xlsx"},
    )
