(function () {
    initLayout("reports");

    let applications = [];

    document.getElementById("apply-filters-btn").addEventListener("click", load);
    document.getElementById("export-btn").addEventListener("click", exportCsv);

    init();

    // Loads the application dropdown, then loads the initial report.
    async function init() {
        try {
            applications = await api.get("/applications");
            document.getElementById("filter-application").innerHTML = `<option value="">All</option>` +
                applications.map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join("");
        } catch (err) {
            showError(err);
        }
        await load();
    }

    // Builds the query string from the current filter inputs.
    function buildQuery() {
        const params = new URLSearchParams();
        const applicationId = document.getElementById("filter-application").value;
        const dateFrom = document.getElementById("filter-date-from").value;
        const dateTo = document.getElementById("filter-date-to").value;
        if (applicationId) params.set("application_id", applicationId);
        if (dateFrom) params.set("date_from", dateFrom);
        if (dateTo) params.set("date_to", dateTo);
        return params.toString();
    }

    // Fetches the availability report matching the current filters and renders the table.
    async function load() {
        try {
            const rows = await api.get(`/reports/availability?${buildQuery()}`);
            renderTable(rows);
        } catch (err) {
            showError(err);
        }
    }

    // Picks the status-badge color tier for an availability percentage.
    function availabilityTier(percent) {
        if (percent >= 99) return "UP";
        if (percent >= 95) return "DEGRADED";
        return "DOWN";
    }

    // Renders the availability report table rows.
    function renderTable(rows) {
        const tbody = document.getElementById("report-table-body");
        if (!rows.length) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">No data for this range.</td></tr>`;
            return;
        }
        tbody.innerHTML = rows.map((r) => `
            <tr>
                <td>${escapeHtml(r.application_name)}</td>
                <td>${escapeHtml(r.environment)}</td>
                <td>${r.successful_checks}/${r.total_checks}</td>
                <td>${statusBadge(availabilityTier(r.availability_percent))} ${r.availability_percent}%</td>
                <td>${r.avg_response_time !== null ? Math.round(r.avg_response_time) + " ms" : "-"}</td>
                <td>${r.incident_count}</td>
                <td>${formatMinutes(r.avg_downtime_seconds)}</td>
                <td>${formatMinutes(r.total_downtime_seconds)}</td>
            </tr>`).join("");
    }

    function formatMinutes(seconds) {
        return seconds ? Math.round(seconds / 60) + " min" : "-";
    }

    // Downloads the current filtered report as a CSV file.
    async function exportCsv() {
        try {
            const response = await api.get(`/reports/availability/export?${buildQuery()}`);
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = "availability_report.csv";
            link.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            showError(err);
        }
    }
})();
