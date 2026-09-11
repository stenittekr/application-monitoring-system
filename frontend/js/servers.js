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

    // The enrolment token, on the page. It was previously "press F12, open
    // Application, find sessionStorage, copy amns_token" - a real instruction
    // given to real people, and the wrong storage was named in the handout.
    // Nobody should be in developer tools to install an agent.
    document.getElementById("add-machine-btn").addEventListener("click", () => {
        const token = getToken() || "";
        document.getElementById("enrol-token").value = token;
        document.getElementById("enrol-command").value =
            `Install.bat ${token} ${window.location.host}`;
        new bootstrap.Modal(document.getElementById("add-machine-modal")).show();
    });

    async function copyField(fieldId, button) {
        const field = document.getElementById(fieldId);
        try {
            await navigator.clipboard.writeText(field.value);
        } catch (err) {
            // http:// pages outside localhost get no clipboard API, so fall
            // back to selecting the text for a manual Ctrl+C rather than
            // failing silently.
            field.select();
            document.execCommand("copy");
        }
        const was = button.textContent;
        button.textContent = "Copied";
        setTimeout(() => { button.textContent = was; }, 1500);
    }

    document.getElementById("copy-token-btn").addEventListener("click", (e) =>
        copyField("enrol-token", e.target));
    document.getElementById("copy-command-btn").addEventListener("click", (e) =>
        copyField("enrol-command", e.target));
    document.getElementById("servers-table-body").addEventListener("click", onTableClick);

    load();

    // Agents heartbeat every 60s, so polling faster only redraws the same rows.
    // Held while a dialog is open: the components dialog is a list of ticks
    // someone is part-way through, and a reload underneath it loses them.
    setInterval(() => {
        if (!document.querySelector(".modal.show")) load();
    }, 30000);

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
    function gb(bytes) {
        if (bytes === null || bytes === undefined) return "-";
        return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB`
                                  : `${Math.round(bytes / 1024 ** 2)} MB`;
    }

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
            ? `<table class="table table-sm mb-0"><thead><tr><th>Interface</th><th>MAC</th><th>State</th><th>Speed</th><th>Errors</th><th>Drops</th></tr></thead><tbody>`
              + nics.map((n) => `<tr>
                    <td>${escapeHtml(n.name)}</td>
                    <td class="small text-muted">${n.mac_address ? `<code>${escapeHtml(n.mac_address)}</code>` : "-"}</td>
                    <td>${n.up ? '<span class="text-success">Up</span>' : '<span class="text-muted">Down</span>'}</td>
                    <td>${n.speed_mbps ? n.speed_mbps + " Mbps" : '<span class="text-muted">-</span>'}</td>
                    <td>${n.errors === null ? "-" : `<span class="${n.errors ? "text-danger" : ""}">${n.errors}</span>`}</td>
                    <td>${n.drops === null ? "-" : `<span class="${n.drops ? "text-danger" : ""}">${n.drops}</span>`}</td>
                 </tr>`).join("") + "</tbody></table>"
            : notAvailable("this agent does not report network counters (needs v0.7.0)");

        // "88% full" is a fact nobody can act on. This is the part that says
        // what to delete or move.
        const usage = server.disk_usage || [];
        const usageHtml = usage.length
            ? usage.map((vol) => {
                const rows = (vol.folders || []).map((f) => {
                    const partial = f.complete === false
                        ? ' <span class="text-muted">(partial - scan timed out)</span>' : "";
                    // The biggest folder is broken down one level, because that
                    // is always the next question.
                    const children = (f.children || []).map((ch) => `<tr>
                            <td class="small ps-4 text-muted">&#8627; <code>${escapeHtml(ch.path)}</code></td>
                            <td class="small text-end text-muted">${ch.gb} GB</td>
                        </tr>`).join("");
                    return `<tr>
                        <td class="small"><code>${escapeHtml(f.path)}</code>${partial}</td>
                        <td class="small text-end" style="width:6rem">${f.gb} GB</td>
                    </tr>${children}`;
                }).join("");
                return `<div class="mb-2"><div class="small text-muted">${escapeHtml(vol.mount)}</div>
                        <table class="table table-sm mb-0"><tbody>${rows}</tbody></table></div>`;
              }).join("")
            : notAvailable("this agent does not measure folder sizes (needs v0.8.0)");

        // Cumulative counters, shown as totals rather than rates: two heartbeats
        // are needed for a rate and this panel has one sample. Busy time is the
        // number worth reading - a disk at its limit makes everything slow while
        // CPU, RAM and free space all look fine.
        const diskIo = server.disk_io || [];
        const diskIoHtml = diskIo.length
            ? `<table class="table table-sm mb-0"><tbody>${diskIo.map((d) => `<tr>
                    <td class="small"><code>${escapeHtml(d.disk)}</code></td>
                    <td class="small text-end">${gb(d.read_bytes)} read</td>
                    <td class="small text-end">${gb(d.write_bytes)} written</td>
                    <td class="small text-end text-muted">${d.busy_ms === null || d.busy_ms === undefined
                        ? "busy n/a" : `${Math.round(d.busy_ms / 1000)}s busy`}</td>
                </tr>`).join("")}</tbody></table>`
            : notAvailable("this agent does not report disk throughput (needs v0.13.0)");

        // Three different owners, told apart. "Cannot reach the application"
        // is a name that will not resolve, a gateway that is gone, or a lossy
        // path - and a dashboard that cannot say which sends the wrong person.
        const reach = server.reachability || {};
        const mark = (ok) => ok === null || ok === undefined
            ? '<i class="bi bi-dash-circle text-muted me-1"></i>'
            : (ok ? '<i class="bi bi-check-circle-fill text-success me-1"></i>'
                  : '<i class="bi bi-x-circle-fill text-danger me-1"></i>');
        const loss = (value) => value === null || value === undefined ? "" :
            (value > 0 ? ` <span class="text-danger">${value}% loss</span>` : " 0% loss");
        const reachHtml = Object.keys(reach).length
            ? `<div class="small">${mark(reach.gateway_reachable)}Gateway
                   <code>${escapeHtml(reach.gateway || "unknown")}</code>
                   ${reach.gateway_latency_ms !== null && reach.gateway_latency_ms !== undefined
                       ? `${reach.gateway_latency_ms} ms` : ""}${loss(reach.gateway_packet_loss_percent)}</div>
               <div class="small">${mark(reach.dns_ok)}DNS
                   <code>${escapeHtml(reach.dns_host || "-")}</code>
                   ${reach.dns_ok ? `${reach.dns_ms} ms`
                       : `<span class="text-danger">${escapeHtml(reach.dns_error || "did not resolve")}</span>`}</div>
               <div class="small">${mark(reach.platform_packet_loss_percent === 0)}Path to the platform
                   ${reach.platform_latency_ms !== null && reach.platform_latency_ms !== undefined
                       ? `${reach.platform_latency_ms} ms` : ""}${loss(reach.platform_packet_loss_percent)}</div>`
            : notAvailable("this agent does not test DNS or gateway reachability (needs v0.16.0)");

        const sites = server.web_sites || [];
        const sitesHtml = sites.length
            ? sites.map((site) => `<div class="small">
                    <span class="badge bg-light text-dark border">${escapeHtml(site.kind)}</span>
                    ${escapeHtml(site.name)}
                    <span class="${site.state === "Started" ? "text-success" : "text-danger"}">
                        ${escapeHtml(site.state || "?")}</span>
                    ${site.bindings ? `<code class="text-muted">${escapeHtml(site.bindings)}</code>` : ""}
                </div>`).join("")
            : notAvailable("IIS is not installed here, or this agent predates v0.13.0");

        // What the machine IS, as an asset register would record it - the same
        // fields Windows shows under Settings > System > About, so a row here
        // can be matched against a machine by anyone reading its screen.
        const inv = server.device_inventory || {};
        const invRows = [
            ["Full device name", inv.fqdn],
            ["Device ID", inv.device_id],
            ["Product ID", inv.product_id],
            ["Manufacturer / model", [inv.manufacturer, inv.model].filter(Boolean).join(" ")],
            ["Serial number", inv.serial_number],
            ["BIOS", inv.bios_version],
            ["Processor", inv.cpu_model],
            ["Installed RAM", inv.ram_total_mb ? `${(inv.ram_total_mb / 1024).toFixed(1)} GB` : null],
            ["System type", inv.system_type],
        ].filter(([, value]) => value);
        const inventoryHtml = invRows.length
            ? `<table class="table table-sm mb-0"><tbody>${invRows.map(([label, value]) =>
                `<tr><th class="small" style="width:12rem">${label}</th>
                     <td class="small">${escapeHtml(String(value))}</td></tr>`).join("")}</tbody></table>`
            : notAvailable("this agent does not report device inventory (needs v0.15.0)");

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

        // §7.1: the one component nobody was watching is the one doing the
        // watching. A queue that never drains means heartbeats are being kept
        // rather than delivered, while the last one that got through looks fine.
        const ah = server.agent_health || {};
        // Reported once, by the run that came back up after the one that
        // died - the only way to see why without remoting into this machine.
        const crashHtml = ah.last_crash
            ? `<div class="small text-danger">Previous run crashed ${formatDateTime(ah.last_crash.at)}:
                   ${escapeHtml(ah.last_crash.error)}</div>`
            : "";
        const agentHtml = server.agent_health_status === "UNAVAILABLE"
            ? notAvailable("this agent does not report its own health (needs v0.9.0)")
            : `<div class="small">
                   ${crashHtml}
                   <div>Version ${escapeHtml(server.agent_version || "?")}, up ${
                       Math.floor((ah.agent_uptime_seconds || 0) / 3600)}h</div>
                   <div class="${(ah.queued_heartbeats || 0) >= 10 ? "text-danger" : ""}">
                       Queued heartbeats: ${ah.queued_heartbeats || 0}${
                           (ah.queued_heartbeats || 0) >= 10
                               ? " - not reaching the platform" : ""}</div>
                   <div class="text-muted">Failed sends: ${ah.failed_heartbeats || 0} &middot;
                       ${ah.agent_memory_mb || "?"} MB &middot; ${ah.agent_cpu_percent || 0}% CPU</div>
               </div>`;

        // §7.1 as observed, not as claimed. A tick here means this machine is
        // actually configured that way; a cross means it is not, however the
        // documentation reads.
        const svc = ah.service || {};
        const yes = (ok, label, warn) => ok
            ? `<div class="small"><i class="bi bi-check-circle-fill text-success me-1"></i>${label}</div>`
            : `<div class="small"><i class="bi bi-x-circle-fill text-danger me-1"></i>${escapeHtml(warn || label)}</div>`;
        const lifecycleHtml = Object.keys(svc).length
            ? `${yes(svc.start_type === "AUTO_START", "Starts automatically after reboot",
                     `Start type is ${svc.start_type || "unknown"} - will not return after a reboot`)}
               ${yes(svc.auto_restart_on_failure, "Restarts itself if it crashes",
                     "No crash recovery - a crash leaves this machine unmonitored")}
               ${yes(svc.rollback_available, `Rollback available${
                     (svc.previous_versions || []).length ? ` (${escapeHtml(svc.previous_versions.join(", "))})` : ""}`,
                     "No previous version kept - a bad update cannot be rolled back")}
               ${yes(svc.uninstall_protected, "Uninstall protected",
                     "Any local administrator can remove the agent")}
               <div class="small text-muted mt-1">Runs as <code>${escapeHtml(svc.run_as || "?")}</code></div>
               <div class="small text-muted text-break"><code>${escapeHtml(svc.install_dir || "?")}</code></div>`
            : notAvailable("this agent does not report how it is installed (needs v0.14.0)");

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
                    <div id="capacity-trend" class="mt-2"></div>
                    <div id="capacity-forecast" class="small text-muted">Checking growth rate&hellip;</div></div>
                <div class="col-12"><h6 class="small text-uppercase text-muted">What is using the space</h6>${usageHtml}</div>
                <div class="col-12"><h6 class="small text-uppercase text-muted">Device</h6>${inventoryHtml}</div>
                <div class="col-12"><h6 class="small text-uppercase text-muted">Disk throughput</h6>${diskIoHtml}</div>
                <div class="col-md-6"><h6 class="small text-uppercase text-muted">Reachability</h6>${reachHtml}</div>
                <div class="col-12"><h6 class="small text-uppercase text-muted">Network</h6>${nicsHtml}</div>
                <div class="col-md-6"><h6 class="small text-uppercase text-muted">IIS sites &amp; pools</h6>${sitesHtml}</div>
                <div class="col-md-4"><h6 class="small text-uppercase text-muted">Hardware</h6>${hwHtml}</div>
                <div class="col-md-4"><h6 class="small text-uppercase text-muted">Clock</h6>${clockHtml}</div>
                <div class="col-md-4"><h6 class="small text-uppercase text-muted">Containers</h6>${containersHtml}</div>
                <div class="col-md-4"><h6 class="small text-uppercase text-muted">Agent</h6>${agentHtml}</div>
                <div class="col-md-8"><h6 class="small text-uppercase text-muted">Agent lifecycle</h6>${lifecycleHtml}</div>
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
            renderTrend(data.history || []);
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
            // A week of readings before this is allowed to alarm anyone. Below
            // that a single overnight jump divided by two days reads as a
            // trend, and the chart above it plainly shows a flat line.
            const trusted = f.observed_days >= 7;
            const tone = !trusted ? "text-muted"
                : f.days_until_full < 30 ? "text-danger"
                : f.days_until_full < 90 ? "text-warning" : "text-muted";
            box.className = `small ${tone}`;
            box.textContent = `Growing ${rate}% a day. Full in about ${f.days_until_full} days`
                + (f.full_on ? ` (around ${f.full_on})` : "")
                + `, from ${f.observed_days} days of readings.`
                + (trusted ? "" : " Too little history to rely on - watch the line, not the date.");
        } catch (err) {
            box.textContent = "Growth rate unavailable.";
        }
    }

    // Drawn as inline SVG on purpose - one series, one axis, no interaction.
    // A charting library is 200KB and another CDN origin for what a polyline
    // already says.
    function renderTrend(history) {
        const box = document.getElementById("capacity-trend");
        if (!box) return;
        if (history.length < 2) { box.innerHTML = ""; return; }

        const W = 300, H = 60;
        // Fixed 0-100, never scaled to the data. Auto-scaling turns a disk that
        // wobbled by half a percent into a cliff, which is how a trend chart
        // starts lying.
        const y = (v) => H - (Math.max(0, Math.min(100, v)) / 100) * H;
        const pts = history.map((r, i) =>
            `${(i / (history.length - 1)) * W},${y(r.percent).toFixed(1)}`).join(" ");
        const first = history[0], last = history[history.length - 1];
        const day = (iso) => new Date(iso).toLocaleDateString(undefined,
            { day: "numeric", month: "short" });

        box.innerHTML = `
            <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img"
                 aria-label="Disk usage from ${escapeHtml(day(first.at))} to ${escapeHtml(day(last.at))},
                             ${first.percent}% to ${last.percent}%"
                 style="max-width:${W}px">
                <polyline points="0,${H} ${pts} ${W},${H}" fill="rgba(13,110,253,.12)" stroke="none"/>
                <polyline points="${pts}" fill="none" stroke="#0d6efd" stroke-width="1.5"
                          stroke-linejoin="round"/>
            </svg>
            <div class="small text-muted d-flex justify-content-between" style="max-width:${W}px">
                <span>${escapeHtml(day(first.at))} &middot; ${first.percent}%</span>
                <span>${escapeHtml(day(last.at))} &middot; ${last.percent}%</span>
            </div>`;
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

    // What actually runs here, and what it talks to. The server tabs answered
    // "which services and processes exist" but never "which of our applications
    // is this machine responsible for" - which is the question asked when the
    // disk fills or the box needs rebooting.
    //
    // The application list is fetched whole and filtered here rather than added
    // as another endpoint: /applications is already the one the rest of the app
    // uses, and nine rows do not need a query.
    let allApplications = null;

    // The chain that answers "what is this, and what does it talk to":
    //   listening port -> owning pid -> that pid's script, and its database
    //   connections.
    //
    // Via the pid, not the port: the local port on an *outbound* connection is
    // an ephemeral one the OS picked, and matching it against the application's
    // listening port finds nothing at all.
    function programIndex(server) {
        const byPort = {};
        const scriptByPid = {};
        (server.discovered_processes || []).forEach((proc) => {
            if (proc.pid) scriptByPid[proc.pid] = proc;
        });
        (server.discovered_ports || []).forEach((row) => {
            if (row.protocol === "TCP" && row.pid && byPort[row.port] === undefined) {
                byPort[row.port] = row.pid;
            }
        });
        return { byPort, scriptByPid };
    }

    function portOf(app) {
        return app.port || Number((app.url || "").match(/:(\d+)/)?.[1]) || null;
    }

    function databasesForPid(server, pid) {
        return (server.database_links || [])
            .filter((link) => link.pid === pid)
            .map((link) => `${link.engine} ${link.remote_host}:${link.remote_port}`
                + (link.open_now ? "" : ` (${Math.round((link.seconds_since_seen || 0) / 60)}m ago)`));
    }

    // One click from "discovered" to "monitored". Discovery has always found
    // these; registering one meant retyping the address into a form, which is
    // why PS_QAS ran four applications with one of them monitored.
    //
    // Deliberately no content rule: only a person knows what the page should
    // say, and a check that only proves "something answered" is honest about
    // being incomplete. The application's own edit form asks for it.
    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-monitor-port]");
        if (!button) return;
        const server = servers.find((s) => s.id === Number(button.dataset.monitorServer));
        if (!server) return;
        button.disabled = true;
        try {
            const user = getCurrentUser();
            await api.post("/applications", {
                name: `${button.dataset.monitorName} (${server.hostname}:${button.dataset.monitorPort})`,
                url: `http://${server.hostname}:${button.dataset.monitorPort}`,
                health_check_type: "HTTP",
                environment: server.environment || "QA",
                owner_name: user.name, owner_email: user.email,
                manager_name: user.name, manager_email: user.email,
                monitoring_enabled: true, monitoring_interval: 900, timeout: 10,
                retry_count: 3, retry_delay: 5, expected_status_code: 200,
                hosted_on_server_id: server.id,
            });
            showToast("Now monitored. Add a content rule so a maintenance page cannot pass.");
            allApplications = null;          // force a refetch
            await renderApplications(server);
            await load();
        } catch (err) {
            button.disabled = false;
            showError(err);
        }
    });

    // Programs listening here that nobody registered as an application.
    //
    // The gap this closes: PS_QAS runs four Python applications and one was
    // recorded, so three could have died unnoticed. The agent has always known
    // about them - nothing was reading the list and asking what was missing.
    function unregisteredHtml(server, registered) {
        const { byPort, scriptByPid } = programIndex(server);
        const claimed = new Set(registered.map(portOf).filter(Boolean));
        const rows = [];
        Object.entries(byPort).forEach(([port, pid]) => {
            const proc = scriptByPid[pid];
            // A script path is what separates an application from a Windows
            // service: svchost has no script, app.py does.
            if (!proc || !proc.script || claimed.has(Number(port))) return;
            const databases = databasesForPid(server, pid);
            // Named from the folder the script lives in, which is what people
            // call these things - "DMS", not "app.py".
            const parts = proc.script.replace(/\//g, "\\").split("\\");
            const suggested = parts.length > 1 ? parts[parts.length - 2] : proc.script;
            rows.push(`<tr>
                <td class="small"><code>${escapeHtml(proc.script)}</code></td>
                <td class="small">${escapeHtml(server.hostname)}:${port}</td>
                <td class="small">${databases.length
                    ? databases.map((d) => `<div><code>${escapeHtml(d)}</code></div>`).join("")
                    : '<span class="text-muted">none observed</span>'}</td>
                <td class="small text-muted">pid ${pid}</td>
                <td class="text-end"><button class="btn btn-sm btn-outline-primary"
                        data-monitor-port="${port}" data-monitor-name="${escapeHtml(suggested)}"
                        data-monitor-server="${server.id}">Monitor</button></td>
            </tr>`);
        });
        if (!rows.length) return "";
        return `<div class="mt-4">
            <h6 class="small text-uppercase text-muted">Listening here but not monitored</h6>
            <p class="small text-muted mb-2">Nothing checks these, so nothing would notice them
               stopping. Add one from the Applications page to change that.</p>
            <table class="table table-sm mb-0">
                <thead><tr><th>Program</th><th>Address</th><th>Database</th><th></th>
                           <th></th></tr></thead>
                <tbody>${rows.join("")}</tbody></table></div>`;
    }

    async function renderApplications(server) {
        const box = document.getElementById("discovery-applications-body");
        if (!box) return;
        box.innerHTML = '<div class="small text-muted">Loading&hellip;</div>';
        try {
            if (!allApplications) allApplications = await api.get("/applications");
            const byId = {};
            allApplications.forEach((a) => { byId[a.id] = a; });
            const here = allApplications.filter((a) => a.hosted_on_server_id === server.id);

            if (!here.length) {
                box.innerHTML = notAvailable(
                    "no applications are recorded as hosted here - set \"Hosted on\" when "
                    + "editing an application, and its failures will be corroborated against "
                    + "this server's agent before anyone is alerted");
                return;
            }

            const { byPort, scriptByPid } = programIndex(server);

            const rows = here.map((app) => {
                const port = portOf(app);
                const pid = port ? byPort[port] : null;
                const program = pid && scriptByPid[pid]
                    ? `<code class="small">${escapeHtml(scriptByPid[pid].script || scriptByPid[pid].name)}</code>`
                      + `<div class="text-muted small">pid ${pid}`
                      + (scriptByPid[pid].memory_mb ? ` &middot; ${scriptByPid[pid].memory_mb} MB` : "")
                      + `</div>`
                    : '<span class="text-muted">-</span>';
                // A DATABASE check IS the database; anything else reaches one
                // through a recorded dependency. Both are worth showing, because
                // "which database does this application use" is the question and
                // the answer lives in two different places.
                // Three sources, best first: what the agent watched this
                // application connect to, then a recorded dependency, then the
                // check's own target when the check IS a database. Observed
                // beats declared - a config file says what was intended.
                const observed = pid ? databasesForPid(server, pid) : [];
                const declared = app.health_check_type === "DATABASE"
                    ? [app.url]
                    : (app.depends_on || [])
                        .map((id) => byId[id])
                        .filter((dep) => dep && dep.health_check_type === "DATABASE")
                        .map((dep) => `${dep.name} - ${dep.url}`);
                const databases = observed.length ? observed : declared;
                const target = app.health_check_type === "TCP"
                    ? `${escapeHtml(app.server || "")}:${app.port || ""}`
                    : `<code class="small">${escapeHtml(app.url || "-")}</code>`;
                return `<tr>
                    <td>${escapeHtml(app.name)}</td>
                    <td>${statusBadge(app.current_status)}</td>
                    <td class="small">${escapeHtml(app.health_check_type)}</td>
                    <td class="small">${target}</td>
                    <td>${program}</td>
                    <td class="small">${databases.length
                        ? databases.map((d) => `<div><code>${escapeHtml(d)}</code></div>`).join("")
                        : '<span class="text-muted">not recorded</span>'}</td>
                    <td class="small">${escapeHtml(app.environment || "-")}</td>
                </tr>`;
            }).join("");

            box.innerHTML = `<table class="table table-sm mb-0">
                <thead><tr><th>Application</th><th>Status</th><th>Check</th><th>Target</th>
                           <th>Program</th><th>Database</th><th>Environment</th></tr></thead>
                <tbody>${rows}</tbody></table>
                ${unregisteredHtml(server, here)}`;
        } catch (err) {
            box.innerHTML = notAvailable("could not load the application list");
        }
    }

    // For a stuck-but-alive agent only: a crash already recovers on its own
    // (the service's own configured recovery), and an out-of-date agent
    // already updates itself on its next check-in, no admin action needed
    // either way - a 200+ machine fleet cannot mean a command run by hand.
    async function restartAgent(serverId, button) {
        button.disabled = true;
        try {
            await api.post(`/servers/${serverId}/agent-command`, { action: "RESTART" });
            showToast("Restart queued - applied on this agent's next check-in.");
        } catch (err) {
            showError(err);
        } finally {
            button.disabled = false;
        }
    }

    // Phase 1 of on-demand remote support: a screenshot on request, not a
    // live feed - the agent only ever polls, it never accepts an inbound
    // connection.
    async function takeScreenshot(serverId, button) {
        button.disabled = true;
        try {
            await api.post(`/servers/${serverId}/agent-command`, { action: "SCREENSHOT" });
            showToast("Screenshot requested - captured on this agent's next check-in.");
        } catch (err) {
            showError(err);
        } finally {
            button.disabled = false;
        }
    }

    // Not a plain <img src>: the API needs the same Bearer token every other
    // request here carries, which a browser never attaches to an <img> tag by
    // itself - fetched as a blob and handed to the <img> as an object URL.
    async function renderScreenshot(server) {
        const box = document.getElementById("screenshot-body");
        if (!server.last_screenshot_at) {
            box.innerHTML = '<div class="text-muted small">No screenshot taken yet.</div>';
            return;
        }
        const captionHtml = `<div class="small text-muted mb-2">Captured ${formatDateTime(server.last_screenshot_at)}</div>`;
        box.innerHTML = captionHtml + '<div class="text-muted small">Loading&hellip;</div>';
        try {
            const resp = await fetch(`${API_BASE_URL}/servers/${server.id}/screenshot`,
                { headers: { Authorization: `Bearer ${getToken()}` } });
            if (!resp.ok) throw new Error("screenshot not available");
            const url = URL.createObjectURL(await resp.blob());
            box.innerHTML = captionHtml
                + `<img src="${url}" class="img-fluid border rounded" alt="Screenshot of ${escapeHtml(server.hostname)}">`;
        } catch (err) {
            box.innerHTML = captionHtml + '<div class="text-muted small">Could not load the screenshot.</div>';
        }
    }

    // A specific, logged action, not an open command channel - restarts one
    // named service the agent already discovered on this machine.
    window.__restartService = async (serverId, serviceName, button) => {
        button.disabled = true;
        try {
            await api.post(`/servers/${serverId}/agent-command`,
                { action: "RESTART_SERVICE", service_name: serviceName });
            showToast(`Restart of "${serviceName}" queued - applied on this agent's next check-in.`);
        } catch (err) {
            showError(err);
        } finally {
            button.disabled = false;
        }
    };

    function openDiscoveryModal(server) {
        document.getElementById("discovery-modal-title").textContent = `Discovered on ${server.hostname}`;

        const isAdmin = getCurrentUser().role === "ADMIN";
        const commandButtons = document.getElementById("agent-command-buttons");
        commandButtons.classList.toggle("d-none", !isAdmin);
        document.getElementById("agent-restart-btn").onclick = (e) => restartAgent(server.id, e.currentTarget);
        document.getElementById("agent-screenshot-btn").onclick = (e) => takeScreenshot(server.id, e.currentTarget);
        renderScreenshot(server);
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
                    <td>${isAdmin
                        ? `<button type="button" class="btn btn-sm btn-outline-secondary"
                               onclick='window.__restartService(${server.id}, ${JSON.stringify(svc.name)}, this)'>Restart</button>`
                        : ""}</td>
                </tr>`).join("")
            : `<tr><td colspan="5" class="text-muted text-center py-3">No services reported.</td></tr>`;
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
        renderApplications(server);
        new bootstrap.Modal(document.getElementById("discovery-modal")).show();
    }
})();
