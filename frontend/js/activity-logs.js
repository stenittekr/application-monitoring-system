(function () {
    initLayout("activity-logs");

    document.getElementById("apply-filters-btn").addEventListener("click", load);
    load();

    // Builds the query string from the current filter inputs.
    function buildQuery() {
        const params = new URLSearchParams();
        const entityType = document.getElementById("filter-entity-type").value;
        const action = document.getElementById("filter-action").value.trim();
        const dateFrom = document.getElementById("filter-date-from").value;
        if (entityType) params.set("entity_type", entityType);
        if (action) params.set("action", action);
        if (dateFrom) params.set("date_from", dateFrom);
        params.set("limit", "200");
        return params.toString();
    }

    // Fetches activity log entries matching the current filters and renders the table.
    async function load() {
        try {
            const logs = await api.get(`/activity-logs?${buildQuery()}`);
            renderTable(logs);
        } catch (err) {
            showError(err);
        }
    }

    // Renders the activity log table rows.
    function renderTable(logs) {
        const tbody = document.getElementById("logs-table-body");
        if (!logs.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">No activity recorded.</td></tr>`;
            return;
        }
        tbody.innerHTML = logs.map((l) => `
            <tr>
                <td>${formatDateTime(l.created_at)}</td>
                <td>${escapeHtml(l.user_name || "System")}</td>
                <td><code>${escapeHtml(l.action)}</code></td>
                <td>${escapeHtml(l.entity_type || "-")}${l.entity_id ? " #" + l.entity_id : ""}</td>
                <td class="text-truncate" style="max-width:400px" title="${escapeHtml(l.description || "")}">${escapeHtml(l.description || "-")}</td>
                <td>${escapeHtml(l.ip_address || "-")}</td>
            </tr>`).join("");
    }
})();
