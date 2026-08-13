(function () {
    initLayout("incidents");

    let applications = [];

    init();

    // Loads the applications list (for filter dropdowns), then loads the initial incidents table.
    async function init() {
        try {
            applications = await api.get("/applications");
            populateFilters();
            await load();
        } catch (err) {
            showError(err);
        }
        document.getElementById("apply-filters-btn").addEventListener("click", load);
    }

    // Fills the application and environment filter dropdowns from the loaded applications.
    function populateFilters() {
        const appSelect = document.getElementById("filter-application");
        applications.forEach((a) => {
            const opt = document.createElement("option");
            opt.value = a.id;
            opt.textContent = a.name;
            appSelect.appendChild(opt);
        });

        const environments = [...new Set(applications.map((a) => a.environment))];
        const envSelect = document.getElementById("filter-environment");
        environments.forEach((e) => {
            const opt = document.createElement("option");
            opt.value = e;
            opt.textContent = e;
            envSelect.appendChild(opt);
        });
    }

    // Fetches incidents matching the current filters and renders the table.
    async function load() {
        const params = new URLSearchParams();
        const appId = document.getElementById("filter-application").value;
        const status = document.getElementById("filter-status").value;
        const environment = document.getElementById("filter-environment").value;
        const dateFrom = document.getElementById("filter-date-from").value;
        const dateTo = document.getElementById("filter-date-to").value;
        if (appId) params.set("application_id", appId);
        if (status) params.set("status", status);
        if (environment) params.set("environment", environment);
        if (dateFrom) params.set("date_from", dateFrom);
        if (dateTo) params.set("date_to", dateTo);

        try {
            const incidents = await api.get(`/incidents?${params.toString()}`);
            renderTable(incidents);
        } catch (err) {
            showError(err);
        }
    }

    // Renders the incidents table rows, looking up each incident's application details.
    function renderTable(incidents) {
        const tbody = document.getElementById("incidents-table-body");
        if (!incidents.length) {
            tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-4">No incidents found.</td></tr>`;
            return;
        }
        const appsById = Object.fromEntries(applications.map((a) => [a.id, a]));
        tbody.innerHTML = incidents.map((i) => {
            const app = appsById[i.application_id];
            return `
                <tr>
                    <td><a href="application-details.html?id=${i.application_id}">${escapeHtml(app ? app.name : "#" + i.application_id)}</a></td>
                    <td>${escapeHtml(app ? app.environment : "-")}</td>
                    <td><span class="badge ${i.status === "OPEN" ? "bg-danger" : "bg-success"}">${i.status}</span></td>
                    <td>${formatDateTime(i.started_at)}</td>
                    <td>${formatDateTime(i.detected_at)}</td>
                    <td>${formatDateTime(i.resolved_at)}</td>
                    <td>${i.duration_seconds !== null ? Math.round(i.duration_seconds / 60) + " min" : "-"}</td>
                    <td class="text-truncate" style="max-width:200px" title="${escapeHtml(i.reason || "")}">${escapeHtml(i.reason || "-")}</td>
                    <td>${i.http_status_code ?? "-"}</td>
                    <td>${i.notification_sent ? '<i class="bi bi-check-circle text-success" title="Sent"></i>' : '<i class="bi bi-dash-circle text-muted" title="Not sent"></i>'}</td>
                </tr>`;
        }).join("");
    }
})();
