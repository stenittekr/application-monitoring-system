/** Powers both applications.html (list + CRUD) and application-details.html (detail view). */
(function () {
    // Reduces a DATABASE connection string to just host/database for display -
    // the full DSN is long, and its user/${ENV_VAR} part is noise on a list screen.
    function dsnLabel(dsn) {
        const m = /@([^/?]+)[/]?([^?]*)/.exec(dsn || "");
        return m ? (m[2] ? `${m[1]}/${m[2]}` : m[1]) : (dsn || "-");
    }

    // Certificates expire quietly and take a site down completely when they do,
    // so the warning belongs where the application is listed, not on a sub-page.
    function certCell(app) {
        const days = app.cert_days_remaining;
        if (days === null || days === undefined) return `<span class="text-muted small">-</span>`;
        if (days < 0) return `<span class="badge bg-danger">Expired ${-days}d ago</span>`;
        if (days <= 14) return `<span class="badge bg-danger">${days}d left</span>`;
        if (days <= 30) return `<span class="badge bg-warning text-dark">${days}d left</span>`;
        return `<span class="text-muted small">${days}d</span>`;
    }

    // Returns the display string for what an app's health check hits (host:port, DSN or URL).
    function targetLabel(app) {
        if (app.health_check_type === "TCP") return `${app.server}:${app.port}`;
        if (app.health_check_type === "DATABASE") return dsnLabel(app.url);
        return app.url || "-";
    }

    const MATURITY_LABELS = {
        DISCOVERED: "Discovered", INFORMATION_REQUIRED: "Information Required", PROFILE_DRAFT: "Profile Draft",
        MONITORED: "Monitored", MAINTENANCE: "Maintenance", RETIRED: "Retired",
    };
    const MATURITY_BADGE_CLASS = {
        DISCOVERED: "bg-secondary-subtle text-secondary-emphasis border",
        INFORMATION_REQUIRED: "bg-warning-subtle text-warning-emphasis border",
        PROFILE_DRAFT: "bg-info-subtle text-info-emphasis border",
        MONITORED: "bg-success-subtle text-success-emphasis border",
        MAINTENANCE: "bg-info-subtle text-info-emphasis border",
        RETIRED: "bg-light text-muted border",
    };
    function maturityBadge(status) {
        const cls = MATURITY_BADGE_CLASS[status] || MATURITY_BADGE_CLASS.DISCOVERED;
        return `<span class="badge ${cls}">${MATURITY_LABELS[status] || status}</span>`;
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
        const isAdmin = user.role === "ADMIN" || user.role === "IT_MANAGER";
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
        setInterval(load, 5000); // ponytail: fixed 5s poll, add a setting if that ever needs tuning

        // ---- Workflow step editor -------------------------------------------
        // Rendered as rows rather than raw JSON: the shape is small and fixed,
        // and asking someone to hand-write JSON in a textarea is how
        // configuration errors get made.
        function workflowRow(step) {
            step = step || {};
            const formText = Object.entries(step.form || {})
                .map(function (e) { return e[0] + "=" + e[1]; }).join("\n");
            const row = document.createElement("div");
            row.className = "border rounded p-2 workflow-step";
            row.innerHTML = [
                '<div class="row g-2">',
                '  <div class="col-md-3"><label class="form-label small mb-1">Step name</label>',
                '    <input class="form-control form-control-sm wf-name" placeholder="Sign in"></div>',
                '  <div class="col-md-2"><label class="form-label small mb-1">Method</label>',
                '    <select class="form-select form-select-sm wf-method"><option>GET</option><option>POST</option></select></div>',
                '  <div class="col-md-3"><label class="form-label small mb-1">Path</label>',
                '    <input class="form-control form-control-sm wf-path" placeholder="/login"></div>',
                '  <div class="col-md-2"><label class="form-label small mb-1">Expect status</label>',
                '    <input type="number" class="form-control form-control-sm wf-status"></div>',
                '  <div class="col-md-2 d-flex align-items-end">',
                '    <button type="button" class="btn btn-sm btn-outline-danger w-100 wf-remove">Remove</button></div>',
                '  <div class="col-md-4"><label class="form-label small mb-1">Page must contain</label>',
                '    <input class="form-control form-control-sm wf-contains" placeholder="Dashboard"></div>',
                '  <div class="col-md-4"><label class="form-label small mb-1">Page must NOT contain</label>',
                '    <input class="form-control form-control-sm wf-absent" placeholder="Invalid username"></div>',
                '  <div class="col-md-4"><label class="form-label small mb-1">Form fields (one per line, name=value)</label>',
                '    <textarea class="form-control form-control-sm wf-form" rows="2"></textarea></div>',
                '  <div class="col-12"><div class="form-check">',
                '    <input class="form-check-input wf-login" type="checkbox">',
                '    <label class="form-check-label small">Login step &mdash; runs only when the session has expired</label>',
                '  </div></div>',
                '</div>',
            ].join("");

            // Values are assigned rather than interpolated, so a quote or an
            // angle bracket in a step cannot break out of the markup.
            row.querySelector(".wf-name").value = step.name || "";
            row.querySelector(".wf-method").value = step.method || "GET";
            row.querySelector(".wf-path").value = step.path || "/";
            row.querySelector(".wf-status").value = step.expect_status == null ? 200 : step.expect_status;
            row.querySelector(".wf-contains").value = step.expect_contains || "";
            row.querySelector(".wf-absent").value = step.expect_absent || "";
            row.querySelector(".wf-form").value = formText;
            row.querySelector(".wf-login").checked = !!step.login;
            row.querySelector(".wf-remove").onclick = function () { row.remove(); };
            return row;
        }

        function renderWorkflow(steps) {
            const host = document.getElementById("app-workflow-steps");
            host.innerHTML = "";
            const list = (steps && steps.length) ? steps : [{ path: "/" }];
            list.forEach(function (step) { host.appendChild(workflowRow(step)); });
        }

        function collectWorkflow() {
            const rows = document.querySelectorAll("#app-workflow-steps .workflow-step");
            return Array.prototype.map.call(rows, function (row) {
                const form = {};
                row.querySelector(".wf-form").value.split("\n").forEach(function (line) {
                    const idx = line.indexOf("=");
                    if (idx > 0) {
                        const key = line.slice(0, idx).trim();
                        if (key) form[key] = line.slice(idx + 1).trim();
                    }
                });
                const step = {
                    name: row.querySelector(".wf-name").value.trim(),
                    method: row.querySelector(".wf-method").value,
                    path: row.querySelector(".wf-path").value.trim() || "/",
                    expect_status: Number(row.querySelector(".wf-status").value) || 200,
                    login: row.querySelector(".wf-login").checked,
                };
                const contains = row.querySelector(".wf-contains").value.trim();
                const absent = row.querySelector(".wf-absent").value.trim();
                if (contains) step.expect_contains = contains;
                if (absent) step.expect_absent = absent;
                if (Object.keys(form).length) step.form = form;
                return step;
            });
        }

        document.getElementById("app-workflow-add").addEventListener("click", function () {
            document.getElementById("app-workflow-steps").appendChild(workflowRow({ path: "/" }));
        });

        // Shows the URL/DSN field for HTTP(S)/DATABASE checks, or server+port for TCP.
        function toggleCheckTypeFields() {
            const type = document.getElementById("app-health-check-type").value;
            const isTcp = type === "TCP";
            const isDb = type === "DATABASE";
            const isWorkflow = type === "WORKFLOW";
            document.getElementById("app-workflow-group").classList.toggle("d-none", !isWorkflow);
            document.getElementById("app-url-label").textContent =
                isDb ? "Connection String" : (isWorkflow ? "Base URL" : "URL");
            const urlInput = document.getElementById("app-url");
            urlInput.placeholder = isDb
                ? "mysql+pymysql://user:${DB_PASSWORD}@host:3306/dbname"
                : "https://example.com";
            document.getElementById("app-url-group").classList.toggle("d-none", isTcp);
            document.getElementById("app-server-group").classList.toggle("d-none", !isTcp);
            document.getElementById("app-port-group").classList.toggle("d-none", !isTcp);
        }

        let allApps = [];

        // Fetches the applications list and re-renders the table.
        async function load() {
            try {
                allApps = (await api.get("/applications")).filter((a) => a.health_check_type !== "DATABASE");
                renderTable(allApps, isAdmin);
                maybeOpenFromEditParam(allApps);
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
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">No applications yet.</td></tr>`;
                return;
            }
            tbody.innerHTML = apps.map((app) => `
                <tr>
                    <td><a href="application-details.html?id=${app.id}">${escapeHtml(app.name)}</a></td>
                    <td>${escapeHtml(app.environment)}</td>
                    <td><span class="badge bg-light text-dark border me-1">${app.health_check_type}</span>${escapeHtml(targetLabel(app))}
                        <div class="small mt-1">TLS: ${certCell(app)}</div></td>
                    <td>${statusBadge(app.current_status)}${app.in_maintenance ? ' <span class="badge bg-info-subtle text-info-emphasis border">Maintenance</span>' : ""}</td>
                    <td>${maturityBadge(app.maturity_status)}</td>
                    <td>${app.monitoring_enabled ? '<span class="text-success">Enabled</span>' : '<span class="text-muted">Disabled</span>'}</td>
                    <td>${formatDateTime(app.last_checked_at)}</td>
                </tr>`).join("");
        }

    // Both selects list the same enrolled servers; loaded once and reused.
    let serverOptions = null;
    async function fillServerSelects(app) {
        if (serverOptions === null) {
            try {
                serverOptions = await api.get("/servers");
            } catch (err) {
                serverOptions = [];
            }
        }
        [["app-hosted-on", "Not recorded", app && app.hosted_on_server_id],
         ["app-network-witness", "None", app && app.network_witness_server_id]].forEach(([id, blank, selected]) => {
            const select = document.getElementById(id);
            if (!select) return;
            select.innerHTML = `<option value="">${blank}</option>` + serverOptions
                .map((s) => `<option value="${s.id}">${escapeHtml(s.hostname)}</option>`).join("");
            select.value = selected ? String(selected) : "";
        });
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
            renderWorkflow(app ? app.workflow_steps : null);
            document.getElementById("app-server").value = app ? (app.server || "") : "";
            document.getElementById("app-port").value = app ? (app.port || "") : "";
            toggleCheckTypeFields();
            const currentUser = getCurrentUser();
            document.getElementById("app-owner-name").value = app ? app.owner_name : currentUser.name;
            document.getElementById("app-owner-email").value = app ? app.owner_email : currentUser.email;
            document.getElementById("app-manager-name").value = app ? app.manager_name : currentUser.name;
            document.getElementById("app-manager-email").value = app ? app.manager_email : currentUser.email;
            document.getElementById("app-interval").value = app ? app.monitoring_interval : 60;
            document.getElementById("app-timeout").value = app ? app.timeout : 10;
            document.getElementById("app-retry-count").value = app ? app.retry_count : 3;
            document.getElementById("app-retry-delay").value = app ? app.retry_delay : 5;
            document.getElementById("app-expected-status").value = app ? app.expected_status_code : 200;
            fillServerSelects(app);
            document.getElementById("app-criticality").value = (app && app.criticality) || "";
            document.getElementById("app-support-hours").value = (app && app.support_hours) || "";
            document.getElementById("app-monitoring-enabled").checked = app ? app.monitoring_enabled : true;
            document.getElementById("app-verify-ssl").checked = app ? app.verify_ssl !== false : true;
            document.getElementById("app-maturity-status").value = app ? app.maturity_status : "MONITORED";
            document.getElementById("app-baseline-notes").value = app ? (app.baseline_notes || "") : "";
            populateDependsOn(app);
            modal.show();
        }

        // Fills the "Depends On" multi-select with every other application, checking off the current app's dependencies.
        function populateDependsOn(app) {
            const select = document.getElementById("app-depends-on");
            const dependsOn = app ? (app.depends_on || []) : [];
            select.innerHTML = allApps
                .filter((a) => !app || a.id !== app.id)
                .map((a) => `<option value="${a.id}" ${dependsOn.includes(a.id) ? "selected" : ""}>${escapeHtml(a.name)}</option>`)
                .join("");
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
                workflow_steps: healthCheckType === "WORKFLOW" ? collectWorkflow() : undefined,
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
                hosted_on_server_id: document.getElementById("app-hosted-on").value || null,
                network_witness_server_id: document.getElementById("app-network-witness").value || null,
                criticality: document.getElementById("app-criticality").value || null,
                support_hours: document.getElementById("app-support-hours").value.trim() || null,
                monitoring_enabled: document.getElementById("app-monitoring-enabled").checked,
                verify_ssl: document.getElementById("app-verify-ssl").checked,
                maturity_status: document.getElementById("app-maturity-status").value,
                baseline_notes: document.getElementById("app-baseline-notes").value.trim(),
                depends_on: Array.from(document.getElementById("app-depends-on").selectedOptions).map((o) => Number(o.value)),
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
                const [app, healthChecks, incidents, allApps] = await Promise.all([
                    api.get(`/applications/${id}`),
                    api.get(`/applications/${id}/health-checks?limit=100`),
                    api.get(`/applications/${id}/incidents`),
                    api.get("/applications"),
                ]);
                window.__allAppsById = Object.fromEntries(allApps.map((a) => [a.id, a.name]));
                renderHeader(app);
                renderStats(healthChecks, incidents);
                renderInfo(app);
                renderIncidents(incidents);
                renderHealthChecks(healthChecks);
            } catch (err) {
                showError(err);
            }
        }

        // Renders the page title, status badge, and (per role/ownership) the edit/run-check buttons.
        function renderHeader(app) {
            document.getElementById("details-name").textContent = app.name;
            document.getElementById("details-status").innerHTML = statusBadge(app.current_status);
            const user = getCurrentUser();
            const ownsApp = app.owner_email === user.email || app.manager_email === user.email;
            const canEdit = user.role === "ADMIN" || user.role === "IT_MANAGER" || (user.role === "APP_OWNER" && ownsApp);
            const canRunCheck = canEdit || user.role === "OPERATOR";

            const buttons = [];
            if (canEdit) buttons.push(`<button class="btn btn-outline-secondary" onclick="window.__editFromDetails()"><i class="bi bi-pencil"></i> Edit</button>`);
            if (canRunCheck) buttons.push(`<button class="btn btn-outline-secondary" onclick="window.__runCheckFromDetails(${app.id})"><i class="bi bi-play-circle"></i> Run Check</button>`);
            // Deactivate lives here rather than on the list. It is the one
            // irreversible action, and it should not sit a mis-click away from
            // the row above it.
            if (canEdit) buttons.push(`<button class="btn btn-outline-danger" onclick="window.__deactivateFromDetails(${app.id})"><i class="bi bi-trash"></i> Deactivate</button>`);
            document.getElementById("details-actions").innerHTML = buttons.join(" ");
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
            let targetRow;
            if (app.health_check_type === "TCP") {
                targetRow = `<tr><th>Server / Port</th><td>${escapeHtml(app.server)}:${app.port}</td></tr>`;
            } else if (app.health_check_type === "DATABASE") {
                // Plain text, not a link - a DSN is not navigable.
                targetRow = `<tr><th>Database</th><td><code>${escapeHtml(app.url || "-")}</code></td></tr>`;
            } else {
                targetRow = `<tr><th>URL</th><td><a href="${app.url}" target="_blank" rel="noopener">${escapeHtml(app.url)}</a></td></tr>`;
            }
            const dependsOnNames = (app.depends_on || [])
                .map((id) => window.__allAppsById && window.__allAppsById[id])
                .filter(Boolean);
            document.getElementById("details-info-table").innerHTML = `
                <tr><th>Health Check Type</th><td>${app.health_check_type}</td></tr>
                ${targetRow}
                <tr><th>Environment</th><td>${escapeHtml(app.environment)}</td></tr>
                <tr><th>Description</th><td>${escapeHtml(app.description || "-")}</td></tr>
                <tr><th>Maturity Status</th><td>${maturityBadge(app.maturity_status)}</td></tr>
                <tr><th>Depends On</th><td>${dependsOnNames.length ? dependsOnNames.map(escapeHtml).join(", ") : "-"}</td></tr>
                <tr><th>Baseline Notes</th><td>${escapeHtml(app.baseline_notes || "-")}</td></tr>
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
        window.__deactivateFromDetails = async (appId) => {
            const ok = await confirmAction("Deactivate this application? It will stop being monitored.");
            if (!ok) return;
            try {
                await api.del(`/applications/${appId}`);
                showToast("Application deactivated.");
                window.location.href = "applications.html";
            } catch (err) {
                showError(err);
            }
        };

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
