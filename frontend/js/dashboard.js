(function () {
    initLayout("dashboard");
    renderWelcomeBanner();
    load();
    document.getElementById("refresh-btn").addEventListener("click", load);
    setInterval(load, 5000); // ponytail: fixed 5s poll, add a setting if that ever needs tuning

    const user = getCurrentUser();
    if (user.role === "ADMIN" || user.role === "IT_MANAGER") {
        const modal = new bootstrap.Modal(document.getElementById("new-app-modal"));
        document.getElementById("new-app-btn").classList.remove("d-none");
        document.getElementById("new-app-btn").addEventListener("click", () => modal.show());
        // Creates a new application from the "New Application" modal form.
        document.getElementById("new-app-form").addEventListener("submit", async (event) => {
            event.preventDefault();
            try {
                await api.post("/applications", {
                    name: document.getElementById("new-app-name").value.trim(),
                    url: document.getElementById("new-app-url").value.trim(),
                    health_check_type: document.getElementById("new-app-url").value.trim().startsWith("https") ? "HTTPS" : "HTTP",
                    owner_name: user.name,
                    owner_email: user.email,
                    manager_name: user.name,
                    manager_email: user.email,
                });
                document.getElementById("new-app-form").reset();
                modal.hide();
                showToast("Application added.");
                await load();
            } catch (err) {
                showError(err);
            }
        });
    }

    // Fetches applications and open incidents, then refreshes the stat cards and table.
    async function load() {
        try {
            const [allApps, incidents] = await Promise.all([api.get("/applications"), api.get("/incidents?status=OPEN")]);
            // Databases live on their own page - their connection strings are not
            // URLs and cannot be opened, so they do not belong in this table.
            const apps = allApps.filter((a) => a.health_check_type !== "DATABASE");
            renderStats(apps, incidents);
            renderAppTiles(apps);
            await renderTable(apps);
        } catch (err) {
            showError(err);
        }
    }

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
    function renderAppTiles(apps) {
        document.getElementById("app-tiles").innerHTML = apps.map((app) => `
            <div class="col-6 col-md-4 col-xl-3">
                <div class="card border-0 shadow-sm app-tile h-100">
                    <div class="card-body d-flex align-items-center justify-content-between">
                        <div class="d-flex align-items-center gap-2">
                            <i class="bi ${app.icon || "bi-hdd-network"} fs-4 text-primary"></i>
                            <div>
                                <div class="fw-semibold">${escapeHtml(app.name)}</div>
                                ${statusBadge(app.current_status)}
                            </div>
                        </div>
                        ${app.url ? `<a class="btn btn-sm btn-outline-primary" href="${escapeHtml(app.url)}" target="_blank" rel="noopener">Open</a>` : ""}
                    </div>
                </div>
            </div>`).join("");
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
