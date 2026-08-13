/** Powers both applications.html (list + CRUD) and application-details.html (detail view). */
(function () {
    // Returns the display string for what an app's health check hits (host:port or URL).
    function targetLabel(app) {
        return app.health_check_type === "TCP" ? `${app.server}:${app.port}` : (app.url || "-");
    }


    if (document.getElementById("applications-page")) {
        initLayout("applications");
        runApplicationsList();
    } else if (document.getElementById("app-details-page")) {
        initLayout("applications");
        runApplicationDetails();
    }

    // Sets up and drives the applications list page (table, create/edit modal, actions).
    function runApplicationsList() {
        const user = getCurrentUser();
        const isAdmin = user.role === "ADMIN";
        const modalEl = document.getElementById("app-form-modal");
        const modal = new bootstrap.Modal(modalEl);
        const form = document.getElementById("app-form");

        if (isAdmin) {
            document.getElementById("new-app-btn").classList.remove("d-none");
            // Opens the modal in "new application" mode.
            document.getElementById("new-app-btn").addEventListener("click", () => openForm(null));
        }

        form.addEventListener("submit", onSubmit);
        document.getElementById("app-health-check-type").addEventListener("change", toggleCheckTypeFields);
        load();

        // Shows the URL field for HTTP(S) checks or the server/port fields for TCP checks.
        function toggleCheckTypeFields() {
            const isTcp = document.getElementById("app-health-check-type").value === "TCP";
            document.getElementById("app-url-group").classList.toggle("d-none", isTcp);
            document.getElementById("app-server-group").classList.toggle("d-none", !isTcp);
            document.getElementById("app-port-group").classList.toggle("d-none", !isTcp);
        }

        // Fetches the applications list and re-renders the table.
        async function load() {
            try {
                const apps = await api.get("/applications");
                renderTable(apps, isAdmin);
                maybeOpenFromEditParam(apps);
            } catch (err) {
                showError(err);
            }
        }

        // Auto-opens the edit modal for the app named in the ?edit= URL query param, if any.
        function maybeOpenFromEditParam(apps) {
            const editId = new URLSearchParams(window.location.search).get("edit");
            if (!editId) return;
            history.replaceState(null, "", "applications.html");
            const app = apps.find((a) => String(a.id) === editId);
            if (app && isAdmin) openForm(app);
        }

        // Renders the applications table rows, including admin-only action buttons.
        function renderTable(apps, isAdmin) {
            const tbody = document.getElementById("applications-table-body");
            if (!apps.length) {
                tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted py-4">No applications yet.</td></tr>`;
                return;
            }
            tbody.innerHTML = apps.map((app) => `
                <tr>
                    <td>${escapeHtml(app.name)}</td>
                    <td>${escapeHtml(app.environment)}</td>
                    <td><span class="badge bg-light text-dark border me-1">${app.health_check_type}</span>${escapeHtml(targetLabel(app))}</td>
                    <td>${statusBadge(app.current_status)}${app.in_maintenance ? ' <span class="badge bg-info-subtle text-info-emphasis border">Maintenance</span>' : ""}</td>
                    <td>${app.monitoring_enabled ? '<span class="text-success">Enabled</span>' : '<span class="text-muted">Disabled</span>'}</td>
                    <td>${formatDateTime(app.last_checked_at)}</td>
                    <td>${escapeHtml(app.owner_name)}</td>
                    <td>${escapeHtml(app.manager_name)}</td>
                    <td class="btn-group btn-group-sm">
                        <a class="btn btn-outline-primary" title="View / History" href="application-details.html?id=${app.id}"><i class="bi bi-eye"></i></a>
                        ${isAdmin ? `
                            <button class="btn btn-outline-secondary" title="Edit" onclick='window.__editApp(${JSON.stringify(app)})'><i class="bi bi-pencil"></i></button>
                            <button class="btn btn-outline-secondary" title="Run Check" onclick="window.__runCheck(${app.id})"><i class="bi bi-play-circle"></i></button>
                            <button class="btn btn-outline-secondary" title="${app.monitoring_enabled ? "Disable" : "Enable"} Monitoring"
                                onclick="window.__toggleMonitoring(${app.id}, ${!app.monitoring_enabled})">
                                <i class="bi ${app.monitoring_enabled ? "bi-toggle-on" : "bi-toggle-off"}"></i>
                            </button>
                            <button class="btn btn-outline-danger" title="Deactivate" onclick="window.__deleteApp(${app.id})"><i class="bi bi-trash"></i></button>
                        ` : ""}
                    </td>
                </tr>`).join("");
        }

        // Fills the create/edit form with an existing app's data (or blank defaults) and opens the modal.
        function openForm(app) {
            document.getElementById("app-form-title").textContent = app ? "Edit Application" : "New Application";
            document.getElementById("app-id").value = app ? app.id : "";
            document.getElementById("app-name").value = app ? app.name : "";
            document.getElementById("app-environment").value = app ? app.environment : "Production";
            document.getElementById("app-description").value = app ? (app.description || "") : "";
            document.getElementById("app-health-check-type").value = app ? app.health_check_type : "HTTP";
            document.getElementById("app-url").value = app ? (app.url || "") : "";
            document.getElementById("app-server").value = app ? (app.server || "") : "";
            document.getElementById("app-port").value = app ? (app.port || "") : "";
            toggleCheckTypeFields();
            document.getElementById("app-owner-name").value = app ? app.owner_name : "";
            document.getElementById("app-owner-email").value = app ? app.owner_email : "";
            document.getElementById("app-manager-name").value = app ? app.manager_name : "";
            document.getElementById("app-manager-email").value = app ? app.manager_email : "";
            document.getElementById("app-interval").value = app ? app.monitoring_interval : 60;
            document.getElementById("app-timeout").value = app ? app.timeout : 10;
            document.getElementById("app-retry-count").value = app ? app.retry_count : 3;
            document.getElementById("app-retry-delay").value = app ? app.retry_delay : 5;
            document.getElementById("app-expected-status").value = app ? app.expected_status_code : 200;
            document.getElementById("app-monitoring-enabled").checked = app ? app.monitoring_enabled : true;
            document.getElementById("app-verify-ssl").checked = app ? app.verify_ssl !== false : true;
            modal.show();
        }

        // Reads the form fields and creates or updates the application via the API.
        async function onSubmit(event) {
            event.preventDefault();
            const id = document.getElementById("app-id").value;
            const healthCheckType = document.getElementById("app-health-check-type").value;
            const payload = {
                name: document.getElementById("app-name").value.trim(),
                environment: document.getElementById("app-environment").value,
                description: document.getElementById("app-description").value.trim(),
                health_check_type: healthCheckType,
                url: document.getElementById("app-url").value.trim(),
                server: document.getElementById("app-server").value.trim(),
                port: document.getElementById("app-port").value ? Number(document.getElementById("app-port").value) : null,
                owner_name: document.getElementById("app-owner-name").value.trim(),
                owner_email: document.getElementById("app-owner-email").value.trim(),
                manager_name: document.getElementById("app-manager-name").value.trim(),
                manager_email: document.getElementById("app-manager-email").value.trim(),
                monitoring_interval: Number(document.getElementById("app-interval").value),
                timeout: Number(document.getElementById("app-timeout").value),
                retry_count: Number(document.getElementById("app-retry-count").value),
                retry_delay: Number(document.getElementById("app-retry-delay").value),
                expected_status_code: Number(document.getElementById("app-expected-status").value),
                monitoring_enabled: document.getElementById("app-monitoring-enabled").checked,
                verify_ssl: document.getElementById("app-verify-ssl").checked,
            };
            try {
                if (id) {
                    await api.put(`/applications/${id}`, payload);
                    showToast("Application updated.");
                } else {
                    await api.post("/applications", payload);
                    showToast("Application created.");
                }
                modal.hide();
                await load();
            } catch (err) {
                showError(err);
            }
        }

        // Exposes openForm as the row "Edit" button handler.
        window.__editApp = openForm;

        // Triggers an immediate health check for one application (row "Run Check" button).
        window.__runCheck = async (id) => {
            try {
                await api.post(`/applications/${id}/check`);
                showToast("Health check completed.");
                await load();
            } catch (err) {
                showError(err);
            }
        };

        // Enables or disables monitoring for one application (row toggle button).
        window.__toggleMonitoring = async (id, enable) => {
            try {
                await api.post(`/applications/${id}/${enable ? "enable-monitoring" : "disable-monitoring"}`);
                showToast(`Monitoring ${enable ? "enabled" : "disabled"}.`);
                await load();
            } catch (err) {
                showError(err);
            }
        };

        // Deactivates (soft-deletes) an application after confirmation (row "Deactivate" button).
        window.__deleteApp = async (id) => {
            const ok = await confirmAction("Deactivate this application? It will stop being monitored.");
            if (!ok) return;
            try {
                await api.del(`/applications/${id}`);
                showToast("Application deactivated.");
                await load();
            } catch (err) {
                showError(err);
            }
        };
    }

    // Sets up and drives the single-application details page (stats, info, incidents, health checks).
    function runApplicationDetails() {
        const id = new URLSearchParams(window.location.search).get("id");
        if (!id) {
            document.getElementById("details-name").textContent = "No application selected.";
            return;
        }
        load();

        // Fetches the app, its health checks, and its incidents, then re-renders every section.
        async function load() {
            try {
                const [app, healthChecks, incidents] = await Promise.all([
                    api.get(`/applications/${id}`),
                    api.get(`/applications/${id}/health-checks?limit=100`),
                    api.get(`/applications/${id}/incidents`),
                ]);
                renderHeader(app);
                renderStats(healthChecks, incidents);
                renderInfo(app);
                renderIncidents(incidents);
                renderHealthChecks(healthChecks);
            } catch (err) {
                showError(err);
            }
        }

        // Renders the page title, status badge, and (for admins) the edit/run-check buttons.
        function renderHeader(app) {
            document.getElementById("details-name").textContent = app.name;
            document.getElementById("details-status").innerHTML = statusBadge(app.current_status);
            const user = getCurrentUser();
            if (user.role === "ADMIN") {
                document.getElementById("details-actions").innerHTML = `
                    <button class="btn btn-outline-secondary" onclick="window.__editFromDetails()"><i class="bi bi-pencil"></i> Edit</button>
                    <button class="btn btn-outline-secondary" onclick="window.__runCheckFromDetails(${app.id})"><i class="bi bi-play-circle"></i> Run Check</button>`;
            }
            window.__currentApp = app;
        }

        // Computes and displays availability %, average response time, and total downtime.
        function renderStats(healthChecks, incidents) {
            const total = healthChecks.length;
            const successful = healthChecks.filter((h) => h.success).length;
            const availability = total ? ((successful / total) * 100).toFixed(2) : "-";
            document.getElementById("details-availability").textContent = total ? `${availability}%` : "-";

            const responseTimes = healthChecks.filter((h) => h.success).map((h) => h.response_time);
            const avg = responseTimes.length ? Math.round(responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length) : null;
            document.getElementById("details-avg-response").textContent = avg !== null ? `${avg} ms` : "-";

            const totalDowntime = incidents.filter((i) => i.status === "RESOLVED")
                .reduce((sum, i) => sum + (i.duration_seconds || 0), 0);
            document.getElementById("details-downtime").textContent = formatDuration(totalDowntime);
        }

        // Renders the app's general info and configuration detail tables.
        function renderInfo(app) {
            const targetRow = app.health_check_type === "TCP"
                ? `<tr><th>Server / Port</th><td>${escapeHtml(app.server)}:${app.port}</td></tr>`
                : `<tr><th>URL</th><td><a href="${app.url}" target="_blank" rel="noopener">${escapeHtml(app.url)}</a></td></tr>`;
            document.getElementById("details-info-table").innerHTML = `
                <tr><th>Health Check Type</th><td>${app.health_check_type}</td></tr>
                ${targetRow}
                <tr><th>Environment</th><td>${escapeHtml(app.environment)}</td></tr>
                <tr><th>Description</th><td>${escapeHtml(app.description || "-")}</td></tr>
                <tr><th>Owner</th><td>${escapeHtml(app.owner_name)} &lt;${escapeHtml(app.owner_email)}&gt;</td></tr>
                <tr><th>Manager</th><td>${escapeHtml(app.manager_name)} &lt;${escapeHtml(app.manager_email)}&gt;</td></tr>
                <tr><th>Last Checked</th><td>${formatDateTime(app.last_checked_at)}</td></tr>
                <tr><th>Last Successful Check</th><td>${formatDateTime(app.last_successful_check_at)}</td></tr>
                <tr><th>Last Failed Check</th><td>${formatDateTime(app.last_failed_check_at)}</td></tr>`;

            document.getElementById("details-config-table").innerHTML = `
                <tr><th>Monitoring Enabled</th><td>${app.monitoring_enabled ? "Yes" : "No"}</td></tr>
                <tr><th>Monitoring Interval</th><td>${app.monitoring_interval}s</td></tr>
                <tr><th>Timeout</th><td>${app.timeout}s</td></tr>
                <tr><th>Retry Count</th><td>${app.retry_count}</td></tr>
                <tr><th>Retry Delay</th><td>${app.retry_delay}s</td></tr>
                <tr><th>Expected Status Code</th><td>${app.expected_status_code}</td></tr>`;
        }

        // Renders the app's incident history table.
        function renderIncidents(incidents) {
            const tbody = document.getElementById("details-incidents-body");
            if (!incidents.length) {
                tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">No incidents recorded.</td></tr>`;
                return;
            }
            tbody.innerHTML = incidents.map((i) => `
                <tr>
                    <td><span class="badge ${i.status === "OPEN" ? "bg-danger" : "bg-success"}">${i.status}</span></td>
                    <td>${formatDateTime(i.started_at)}</td>
                    <td>${formatDateTime(i.resolved_at)}</td>
                    <td>${i.duration_seconds !== null ? formatDuration(i.duration_seconds) : "-"}</td>
                    <td>${escapeHtml(i.reason || "-")}</td>
                    <td>${i.notification_sent ? '<i class="bi bi-check-circle text-success"></i>' : '<i class="bi bi-dash-circle text-muted"></i>'}</td>
                </tr>`).join("");
        }

        // Renders the app's recent health check history table.
        function renderHealthChecks(checks) {
            const tbody = document.getElementById("details-health-checks-body");
            if (!checks.length) {
                tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">No health checks recorded.</td></tr>`;
                return;
            }
            tbody.innerHTML = checks.map((c) => `
                <tr>
                    <td>${formatDateTime(c.checked_at)}</td>
                    <td>${statusBadge(c.status)}</td>
                    <td>${c.http_status_code ?? "-"}</td>
                    <td>${c.response_time ? Math.round(c.response_time) + " ms" : "-"}</td>
                    <td>${c.attempt_number}</td>
                    <td class="text-truncate" style="max-width:250px" title="${escapeHtml(c.error_message || "")}">${escapeHtml(c.error_message || "-")}</td>
                </tr>`).join("");
        }

        // Sends the user to the applications page with this app's edit modal pre-opened.
        window.__editFromDetails = () => {
            sessionStorage.setItem("amns_edit_redirect", "1");
            window.location.href = `applications.html?edit=${id}`;
        };
        // Triggers an immediate health check from the details page "Run Check" button.
        window.__runCheckFromDetails = async (appId) => {
            try {
                await api.post(`/applications/${appId}/check`);
                showToast("Health check completed.");
                await load();
            } catch (err) {
                showError(err);
            }
        };
    }

    // Formats a duration in seconds as an "Xh Ym Zs" string.
    function formatDuration(seconds) {
        if (!seconds && seconds !== 0) return "-";
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return `${h}h ${m}m ${s}s`;
    }
})();
