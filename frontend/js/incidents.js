(function () {
    initLayout("incidents");

    let applications = [];
    let servers = [];
    let users = [];
    const user = getCurrentUser();
    const canAct = user.role === "ADMIN" || user.role === "MANAGER";
    const canAssign = user.role === "ADMIN"; // only ADMIN can list users to populate the assign dropdown

    init();

    // Loads applications/servers (for filters + entity names) and, if allowed, users (for assignment).
    async function init() {
        try {
            applications = await api.get("/applications");
            servers = await api.get("/servers");
            if (canAssign) users = await api.get("/users");
            populateFilters();
            await load();
        } catch (err) {
            showError(err);
        }
        document.getElementById("apply-filters-btn").addEventListener("click", load);
        document.getElementById("incidents-table-body").addEventListener("click", onTableClick);
        document.getElementById("assign-confirm-btn").addEventListener("click", onAssignConfirm);
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

    // Renders the incidents table rows, looking up each incident's application/server details.
    function renderTable(incidents) {
        const tbody = document.getElementById("incidents-table-body");
        if (!incidents.length) {
            tbody.innerHTML = `<tr><td colspan="12" class="text-center text-muted py-4">No incidents found.</td></tr>`;
            return;
        }
        const appsById = Object.fromEntries(applications.map((a) => [a.id, a]));
        const serversById = Object.fromEntries(servers.map((s) => [s.id, s]));
        tbody.innerHTML = incidents.map((i) => renderRow(i, appsById, serversById)).join("");
    }

    // Builds the entity (application or server) name/link cell for one incident.
    function entityCell(incident, app, server) {
        if (app) return `<a href="application-details.html?id=${incident.application_id}">${escapeHtml(app.name)}</a>`;
        const label = server ? server.hostname : "#" + incident.server_id;
        return `<i class="bi bi-hdd-network me-1"></i>${escapeHtml(label)}`;
    }

    // Builds the action buttons (acknowledge/assign) available for one incident, per the current user's role.
    function actionButtons(incident) {
        const buttons = [];
        if (canAct && incident.status === "OPEN" && !incident.acknowledged_at) {
            buttons.push(`<button class="btn btn-sm btn-outline-secondary" data-action="acknowledge" data-id="${incident.id}">Acknowledge</button>`);
        }
        if (canAssign && incident.status === "OPEN") {
            const label = incident.assigned_to ? "Reassign" : "Assign";
            buttons.push(`<button class="btn btn-sm btn-outline-secondary" data-action="assign" data-id="${incident.id}">${label}</button>`);
        }
        return buttons.join(" ") || "-";
    }

    // Renders one incident as a table row.
    function renderRow(incident, appsById, serversById) {
        const app = incident.application_id ? appsById[incident.application_id] : null;
        const server = incident.server_id ? serversById[incident.server_id] : null;
        const durationLabel = incident.duration_seconds !== null ? Math.round(incident.duration_seconds / 60) + " min" : "-";
        const notificationIcon = incident.notification_sent
            ? '<i class="bi bi-check-circle text-success" title="Sent"></i>'
            : '<i class="bi bi-dash-circle text-muted" title="Not sent"></i>';
        const acknowledgedLabel = incident.acknowledged_at ? formatDateTime(incident.acknowledged_at) : "-";
        const assignedLabel = incident.assigned_to ? escapeHtml(incident.assigned_to.name) : "-";
        return `
            <tr>
                <td>${entityCell(incident, app, server)}</td>
                <td>${escapeHtml(app ? app.environment : "-")}</td>
                <td><span class="badge ${incident.status === "OPEN" ? "bg-danger" : "bg-success"}">${incident.status}</span></td>
                <td>${formatDateTime(incident.started_at)}</td>
                <td>${formatDateTime(incident.detected_at)}</td>
                <td>${formatDateTime(incident.resolved_at)}</td>
                <td>${durationLabel}</td>
                <td class="text-truncate" style="max-width:200px" title="${escapeHtml(incident.reason || "")}">${escapeHtml(incident.reason || "-")}</td>
                <td>${notificationIcon}</td>
                <td>${acknowledgedLabel}</td>
                <td>${assignedLabel}</td>
                <td>${actionButtons(incident)}</td>
            </tr>`;
    }

    let assignIncidentId = null;

    function onTableClick(event) {
        const btn = event.target.closest("button[data-action]");
        if (!btn) return;
        const incidentId = Number(btn.dataset.id);
        if (btn.dataset.action === "acknowledge") acknowledgeIncident(incidentId);
        if (btn.dataset.action === "assign") openAssignModal(incidentId);
    }

    async function acknowledgeIncident(incidentId) {
        try {
            await api.post(`/incidents/${incidentId}/acknowledge`);
            showToast("Incident acknowledged.");
            await load();
        } catch (err) {
            showError(err);
        }
    }

    function openAssignModal(incidentId) {
        assignIncidentId = incidentId;
        const select = document.getElementById("assign-user-select");
        select.innerHTML = users.map((u) => `<option value="${u.id}">${escapeHtml(u.name)} (${escapeHtml(u.role)})</option>`).join("");
        new bootstrap.Modal(document.getElementById("assign-modal")).show();
    }

    async function onAssignConfirm() {
        const userId = document.getElementById("assign-user-select").value;
        if (!userId || !assignIncidentId) return;
        try {
            await api.post(`/incidents/${assignIncidentId}/assign`, { user_id: Number(userId) });
            bootstrap.Modal.getInstance(document.getElementById("assign-modal")).hide();
            showToast("Incident assigned.");
            await load();
        } catch (err) {
            showError(err);
        }
    }
})();
