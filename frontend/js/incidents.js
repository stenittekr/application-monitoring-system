(function () {
    initLayout("incidents");

    let applications = [];
    let servers = [];
    let users = [];
    const user = getCurrentUser();
    // ADMIN/IT_MANAGER/OPERATOR act on any incident; APP_OWNER only their own (enforced server-side).
    const canAct = ["ADMIN", "IT_MANAGER", "OPERATOR", "APP_OWNER"].includes(user.role);
    const isAdmin = user.role === "ADMIN";
    const canAssign = user.role === "ADMIN" || user.role === "IT_MANAGER"; // these roles can list users to populate the dropdown
    const canSeeServers = ["ADMIN", "IT_MANAGER", "OPERATOR", "AUDITOR"].includes(user.role); // APP_OWNER has no server access

    init();

    // Loads applications/servers (for filters + entity names) and, if allowed, users (for assignment).
    async function init() {
        try {
            applications = await api.get("/applications");
            if (canSeeServers) servers = await api.get("/servers");
            if (canAssign) users = await api.get("/users");
            populateFilters();
            await load();
        } catch (err) {
            showError(err);
        }
        document.getElementById("apply-filters-btn").addEventListener("click", load);
        document.getElementById("incidents-table-body").addEventListener("click", onTableClick);
        document.getElementById("assign-confirm-btn").addEventListener("click", onAssignConfirm);
        document.getElementById("incident-note-add").addEventListener("click", addNote);
        document.getElementById("incident-resolve-btn").addEventListener("click", resolveOpenIncident);
        document.getElementById("incident-reopen-btn").addEventListener("click", reopenIncident);
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

    // Preselect the status filter when arrived at from a dashboard stat card, so
    // "2 active incidents" lands on those two rather than on the whole history.
    const requestedStatus = new URLSearchParams(window.location.search).get("status");
    if (requestedStatus) {
        const control = document.getElementById("filter-status");
        if ([...control.options].some((o) => o.value === requestedStatus)) {
            control.value = requestedStatus;
        }
    }

    // Fetches incidents matching the current filters and renders the table.
    setInterval(load, 10000); // ponytail: matches the other list pages

    // A quiet inbox has two meanings - nothing is wrong, or nobody is being
    // told - and those must never look the same. The switch and its current
    // state live together, on the page that lists what would have been sent.
    async function showAlertingBanner() {
        const host = document.getElementById("alerting-banner");
        if (!host) return;
        try {
            const status = await api.get("/settings/alerting-status");
            const on = status.alerts_enabled;
            const tone = on ? (status.quiet_today ? "warning" : "success") : "warning";
            const icon = on ? "bi-bell" : "bi-bell-slash";

            let message;
            if (!on) {
                message = "<strong>Incident alert email is off.</strong> Nothing is being sent - "
                        + "not down alerts, not recovery. Everything below is still recorded.";
            } else if (status.quiet_today) {
                message = "<strong>Alert email is on, but today is a quiet day</strong>, so anything "
                        + "raised is held rather than sent.";
            } else {
                message = "<strong>Incident alert email is on.</strong> Alerts are being sent as "
                        + "incidents are raised.";
            }

            const control = isAdmin
                ? `<button class="btn btn-sm btn-${on ? "outline-danger" : "success"} ms-auto flex-shrink-0"
                       id="alerting-toggle" data-on="${on}">
                       ${on ? "Turn alert email off" : "Turn alert email on"}</button>`
                : "";

            host.innerHTML = `<div class="alert alert-${tone} d-flex align-items-center gap-2 py-2 mb-3">
                    <i class="bi ${icon}"></i>
                    <div class="small">${message}
                        <span class="text-muted d-block">Running on
                            ${escapeHtml(status.running_on || "unknown")}. Monitoring is unaffected either way.</span>
                    </div>
                    ${control}
                </div>`;

            const button = document.getElementById("alerting-toggle");
            if (button) button.addEventListener("click", () => toggleAlerting(button.dataset.on === "true"));
        } catch (err) {
            host.innerHTML = "";
        }
    }

    // Turning it ON is the dangerous direction: on a machine that cannot see
    // half the estate, that is a flood. Turning it off needs no ceremony.
    async function toggleAlerting(currentlyOn) {
        if (!currentlyOn) {
            const ok = await confirmAction(
                "Turn incident alert email back on?\n\n"
                + "Anything currently failing will start alerting. If this platform is running "
                + "somewhere that cannot reach the systems it monitors, those alerts will be wrong.");
            if (!ok) return;
        }
        try {
            await api.put("/settings/incident_alerts_enabled", { setting_value: currentlyOn ? "false" : "true" });
            showToast(currentlyOn ? "Alert email is now off. Incidents are still recorded."
                                  : "Alert email is now on.");
            await showAlertingBanner();
        } catch (err) {
            showError(err);
        }
    }

    showAlertingBanner();

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
            allIncidents = incidents;   // the detail modal looks rows up by id
            renderTable(incidents);
        } catch (err) {
            showError(err);
        }
    }

    // Renders the incidents table rows, looking up each incident's application/server details.
    function renderTable(incidents) {
        const tbody = document.getElementById("incidents-table-body");
        if (!incidents.length) {
            tbody.innerHTML = `<tr><td colspan="13" class="text-center text-muted py-4">No incidents found.</td></tr>`;
            return;
        }
        const appsById = Object.fromEntries(applications.map((a) => [a.id, a]));
        const serversById = Object.fromEntries(servers.map((s) => [s.id, s]));
        tbody.innerHTML = incidents.map((i) => renderRow(i, appsById, serversById)).join("");
    }

    // Builds the entity (application or server) name/link cell for one incident.
    // Severity decides who hears about an incident and when, so it has to be
    // visible - a routing rule nobody can see is indistinguishable from a bug.
    function severityBadge(severity) {
        if (!severity) return '<span class="text-muted">-</span>';
        const cls = { CRITICAL: "danger", HIGH: "danger", MEDIUM: "warning", LOW: "secondary" }[severity] || "secondary";
        return `<span class="badge bg-${cls}-subtle text-${cls}-emphasis border border-${cls}-subtle">${escapeHtml(severity)}</span>`;
    }

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
        // Notes, resolve and reopen live behind one button rather than three more
        // columns - the table is already wide.
        buttons.push(`<button class="btn btn-sm btn-outline-primary" data-action="open" data-id="${incident.id}">Details</button>`);
        if (incident.reopened_count > 0) {
            buttons.push(`<span class="badge bg-warning-subtle text-warning-emphasis"
                                title="Closed and reopened ${incident.reopened_count} time(s)">
                              reopened ${incident.reopened_count}x</span>`);
        }
        return buttons.join(" ") || "-";
    }

    let allIncidents = [];
    let openIncident = null;

    async function showIncident(incidentId) {
        const incident = allIncidents.find((i) => i.id === incidentId);
        if (!incident) return;
        openIncident = incident;

        document.getElementById("incident-modal-title").textContent =
            `Incident #${incident.id} - ${incident.status}`;
        document.getElementById("incident-summary").innerHTML = `
            <div class="small text-muted">Reason</div>
            <div class="mb-2">${escapeHtml(incident.reason || incident.error_message || "Not recorded")}</div>
            <div class="row small text-muted">
                <div class="col-sm-4">Detected: ${formatDateTime(incident.detected_at)}</div>
                <div class="col-sm-4">Resolved: ${incident.resolved_at ? formatDateTime(incident.resolved_at) : "-"}</div>
                <div class="col-sm-4">Kind: ${escapeHtml(incident.kind || "REACHABILITY")}</div>
            <div class="col-sm-4">Severity: ${severityBadge(incident.severity)}</div>
            </div>
            ${incident.resolution_category
                ? `<div class="small mt-2">Cause: <strong>${escapeHtml(incident.resolution_category)}</strong>
                   ${incident.resolution_note ? " - " + escapeHtml(incident.resolution_note) : ""}</div>`
                : ""}`;

        // Resolve applies to an open incident; reopen to a closed one. Never both.
        const isOpen = incident.status === "OPEN";
        document.getElementById("incident-resolve-panel").classList.toggle("d-none", !isOpen || !canAct);
        document.getElementById("incident-reopen-panel").classList.toggle("d-none", isOpen || !canAct);
        document.getElementById("incident-note-input").value = "";
        document.getElementById("incident-resolve-note").value = "";
        document.getElementById("incident-reopen-reason").value = "";

        await renderNotes(incident.id);
        new bootstrap.Modal(document.getElementById("incident-modal")).show();
    }

    async function renderNotes(incidentId) {
        const container = document.getElementById("incident-notes");
        try {
            const notes = await api.get(`/incidents/${incidentId}/notes`);
            container.innerHTML = notes.length
                ? notes.map((n) => `
                    <div class="border-start border-2 ps-2 mb-2">
                        <div class="small text-muted">
                            ${escapeHtml(n.user_name || "Unknown")} &middot; ${formatDateTime(n.created_at)}
                        </div>
                        <div>${escapeHtml(n.note)}</div>
                    </div>`).join("")
                : `<div class="text-muted small fst-italic">No notes yet.</div>`;
        } catch (err) {
            container.innerHTML = `<div class="text-muted small">Could not load notes.</div>`;
        }
    }

    async function addNote() {
        const input = document.getElementById("incident-note-input");
        const note = input.value.trim();
        if (!note || !openIncident) return;
        try {
            await api.post(`/incidents/${openIncident.id}/notes`, { note });
            input.value = "";
            await renderNotes(openIncident.id);
        } catch (err) {
            showError(err);
        }
    }

    async function resolveOpenIncident() {
        if (!openIncident) return;
        try {
            await api.post(`/incidents/${openIncident.id}/resolve`, {
                category: document.getElementById("incident-resolve-category").value,
                note: document.getElementById("incident-resolve-note").value.trim(),
            });
            bootstrap.Modal.getInstance(document.getElementById("incident-modal")).hide();
            await load();
        } catch (err) {
            showError(err);
        }
    }

    async function reopenIncident() {
        if (!openIncident) return;
        const reason = document.getElementById("incident-reopen-reason").value.trim();
        if (!reason) {
            showError(new Error("A reason is required to reopen an incident."));
            return;
        }
        try {
            await api.post(`/incidents/${openIncident.id}/reopen`, { reason });
            bootstrap.Modal.getInstance(document.getElementById("incident-modal")).hide();
            await load();
        } catch (err) {
            showError(err);
        }
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
                <td>${severityBadge(incident.severity)}</td>
                <td><span class="badge ${incident.status === "OPEN" ? "bg-danger" : "bg-success"}">${incident.status}</span></td>
                <td>${formatDateTime(incident.started_at)}</td>
                <td>${formatDateTime(incident.detected_at)}</td>
                <td>${formatDateTime(incident.resolved_at)}</td>
                <td>${durationLabel}</td>
                <td style="max-width:280px; white-space:normal;">${escapeHtml(incident.reason || "-")}</td>
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
        if (btn.dataset.action === "open") showIncident(incidentId);
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
