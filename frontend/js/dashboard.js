(function () {
    initLayout("dashboard");
    renderWelcomeBanner();
    load();
    document.getElementById("refresh-btn").addEventListener("click", load);
    setInterval(load, 5000); // ponytail: fixed 5s poll, add a setting if that ever needs tuning

    // §12.1: filter the overview by the things people actually group work by.
    // Options are built from the data rather than hard-coded, so a filter can
    // never offer a value nothing has - an empty result from a dropdown you
    // were offered reads as a bug.
    // hosted_on_server_id is a foreign key, not a display value - resolve it
    // to the server's own hostname via window.__servers (populated in load(),
    // before this is ever called) so the dropdown shows names, not raw ids.
    // An app with no host set (most apps, unless someone has explicitly linked
    // it via the edit form - see applications.js) resolves to null and is
    // dropped from the options list by populateFilters' own filter(Boolean),
    // same as any other blank field - it just never matches a chosen server.
    function serverNameOf(app) {
        const server = (window.__servers || []).find((s) => s.id === app.hosted_on_server_id);
        return server ? server.hostname : null;
    }

    const FILTERS = [
        ["filter-status", "All statuses", (a) => a.current_status],
        ["filter-environment", "All environments", (a) => a.environment],
        ["filter-server", "All servers", serverNameOf],
        ["filter-criticality", "All criticalities", (a) => a.criticality || "Normal"],
        ["filter-site", "All sites", (a) => a.site],
        ["filter-owner", "All owners", (a) => a.owner_email],
        ["filter-tag", "All tags", (a) => (a.tags || []).join(", ")],
    ];

    function selected(id) {
        const el = document.getElementById(id);
        return el && el.value ? el.value : "";
    }

    function populateFilters(apps) {
        FILTERS.forEach(([id, blank, valueOf]) => {
            const select = document.getElementById(id);
            if (!select) return;
            const keep = select.value;
            const values = [...new Set(apps.map(valueOf).filter(Boolean))].sort();
            select.innerHTML = `<option value="">${blank}</option>`
                + values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("");
            select.value = values.includes(keep) ? keep : "";
            // A filter with one possible value filters nothing.
            select.classList.toggle("d-none", values.length < 2);
        });
    }

    function applyFilters(apps) {
        return apps.filter((app) =>
            FILTERS.every(([id, , valueOf]) => {
                const want = selected(id);
                return !want || valueOf(app) === want;
            }));
    }

    document.getElementById("dashboard-filters").addEventListener("change", load);
    document.getElementById("filter-clear").addEventListener("click", () => {
        FILTERS.forEach(([id]) => {
            const el = document.getElementById(id);
            if (el) el.value = "";
        });
        load();
    });

    // Fetches applications and open incidents, then refreshes the stat cards and table.
    async function load() {
        try {
            const [allApps, incidents, servers] = await Promise.all([
                api.get("/applications"), api.get("/incidents?status=OPEN"),
                // Only ADMIN..AUDITOR may list servers; an APP_OWNER still gets
                // a working dashboard, just without the host groupings.
                api.get("/servers").catch(() => []),
            ]);
            window.__servers = servers;
            window.__apps = allApps;
            // Databases live on their own page - their connection strings are not
            // URLs and cannot be opened, so they do not belong in this table.
            const monitored = allApps.filter((a) => a.health_check_type !== "DATABASE");
            populateFilters(monitored);
            const apps = applyFilters(monitored);

            // The stat cards count what is on screen. A total that disagrees
            // with the list under it is worse than no total.
            const hidden = monitored.length - apps.length;
            document.getElementById("filter-count").textContent =
                hidden ? `${apps.length} of ${monitored.length} shown` : "";
            document.getElementById("filter-clear").classList.toggle("d-none", !hidden);

            const shownIds = new Set(apps.map((a) => a.id));
            const shownIncidents = incidents.filter(
                (i) => !i.application_id || shownIds.has(i.application_id));

            renderStats(apps, shownIncidents);
            renderAppTiles(apps);
            await renderTable(apps);
        } catch (err) {
            showError(err);
        }
    }

    const STEP_LABELS = {
        target: "Target", dns: "Name resolution", tcp: "Connection",
        http: "Response", content: "Content",
    };
    const STEP_STYLE = {
        ok: ["bi-check-circle-fill text-success", ""],
        failed: ["bi-x-circle-fill text-danger", "fw-semibold"],
        skipped: ["bi-dash-circle text-muted", "text-muted"],
    };

    // The whole point of the panel: not "DOWN" but which link in the chain
    // broke, because each one is a different fix and a different person.
    async function showDiagnosis(appId, appName) {
        const body = document.getElementById("diagnose-body");
        const app = (window.__apps || []).find((a) => a.id === appId) || {};
        document.getElementById("diagnose-title").textContent = `Diagnosis - ${appName}`;
        body.innerHTML = '<div class="text-muted small">Probing&hellip;</div>';
        new bootstrap.Modal(document.getElementById("diagnose-modal")).show();

        let data;
        try {
            data = await api.get(`/applications/${appId}/diagnose`);
        } catch (err) {
            body.innerHTML = `<div class="alert alert-warning small mb-0">Could not run the
                diagnosis. ${escapeHtml(err.message || "")}</div>`;
            return;
        }

        const steps = (data.steps || []).map((step) => {
            const [icon, cls] = STEP_STYLE[step.state] || STEP_STYLE.skipped;
            return `<div class="d-flex gap-2 py-2 border-bottom">
                <i class="bi ${icon}"></i>
                <div>
                    <div class="small ${cls}">${escapeHtml(STEP_LABELS[step.step] || step.step)}</div>
                    <div class="small text-muted">${escapeHtml(step.detail)}</div>
                </div>
            </div>`;
        }).join("");

        const host = data.host || {};
        let hostHtml;
        if (!host.known) {
            hostHtml = `<div class="small text-muted">${escapeHtml(host.detail || "")}</div>`;
        } else {
            const process = host.process
                ? `<code class="small">${escapeHtml(host.process.script || host.process.name || "?")}</code>
                   <span class="text-muted small">pid ${host.process.pid}`
                   + (host.process.memory_mb ? ` &middot; ${host.process.memory_mb} MB` : "") + `</span>`
                : `<span class="text-muted small">${escapeHtml(host.process_detail || "not running")}</span>`;
            const databases = (host.databases || []).length
                ? host.databases.map((link) => `<div><code class="small">${escapeHtml(link.engine)}
                    ${escapeHtml(link.remote_host)}:${link.remote_port}</code>
                    <span class="text-muted small">${link.open_now ? "connected now"
                        : `seen ${Math.round((link.seconds_since_seen || 0) / 60)} min ago`}</span></div>`).join("")
                : '<span class="text-muted small">none observed</span>';
            hostHtml = `<table class="table table-sm mb-0">
                <tr><th style="width:11rem">Machine</th><td class="small">${escapeHtml(host.hostname)}
                    &middot; ${statusBadge(host.server_status)}
                    <span class="text-muted">agent ${escapeHtml(host.agent_version || "?")}</span></td></tr>
                <tr><th>Last heartbeat</th><td class="small">${formatDateTime(host.last_heartbeat_at)}</td></tr>
                <tr><th>Process</th><td>${process}</td></tr>
                <tr><th>Database</th><td>${databases}</td></tr>
            </table>`;
        }

        // The runbook, next to the fault. Whoever opens this at 2am should not
        // also have to find out how the thing is started - and the platform
        // holds the note without ever running it. Deliberately text: a stored
        // command the platform could execute is a deploy button, and this
        // platform is not where one belongs.
        const runbook = (app.baseline_notes || "").trim()
            ? `<pre class="small bg-light border rounded p-2 mb-0" style="white-space:pre-wrap">${escapeHtml(app.baseline_notes)}</pre>`
            : `<div class="small text-muted">Nothing recorded. Put the folder, venv and run
                command in <em>Baseline notes</em> when editing this application, and they will
                show here whenever it breaks.</div>`;

        body.innerHTML = `
            <h6 class="small text-uppercase text-muted">What a request finds</h6>
            ${steps || '<div class="small text-muted">Nothing to report.</div>'}
            <h6 class="small text-uppercase text-muted mt-4">The machine underneath</h6>
            ${hostHtml}
            <h6 class="small text-uppercase text-muted mt-4">How to start this</h6>
            ${runbook}
            <p class="small text-muted mt-3 mb-0">Probed just now, on demand - these are live
               results, not the last cycle's. Nothing here is executed by the platform.</p>`;
    }

    document.getElementById("app-tiles").addEventListener("click", (event) => {
        const button = event.target.closest("[data-diagnose]");
        if (!button) return;
        showDiagnosis(Number(button.dataset.diagnose),
                      button.querySelector(".fw-semibold").textContent);
    });

    // Shows a personalized welcome message with the logged-in user's name.
    function renderWelcomeBanner() {
        const user = getCurrentUser();
        document.querySelector("#welcome-banner .card-body").innerHTML = `
            <h4 class="fw-bold mb-1">Welcome back, ${escapeHtml(user.name)}</h4>
            <div class="text-muted">Monitor application availability, incidents, and health checks from a single screen.</div>`;
    }

    // Renders the summary stat cards (totals by status, active incidents) at the top of the dashboard.
    function renderStats(apps, activeIncidents) {
        const counts = { UP: 0, DOWN: 0, DEGRADED: 0, UNKNOWN: 0, DISABLED: 0 };
        apps.forEach((a) => { counts[a.current_status] = (counts[a.current_status] || 0) + 1; });

        // Every figure links to the list it counts. A stat that raises a question
        // should be one click from its answer - "2 active incidents" is not much
        // use without which two, and why.
        const cards = [
            { label: "Total Applications", value: apps.length, icon: "bi-hdd-network", color: "primary",
              href: "applications.html" },
            { label: "Up", value: counts.UP, icon: "bi-check-circle", color: "success",
              href: "applications.html" },
            { label: "Down", value: counts.DOWN, icon: "bi-x-circle", color: "danger",
              href: "applications.html" },
            { label: "Active Incidents", value: activeIncidents.length, icon: "bi-fire", color: "danger",
              href: "incidents.html?status=OPEN",
              // The dashboard already has the reasons; showing them here saves a
              // trip for the common case of "what is on fire right now?".
              detail: activeIncidents.slice(0, 3).map((i) => i.reason || i.error_message || "Reason not recorded") },
        ];

        document.getElementById("stat-cards").innerHTML = cards.map((c) => `
            <div class="col-6 col-md-4 col-xl-3">
                <a class="card border-0 shadow-sm stat-card h-100 text-decoration-none text-reset"
                   href="${c.href}" title="${escapeHtml(c.label)} - open the full list">
                    <div class="card-body d-flex justify-content-between align-items-start">
                        <!-- min-width:0 is what makes text-truncate work at all here:
                             a flex child defaults to min-width:auto and refuses to
                             shrink below its content, so long reasons spill out. -->
                        <div class="me-2 flex-grow-1" style="min-width:0">
                            <div class="text-muted small mb-2">${c.label}</div>
                            <div class="stat-value text-${c.color}">${c.value}</div>
                            ${(c.detail || []).length ? `<div class="small text-muted mt-2 lh-sm">
                                ${c.detail.map((d) => `<div class="stat-detail" title="${escapeHtml(d)}">${escapeHtml(d)}</div>`).join("")}
                                ${c.value > c.detail.length ? `<div class="fst-italic">+${c.value - c.detail.length} more</div>` : ""}
                            </div>` : ""}
                        </div>
                        <span class="stat-icon-badge text-${c.color} flex-shrink-0"><i class="bi ${c.icon}"></i></span>
                    </div>
                </a>
            </div>`).join("");
    }

    // Renders one launcher tile per application: status dot, name, and an Open button linking to its URL.
    // Grouped by the machine each application runs on, because that is how a
    // problem arrives: "the QA box is being rebooted", "the live server is
    // slow". A flat grid of tiles could not answer which applications that
    // affects, and repeated what the table below already said.
    function renderAppTiles(apps) {
        const host = document.getElementById("app-tiles");

        // Grouping by machine needs the machine list, and APP_OWNER is not
        // allowed to see it - so the headings came out as "Unknown server",
        // which is worse than no grouping. The table below shows everything
        // either way.
        if (!(window.__servers || []).length) {
            host.innerHTML = "";
            return;
        }
        const groups = new Map();
        apps.forEach((app) => {
            const key = app.hosted_on_server_id || 0;
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(app);
        });

        const serverName = (id) => {
            const server = (window.__servers || []).find((s) => s.id === id);
            return server ? server.hostname : null;
        };

        // Only applications on a machine we monitor. The rest are externally
        // hosted - there is no host to group them under and nothing useful to
        // say about it - so they stay in the table below rather than forming a
        // group whose heading is an apology.
        const keys = [...groups.keys()].filter((key) => key !== 0)
            .sort((a, b) => String(serverName(a)).localeCompare(String(serverName(b))));

        host.innerHTML = keys.map((key) => {
            const rows = groups.get(key);
            const server = (window.__servers || []).find((s) => s.id === key);
            const heading = key === 0
                ? '<span class="text-muted">Not linked to a server</span>'
                : `<i class="bi bi-hdd-rack me-1"></i>${escapeHtml(server ? server.hostname : "Unknown server")}`;
            const hostState = server && server.current_status !== "UP"
                ? ` <span class="badge bg-warning text-dark">host ${escapeHtml(server.current_status)}</span>`
                : "";
            return `<div class="col-12">
                <div class="card border-0 shadow-sm">
                    <div class="card-header bg-white fw-semibold small">${heading}${hostState}</div>
                    <div class="list-group list-group-flush">
                        ${rows.map((app) => `
                            <button class="list-group-item list-group-item-action d-flex align-items-center gap-3"
                                    data-diagnose="${app.id}">
                                <i class="bi ${app.icon || "bi-hdd-network"} text-primary"></i>
                                <span class="fw-semibold">${escapeHtml(app.name)}</span>
                                ${statusBadge(app.current_status)}
                                <span class="small text-muted text-truncate">${escapeHtml(app.url || "")}</span>
                                <span class="ms-auto small text-primary">Diagnose</span>
                            </button>`).join("")}
                    </div>
                </div>
            </div>`;
        }).join("");
    }

    // Renders the applications table, including each app's most recent response time.
    async function renderTable(apps) {
        const tbody = document.getElementById("apps-table-body");
        if (!apps.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">No applications yet.</td></tr>`;
            return;
        }

        const lastChecks = await Promise.all(apps.map((a) =>
            api.get(`/applications/${a.id}/health-checks?limit=1`).catch(() => [])
        ));

        tbody.innerHTML = apps.map((app, idx) => {
            const responseTime = lastChecks[idx][0] ? `${Math.round(lastChecks[idx][0].response_time)} ms` : "-";
            const target = app.server ? `${app.server}:${app.port}` : "-";
            const urlCell = app.url
                ? `<a href="${escapeHtml(app.url)}" target="_blank" rel="noopener">${escapeHtml(app.url)}</a>`
                : escapeHtml(target);
            return `
                <tr>
                    <td>${escapeHtml(app.name)}</td>
                    <td>${urlCell}</td>
                    <td>${escapeHtml(app.environment)}</td>
                    <td>${statusBadge(app.current_status)}${app.in_maintenance ? ' <span class="badge bg-info-subtle text-info-emphasis border">Maintenance</span>' : ""}</td>
                    <td>${responseTime}</td>
                    <td>${formatDateTime(app.last_checked_at)}</td>
                </tr>`;
        }).join("");
    }
})();
