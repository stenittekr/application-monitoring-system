(function () {
    // Renders the capacity a percentage refers to, e.g. "of 15.8 GB". Older
    // agents do not report these, so an absent value shows nothing at all
    // rather than a misleading "of 0".
    function capacity(value, label) {
        return value ? `<div class="small text-muted">${label(value)}</div>` : "";
    }

    // Who hears about each machine, chosen per machine and visible at a glance.
    // Two states were not enough: the laptop running the platform produces real
    // incidents that are nobody's business but its owner's, and some weeks not
    // even that.
    const ALERT_SCOPES = [
        ["ALL", "Everyone", "Owner plus the standing distribution list."],
        ["OWNER", "Owner only", "Its owner is emailed; the distribution list is not."],
        ["NONE", "No email", "Nothing is emailed. Incidents are still recorded and shown."],
    ];

    function alertScopeCell(server) {
        const current = server.alert_scope || "ALL";
        const tone = { ALL: "primary", OWNER: "secondary", NONE: "warning" }[current];
        const options = ALERT_SCOPES.map(([value, label]) =>
            `<option value="${value}"${value === current ? " selected" : ""}>${label}</option>`).join("");
        const help = (ALERT_SCOPES.find((o) => o[0] === current) || [])[2] || "";
        return `<select class="form-select form-select-sm alert-scope-select border-${tone}"
                    data-id="${server.id}" title="${help}" style="min-width:8.5rem">${options}</select>`;
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
    // Changed in place rather than behind a form: it is one choice, and the
    // person making it is looking at the machine it applies to.
    document.addEventListener("change", async (event) => {
        const select = event.target.closest(".alert-scope-select");
        if (!select) return;
        const scope = select.value;
        try {
            await api.put(`/servers/${select.dataset.id}/alert-scope`, { alert_scope: scope });
            showToast({
                ALL: "Alerts about this server now go to everyone.",
                OWNER: "Alerts about this server now go to its owner only.",
                NONE: "Alerts about this server will not be emailed. They are still recorded.",
            }[scope]);
            await load();
        } catch (err) {
            showError(err);
            await load();
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
    // Section 8 asks for per-core CPU, network errors and drops, hardware
    // readings and every volume - and is explicit that where a machine exposes
    // none of it the answer is "Not available", never a comfortable zero.
    function notAvailable(why) {
        return `<div class="text-muted small py-2">Not available &mdash; ${escapeHtml(why)}</div>`;
    }

    function renderHostHealth(server) {
        const box = document.getElementById("health-body");
        const bar = (label, percent) => {
            const tone = percent >= 90 ? "danger" : percent >= 75 ? "warning" : "success";
            return `<div class="d-flex align-items-center gap-2 mb-1">
                        <span class="small text-muted" style="width:5.5rem">${escapeHtml(label)}</span>
                        <div class="progress flex-grow-1" style="height:.6rem">
                            <div class="progress-bar bg-${tone}" style="width:${Math.min(100, percent)}%"></div>
                        </div>
                        <span class="small" style="width:3rem">${percent}%</span>
                    </div>`;
        };

        const cores = server.cpu_per_core || [];
        const coresHtml = cores.length
            ? cores.map((v, i) => bar(`Core ${i}`, Math.round(v))).join("")
            : notAvailable("this agent does not report per-core CPU (needs v0.7.0)");

        const volumes = server.disk_volumes || [];
        const volumesHtml = volumes.length
            ? volumes.map((v) => bar(`${v.mount} (${v.total_gb} GB)`, Math.round(v.used_percent))).join("")
            : notAvailable("this agent reports only the system drive (needs v0.7.0)");

        const nics = server.network_interfaces || [];
        const nicsHtml = nics.length
            ? `<table class="table table-sm mb-0"><thead><tr><th>Interface</th><th>State</th><th>Speed</th><th>Errors</th><th>Drops</th></tr></thead><tbody>`
              + nics.map((n) => `<tr>
                    <td>${escapeHtml(n.name)}</td>
                    <td>${n.up ? '<span class="text-success">Up</span>' : '<span class="text-muted">Down</span>'}</td>
                    <td>${n.speed_mbps ? n.speed_mbps + " Mbps" : '<span class="text-muted">-</span>'}</td>
                    <td>${n.errors === null ? "-" : `<span class="${n.errors ? "text-danger" : ""}">${n.errors}</span>`}</td>
                    <td>${n.drops === null ? "-" : `<span class="${n.drops ? "text-danger" : ""}">${n.drops}</span>`}</td>
                 </tr>`).join("") + "</tbody></table>"
            : notAvailable("this agent does not report network counters (needs v0.7.0)");

        const hw = server.hardware || {};
        const hwParts = [];
        if (hw.temperature_c !== undefined) hwParts.push(`Temperature ${hw.temperature_c} &deg;C`);
        if (hw.fan_rpm !== undefined) hwParts.push(`Fan ${hw.fan_rpm} rpm`);
        if (hw.battery_percent !== undefined) {
            hwParts.push(`Battery ${hw.battery_percent}%${hw.on_mains ? " (on mains)" : " (on battery)"}`);
        }
        const hwHtml = hwParts.length
            ? `<div class="small">${hwParts.join(" &middot; ")}</div>`
            : notAvailable("this machine exposes no temperature, fan or power readings");

        const skew = server.clock_skew_seconds;
        const clockHtml = skew === null || skew === undefined
            ? notAvailable("this agent does not report its clock (needs v0.7.0)")
            : server.clock_is_trustworthy
                ? `<div class="small text-success">In step with the platform (${skew >= 0 ? "+" : ""}${skew}s)</div>`
                : `<div class="small text-danger">Out by ${Math.round(Math.abs(skew) / 60)} minutes.
                     This machine's own logs and certificate checks will be affected.</div>`;

        const containers = server.containers || [];
        const containersHtml = containers.length
            ? containers.map((c) => `<div class="small"><code>${escapeHtml(c.name)}</code>
                 ${escapeHtml(c.image)} &mdash; ${escapeHtml(c.status)}</div>`).join("")
            : notAvailable("no containers running, or Docker is not installed here");

        box.innerHTML = `
            <div class="row g-3">
                <div class="col-md-6"><h6 class="small text-uppercase text-muted">CPU per core</h6>${coresHtml}</div>
                <div class="col-md-6"><h6 class="small text-uppercase text-muted">Volumes</h6>${volumesHtml}
                    <div id="capacity-forecast" class="small mt-2 text-muted">Checking growth rate&hellip;</div></div>
                <div class="col-12"><h6 class="small text-uppercase text-muted">Network</h6>${nicsHtml}</div>
                <div class="col-md-4"><h6 class="small text-uppercase text-muted">Hardware</h6>${hwHtml}</div>
                <div class="col-md-4"><h6 class="small text-uppercase text-muted">Clock</h6>${clockHtml}</div>
                <div class="col-md-4"><h6 class="small text-uppercase text-muted">Containers</h6>${containersHtml}</div>
            </div>`;

        loadForecast(server.id);
    }

    // The rate, not the percentage. "84% full" cannot tell you whether that took
    // two years or two days, and only one of those needs doing something about.
    async function loadForecast(serverId) {
        const box = document.getElementById("capacity-forecast");
        if (!box) return;
        try {
            const data = await api.get(`/servers/${serverId}/capacity`);
            const f = data.forecast;
            if (!f) {
                box.textContent = "Not enough history yet to estimate a growth rate.";
                return;
            }
            const rate = f.growth_percent_per_day;
            if (f.days_until_full === null) {
                box.textContent = `Growing ${rate}% a day over ${f.observed_days} days - no date worth quoting.`;
                return;
            }
            const tone = f.days_until_full < 30 ? "text-danger" : f.days_until_full < 90 ? "text-warning" : "text-muted";
            box.className = `small mt-2 ${tone}`;
            box.textContent = `Growing ${rate}% a day. Full in about ${f.days_until_full} days`
                + (f.full_on ? ` (around ${f.full_on})` : "") + `, from ${f.observed_days} days of readings.`;
        } catch (err) {
            box.textContent = "Growth rate unavailable.";
        }
    }

    function renderScheduledTasks(server) {
        const body = document.getElementById("tasks-body");
        const tasks = server.scheduled_tasks || [];
        if (!tasks.length) {
            body.innerHTML = `<tr><td colspan="5" class="text-muted text-center py-3">
                No scheduled tasks reported. Agents below v0.7.0 do not collect them.</td></tr>`;
            return;
        }
        body.innerHTML = tasks.map((t) => {
            // "0" is success in the Windows world; anything else is worth seeing.
            const failed = t.last_result && t.last_result !== "0";
            return `<tr>
                <td><code class="small">${escapeHtml(t.name)}</code></td>
                <td>${escapeHtml(t.status || "-")}</td>
                <td class="small">${escapeHtml(t.last_run || "-")}</td>
                <td class="small ${failed ? "text-danger" : "text-success"}">${escapeHtml(t.last_result || "-")}</td>
                <td class="small">${escapeHtml(t.next_run || "-")}</td>
            </tr>`;
        }).join("");
    }

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

        renderScheduledTasks(server);
        renderHostHealth(server);
        new bootstrap.Modal(document.getElementById("discovery-modal")).show();
    }
})();
