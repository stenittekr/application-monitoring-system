/** Databases page: the DATABASE-type checks, split out from Applications because
 *  a connection string is not a URL and reads as noise in a list of web apps. */
(function () {
    initLayout("databases");

    // Splits a DSN into readable parts. The password is always a ${ENV_VAR}
    // placeholder (validation enforces it), so nothing secret is shown here -
    // but it is still dropped rather than rendered, since it is not useful.
    function describe(dsn) {
        const match = /^([^:]+):\/\/([^:@/]+)(?::[^@]*)?@([^/?]+)(?:\/([^?]*))?/.exec(dsn || "");
        if (!match) return { backend: "-", user: "-", host: dsn || "-", database: "-" };
        return {
            backend: match[1].split("+")[0],
            user: decodeURIComponent(match[2]),
            host: match[3],
            database: match[4] || "-",
        };
    }

    // ONLINE is unremarkable; anything else on a database we depend on is the
    // whole point of this column, so it is the state that gets the colour.
    function dbStateBadge(state) {
        const ok = state === "ONLINE";
        const cls = state === "NOT FOUND" ? "secondary" : (ok ? "success" : "danger");
        return `<span class="badge bg-${cls}-subtle text-${cls}-emphasis border border-${cls}-subtle">${escapeHtml(state || "?")}</span>`;
    }

    function trackedCell(row) {
        const tracked = row.tracked_databases || [];
        const total = (row.discovered_databases || []).length;
        if (!tracked.length) {
            return `<span class="text-muted small fst-italic">Not collected</span>`;
        }
        const list = tracked.map((d) => `
            <div class="d-flex align-items-center gap-2 mb-1">
                <code class="small">${escapeHtml(d.name)}</code>${dbStateBadge(d.state)}
            </div>`).join("");
        return `${list}
            <button class="btn btn-sm btn-link p-0 small" data-all-for="${row.id}">
                view all ${total} on this instance
            </button>`;
    }

    function statusBadge(status) {
        const cls = { UP: "success", DEGRADED: "warning", DOWN: "danger" }[status] || "secondary";
        return `<span class="badge bg-${cls}-subtle text-${cls}-emphasis border border-${cls}-subtle">${escapeHtml(status || "UNKNOWN")}</span>`;
    }

    async function load() {
        loadLinks();
        const body = document.getElementById("db-table-body");
        try {
            const rows = (await api.get("/applications")).filter((a) => a.health_check_type === "DATABASE");
            if (!rows.length) {
                body.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">
                    No databases monitored yet. Add one from Applications with check type "Database".</td></tr>`;
                return;
            }
            // The application row carries no response time; it lives on the most
            // recent health check, same as the dashboard reads it.
            const lastChecks = await Promise.all(rows.map((row) =>
                api.get(`/applications/${row.id}/health-checks?limit=1`).catch(() => [])
            ));

            body.innerHTML = rows.map((row, idx) => {
                const d = describe(row.url);
                return `
                    <tr>
                        <td>${escapeHtml(row.name)}</td>
                        <td>${escapeHtml(d.host)}<div class="small text-muted">${escapeHtml(d.backend)}</div></td>
                        <td class="small text-muted">${escapeHtml(d.user)}</td>
                        <td>${statusBadge(row.current_status)}</td>
                        <td>${trackedCell(row)}</td>
                        <td>${lastChecks[idx][0] ? `${Math.round(lastChecks[idx][0].response_time)} ms` : "-"}</td>
                        <td class="small">${row.last_checked_at ? new Date(row.last_checked_at).toLocaleString() : "-"}</td>
                    </tr>`;
            }).join("");
            // One handler for the whole table rather than per row.
            document.getElementById("db-table-body").onclick = (event) => {
                const btn = event.target.closest("button[data-all-for]");
                if (!btn) return;
                const row = rows.find((r) => r.id === Number(btn.dataset.allFor));
                if (row) openInstanceList(row);
            };
        } catch (err) {
            showError(err);
        }
    }

    // Every observed program-to-database connection across the whole estate.
    //
    // The question this answers is "which database does that application use",
    // asked across 75 servers rather than one at a time. Each agent reports
    // what its own machine's socket table shows, so this is a map of what is
    // actually happening rather than what a configuration file claims.
    //
    // Built from /servers, which already carries the links - the alternative
    // was an endpoint that fans out over every server to assemble the same rows.
    async function loadLinks() {
        const body = document.getElementById("db-links-body");
        if (!body) return;
        try {
            const [servers, applications] = await Promise.all([
                api.get("/servers"), api.get("/applications"),
            ]);

            const rows = [];
            servers.forEach((server) => {
                // A listening port identifies the program; that is what lets a
                // connection be attributed to a registered application rather
                // than just to "python.exe".
                const listeners = {};
                (server.discovered_ports || []).forEach((port) => {
                    if (port.pid && port.protocol === "TCP" && listeners[port.pid] === undefined) {
                        listeners[port.pid] = port.port;
                    }
                });
                (server.database_links || []).forEach((link) => {
                    const port = listeners[link.pid];
                    const app = applications.find((a) => a.hosted_on_server_id === server.id
                        && (a.port === port || (port && (a.url || "").includes(`:${port}`))));
                    rows.push({ server, link, port, app });
                });
            });

            if (!rows.length) {
                body.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">
                    Nothing observed yet. Agents on v0.12.0 and later watch for database
                    connections; older agents report none.</td></tr>`;
                return;
            }

            rows.sort((a, b) => (a.link.remote_host + a.link.remote_port)
                .localeCompare(b.link.remote_host + b.link.remote_port));

            body.innerHTML = rows.map(({ server, link, port, app }) => `<tr>
                <td><code>${escapeHtml(link.remote_host)}:${link.remote_port}</code></td>
                <td class="small">${escapeHtml(link.engine)}</td>
                <td class="small">${escapeHtml(server.hostname)}${port ? ` <span class="text-muted">:${port}</span>` : ""}</td>
                <td class="small"><code>${escapeHtml(link.process_name || "?")}</code>
                    <span class="text-muted">pid ${link.pid}</span></td>
                <td class="small">${app ? escapeHtml(app.name)
                    : '<span class="text-muted">not registered</span>'}</td>
                <td class="small">${link.open_now
                    ? '<span class="text-success">connected now</span>'
                    : `${Math.round((link.seconds_since_seen || 0) / 60)} min ago`}</td>
            </tr>`).join("");
        } catch (err) {
            body.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">
                Could not load the connection map.</td></tr>`;
        }
    }

    function openInstanceList(row) {
        const all = row.discovered_databases || [];
        document.getElementById("db-list-title").textContent =
            `${all.length} databases on ${describe(row.url).host}`;
        const filter = document.getElementById("db-list-filter");

        function render() {
            const needle = filter.value.trim().toLowerCase();
            const shown = needle ? all.filter((d) => d.name.toLowerCase().includes(needle)) : all;
            document.getElementById("db-list-body").innerHTML = shown.length
                ? shown.map((d) => `
                    <tr>
                        <td><code class="small">${escapeHtml(d.name)}</code></td>
                        <td>${dbStateBadge(d.state)}</td>
                        <td class="small text-muted">${escapeHtml(d.recovery_model || "-")}</td>
                    </tr>`).join("")
                : `<tr><td colspan="3" class="text-muted text-center py-3">No databases match that filter.</td></tr>`;
        }
        filter.oninput = render;
        filter.value = "";
        render();
        new bootstrap.Modal(document.getElementById("db-list-modal")).show();
    }

    document.getElementById("db-refresh").addEventListener("click", load);
    load();
    setInterval(load, 15000); // ponytail: fixed poll, matches the other list pages
})();
