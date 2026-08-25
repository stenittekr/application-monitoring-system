(function () {
    initLayout("reports");

    let applications = [];

    document.getElementById("apply-filters-btn").addEventListener("click", load);
    document.getElementById("export-btn").addEventListener("click", exportCsv);

    init();
    // The report only reloaded on "Apply filters", so figures went stale while
    // the page sat open. load() rebuilds the query from the current filters, so
    // polling respects whatever the user has selected. 30s rather than the 5s
    // used elsewhere: this endpoint aggregates every health check in the window.
    setInterval(load, 30000);

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
    // MTTD / MTTA / MTTR. Each tile carries the sample it was averaged over:
    // a four-minute MTTA drawn from one incident out of forty is not a number
    // anyone should plan around, and hiding that makes the figure a lie.
    async function loadResponseMetrics() {
        const container = document.getElementById("response-metrics");
        try {
            const m = await api.get(`/reports/response-metrics?${buildQuery()}`);
            const tiles = [
                { label: "Mean time to detect", value: m.mttd_minutes, sample: m.mttd_sample,
                  hint: "Outage began to platform noticed" },
                { label: "Mean time to acknowledge", value: m.mtta_minutes, sample: m.mtta_sample,
                  hint: "Noticed to a person picking it up" },
                { label: "Mean time to restore", value: m.mttr_minutes, sample: m.mttr_sample,
                  hint: "Noticed to service returning" },
                { label: "Incidents in window", value: m.incidents, sample: null, raw: true,
                  hint: `${m.unacknowledged} never acknowledged, ${m.unresolved} still open` },
            ];
            container.innerHTML = tiles.map((t) => `
                <div class="col-6 col-xl-3">
                    <div class="card border-0 shadow-sm h-100">
                        <div class="card-body">
                            <div class="text-muted small mb-2">${t.label}</div>
                            <div class="stat-value text-primary">${
                                t.value === null || t.value === undefined
                                    ? `<span class="fs-6 fst-italic text-muted">No data</span>`
                                    : (t.raw ? t.value : `${t.value}<span class="fs-6 text-muted"> min</span>`)
                            }</div>
                            <div class="small text-muted mt-2">${escapeHtml(t.hint)}</div>
                            ${t.sample !== null && t.sample !== undefined
                                ? `<div class="small text-muted fst-italic">from ${t.sample} incident(s)</div>` : ""}
                        </div>
                    </div>
                </div>`).join("");
        } catch (err) {
            container.innerHTML = "";
        }
    }

    async function load() {
        loadResponseMetrics();
        try {
            const rows = await api.get(`/reports/availability?${buildQuery()}`);
            renderTable(rows);
        } catch (err) {
            showError(err);
        }
    }

    // Picks a color/label for an availability percentage over the report window.
    // Deliberately NOT the UP/DOWN/DEGRADED words used for live status elsewhere -
    // this reflects a historical score, not whether the app is up right now.
    function availabilityTier(percent) {
        if (percent >= 99) return { cls: "bg-success-subtle text-success-emphasis border", label: "Healthy" };
        if (percent >= 95) return { cls: "bg-warning-subtle text-warning-emphasis border", label: "At Risk" };
        return { cls: "bg-danger-subtle text-danger-emphasis border", label: "Poor" };
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
                <td><span class="badge ${availabilityTier(r.availability_percent).cls}">${availabilityTier(r.availability_percent).label}</span> ${r.availability_percent}%</td>
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
