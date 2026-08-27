(function () {
    // Renders the capacity a percentage refers to, e.g. "of 15.8 GB". Older
    // agents do not report these, so an absent value shows nothing at all
    // rather than a misleading "of 0".
    function capacity(value, label) {
        return value ? `<div class="small text-muted">${label(value)}</div>` : "";
    }

    // Some machines are monitoring infrastructure, not business systems. The
    // laptop running the platform raised most of last week's incidents; those
    // are real and worth recording, and of no use to a manager. Shown on the
    // row rather than hidden in a modal, because who gets woken by a server is
    // the kind of thing that should be obvious at a glance.
    function alertScopeCell(server) {
        const ownerOnly = !!server.owner_only_alerts;
        const label = ownerOnly ? "Owner only" : "Full list";
        const cls = ownerOnly ? "secondary" : "primary";
        return `<button class="btn btn-sm btn-outline-${cls} alert-scope-toggle"
                    data-id="${server.id}" data-owner-only="${ownerOnly}"
                    title="${ownerOnly
                        ? "Alerts about this server go to its owner only. Click to copy the full distribution list."
                        : "Alerts about this server copy the full distribution list. Click to send to its owner only."}">
                    ${label}</button>`;
    }

    function ramLabel(totalMb) {
        return totalMb >= 1024 ? `of ${(totalMb / 1024).toFixed(1)} GB` : `of ${totalMb} MB`;
    }

    initLayout("servers");

    let servers = [];
    document.getElementById("refresh-btn").addEventListener("click", load);
    document.getElementById("servers-table-body").addEventListener("click", onTableClick);

    load();

    // Fetches the enrolled server list and renders the table.
    // Flipping who hears about a server is a two-word change, so it is done in
    // place rather than behind a form.
    document.addEventListener("click", async (event) => {
        const button = event.target.closest(".alert-scope-toggle");
        if (!button) return;
        const ownerOnly = button.dataset.ownerOnly !== "true";
        try {
            await api.put(`/servers/${button.dataset.id}/alert-scope`, { owner_only_alerts: ownerOnly });
            showToast(ownerOnly ? "Alerts about this server now go to its owner only."
                                : "Alerts about this server now copy the full list.");
            await load();
        } catch (err) {
            showError(err);
        }
    });

    async function load() {
        try {
            servers = await api.get("/servers");
            renderTable();
        } catch (err) {
            showError(err);
        }
    }

    function renderTable() {
        const tbody = document.getElementById("servers-table-body");
        if (!servers.length) {
            tbody.innerHTML = `<tr><td colspan="11" class="text-center text-muted py-4">
                No servers enrolled yet. Run the agent's <code>enroll</code> command to register one.</td></tr>`;
            return;
        }
        tbody.innerHTML = servers.map((s) => `
            <tr>
                <td>${escapeHtml(s.hostname)}</td>
                <td>${escapeHtml(s.ip_address || "-")}</td>
                <td>${escapeHtml([s.os_name, s.os_version].filter(Boolean).join(" ") || "-")}</td>
                <td>${statusBadge(s.current_status)}</td>
                <td>${formatPercent(s.cpu_percent, s.is_stale, (s.resource_flags || {}).cpu)}${capacity(s.cpu_cores, (n) => `${n} cores`)}</td>
                <td>${formatPercent(s.ram_percent, s.is_stale, (s.resource_flags || {}).ram)}${capacity(s.ram_total_mb, ramLabel)}</td>
                <td>${formatPercent(s.disk_percent, s.is_stale, (s.resource_flags || {}).disk)}${capacity(s.disk_total_gb, (n) => `of ${n} GB`)}</td>
                <td>${formatDateTime(s.last_heartbeat_at)}</td>
                <td>${formatDateTime(s.last_boot_at)}</td>
                <td>${alertScopeCell(s)}</td>
                <td>
                    <button class="btn btn-sm btn-outline-secondary" data-server-id="${s.id}">
                        ${s.discovered_services.length} services, ${s.discovered_ports.length} ports, ${(s.discovered_processes || []).length} processes
                    </button>
                    ${componentBadge(s)}
                </td>
            </tr>`).join("");
    }

    // Three different nothings, and the requirements are explicit that they must
    // not look alike: the agent could not collect it (Not available), the reading
    // is too old to trust (stale), or it is a live figure.
    // Monitored components are the point of the discovery data; a stopped one
    // should be visible on the row, not only inside the modal.
    function componentBadge(server) {
        const components = server.component_status || [];
        if (!components.length) return "";
        const bad = components.filter((c) => c.state !== "OK");
        return bad.length
            ? `<div class="small text-danger mt-1" title="${escapeHtml(bad.map((c) => c.name + " " + c.state).join(", "))}">
                   ${bad.length} of ${components.length} monitored not OK
               </div>`
            : `<div class="small text-success mt-1">${components.length} monitored OK</div>`;
    }

    function formatPercent(value, stale, flag) {
        if (value === null || value === undefined) {
            return `<span class="text-muted fst-italic small">Not available</span>`;
        }
        const text = `${Math.round(value)}%`;
        if (stale) {
            return `<span class="text-muted" title="No fresh reading - last known value">${text}</span>`;
        }
        // Colour comes from the same thresholds the alerting uses, so the screen
        // and the emails can never disagree. Not colour alone: the label spells
        // out the state for anyone who cannot rely on it (§16 accessibility).
        if (flag === "CRITICAL") {
            return `<span class="fw-semibold text-danger">${text}</span>
                    <div class="small text-danger">Critical</div>`;
        }
        if (flag === "WARNING") {
            return `<span class="fw-semibold" style="color:#8a5a00">${text}</span>
                    <div class="small" style="color:#8a5a00">Warning</div>`;
        }
        return text;
    }

    function onTableClick(event) {
        const btn = event.target.closest("button[data-server-id]");
        if (!btn) return;
        const server = servers.find((s) => s.id === Number(btn.dataset.serverId));
        if (server) openDiscoveryModal(server);
    }

    // Which components this server is expected to be running. Discovery lists
    // candidates; ticking one is the authorised decision to monitor it.
    function checkbox(kind, name, expected) {
        const checked = expected.some((e) => e.toLowerCase() === (name || "").toLowerCase());
        return `<input class="form-check-input expected-box" type="checkbox" data-kind="${kind}"
                       value="${escapeHtml(name || "")}" ${checked ? "checked" : ""}
                       aria-label="Monitor ${escapeHtml(name || "")}">`;
    }

    async function renderChanges(server) {
        const body = document.getElementById("discovery-changes-body");
        body.innerHTML = `<tr><td colspan="5" class="text-muted text-center py-3">Loading...</td></tr>`;
        try {
            const rows = await api.get(`/servers/${server.id}/changes`);
            const colour = { ADDED: "success", REMOVED: "danger", CHANGED: "warning" };
            body.innerHTML = rows.length
                ? rows.map((c) => `
                    <tr>
                        <td class="small">${new Date(c.detected_at).toLocaleString()}</td>
                        <td class="small text-muted">${escapeHtml(c.category)}</td>
                        <td><span class="badge bg-${colour[c.change_type] || "secondary"}-subtle
                                   text-${colour[c.change_type] || "secondary"}-emphasis">${escapeHtml(c.change_type)}</span></td>
                        <td>${escapeHtml(c.item_name)}</td>
                        <td class="small text-muted">${
                            c.change_type === "CHANGED"
                                ? `${escapeHtml(c.old_value || "-")} &rarr; ${escapeHtml(c.new_value || "-")}`
                                : escapeHtml(c.new_value || c.old_value || "-")}</td>
                    </tr>`).join("")
                : `<tr><td colspan="5" class="text-muted text-center py-3">
                       No changes detected yet. Services and installed software are compared on every heartbeat.
                   </td></tr>`;
        } catch (err) {
            body.innerHTML = `<tr><td colspan="5" class="text-muted text-center py-3">Could not load changes.</td></tr>`;
        }
    }

    function componentSummary(server) {
        const problems = (server.component_status || []).filter((c) => c.state !== "OK");
        if (!(server.component_status || []).length) {
            return "Nothing monitored on this server yet - tick a service or process below.";
        }
        return problems.length
            ? `${problems.length} of ${server.component_status.length} monitored component(s) not OK: `
              + problems.map((c) => `${c.name} ${c.state}`).join(", ")
            : `All ${server.component_status.length} monitored component(s) OK.`;
    }

    function openDiscoveryModal(server) {
        document.getElementById("discovery-modal-title").textContent = `Discovered on ${server.hostname}`;
        const expectedServices = server.expected_services || [];
        const expectedProcesses = server.expected_processes || [];

        document.getElementById("discovery-services-body").innerHTML = server.discovered_services.length
            ? server.discovered_services.map((svc) => `
                <tr>
                    <td>${checkbox("service", svc.name, expectedServices)}</td>
                    <td>${escapeHtml(svc.name)}</td>
                    <td>${escapeHtml(svc.display_name || "-")}</td>
                    <td>${svc.status === "running"
                        ? `<span class="text-success">running</span>`
                        : `<span class="text-danger">${escapeHtml(svc.status || "-")}</span>`}</td>
                </tr>`).join("")
            : `<tr><td colspan="4" class="text-muted text-center py-3">No services reported.</td></tr>`;
        document.getElementById("discovery-ports-body").innerHTML = server.discovered_ports.length
            ? server.discovered_ports.map((p) => `
                <tr><td>${p.port ?? "-"}</td><td>${escapeHtml(p.protocol || "-")}</td><td>${escapeHtml(p.process_name || "-")}</td></tr>`).join("")
            : `<tr><td colspan="3" class="text-muted text-center py-3">No ports reported.</td></tr>`;
        // Interpreters first, then everything else by memory - the script list is
        // what people open this tab for.
        const processes = (server.discovered_processes || []).slice().sort((a, b) =>
            (b.script ? 1 : 0) - (a.script ? 1 : 0) || (b.memory_mb || 0) - (a.memory_mb || 0));
        const scriptsOnly = document.getElementById("discovery-scripts-only");

        function renderProcesses() {
            const rows = scriptsOnly.checked ? processes.filter((p) => p.script) : processes;
            document.getElementById("discovery-processes-body").innerHTML = rows.length
                ? rows.map((p) => `
                    <tr>
                        <td>${checkbox("process", p.name, expectedProcesses)}</td>
                        <td>${escapeHtml(p.name || "-")}</td>
                        <td><code class="small">${escapeHtml(p.script || "-")}</code></td>
                        <td>${p.pid ?? "-"}</td>
                        <td class="small text-muted">${escapeHtml(p.user || "-")}</td>
                        <td class="text-end">${p.memory_mb ?? "-"} MB</td>
                    </tr>`).join("")
                : `<tr><td colspan="6" class="text-muted text-center py-3">${
                    processes.length
                        ? "No script processes reported."
                        : "No processes reported - agent v0.3.0+ required on this server."
                  }</td></tr>`;
        }
        scriptsOnly.onchange = renderProcesses;
        renderProcesses();

        const programs = server.discovered_programs || [];
        const programFilter = document.getElementById("discovery-programs-filter");

        function renderPrograms() {
            const needle = programFilter.value.trim().toLowerCase();
            const rows = needle
                ? programs.filter((p) => `${p.name} ${p.publisher}`.toLowerCase().includes(needle))
                : programs;
            document.getElementById("discovery-programs-body").innerHTML = rows.length
                ? rows.map((p) => `
                    <tr>
                        <td>${checkbox("process", p.name, expectedProcesses)}</td>
                        <td>${escapeHtml(p.name || "-")}</td>
                        <td class="small">${escapeHtml(p.version || "-")}</td>
                        <td class="small text-muted">${escapeHtml(p.publisher || "-")}</td>
                    </tr>`).join("")
                : `<tr><td colspan="3" class="text-muted text-center py-3">${
                    programs.length
                        ? "No programs match that filter."
                        : "No programs reported - agent v0.3.0+ required on this server."
                  }</td></tr>`;
        }
        programFilter.oninput = renderPrograms;
        programFilter.value = "";
        renderPrograms();

        document.getElementById("discovery-expected-summary").textContent = componentSummary(server);
        renderChanges(server);

        document.getElementById("discovery-save-expected").onclick = async (event) => {
            const button = event.currentTarget;
            const picked = (kind) => [...document.querySelectorAll(`.expected-box[data-kind="${kind}"]:checked`)]
                .map((box) => box.value);
            button.disabled = true;
            try {
                const updated = await api.put(`/servers/${server.id}/expected`, {
                    services: picked("service"), processes: picked("process"),
                });
                Object.assign(server, updated);
                document.getElementById("discovery-expected-summary").textContent = componentSummary(updated);
                await load();
            } catch (err) {
                showError(err);
            } finally {
                button.disabled = false;
            }
        };

        new bootstrap.Modal(document.getElementById("discovery-modal")).show();
    }
})();
