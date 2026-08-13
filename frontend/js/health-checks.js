(function () {
    initLayout("health-checks");

    document.getElementById("apply-filters-btn").addEventListener("click", load);

    init();

    // Loads the application dropdown, then loads the initial (unfiltered) health-check list.
    async function init() {
        try {
            const apps = await api.get("/applications");
            document.getElementById("filter-application").innerHTML = `<option value="">All</option>` +
                apps.map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join("");
        } catch (err) {
            showError(err);
        }
        await load();
    }

    // Builds the query string from the current filter inputs.
    function buildQuery() {
        const params = new URLSearchParams();
        const applicationId = document.getElementById("filter-application").value;
        const status = document.getElementById("filter-status").value;
        const from = document.getElementById("filter-date-from").value;
        const to = document.getElementById("filter-date-to").value;
        if (applicationId) params.set("application_id", applicationId);
        if (status) params.set("status", status);
        if (from) params.set("date_from", from);
        if (to) params.set("date_to", to);
        params.set("limit", "200");
        return params.toString();
    }

    // Fetches health checks matching the current filters and renders the table.
    async function load() {
        try {
            const checks = await api.get(`/health-checks?${buildQuery()}`);
            renderTable(checks);
        } catch (err) {
            showError(err);
        }
    }

    // Renders the health-checks table rows.
    function renderTable(checks) {
        const tbody = document.getElementById("health-checks-table-body");
        if (!checks.length) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">No health checks recorded.</td></tr>`;
            return;
        }
        tbody.innerHTML = checks.map((c) => `
            <tr>
                <td>${formatDateTime(c.checked_at)}</td>
                <td>${escapeHtml(c.application_name)}</td>
                <td>${statusBadge(c.status)}</td>
                <td>${c.http_status_code ?? "-"}</td>
                <td>${c.response_time ? Math.round(c.response_time) + " ms" : "-"}</td>
                <td>${c.attempt_number}</td>
                <td class="text-truncate" style="max-width:250px" title="${escapeHtml(c.error_message || "")}">${escapeHtml(c.error_message || "-")}</td>
            </tr>`).join("");
    }
})();
