(function () {
    initLayout("servers");

    let servers = [];
    document.getElementById("refresh-btn").addEventListener("click", load);
    document.getElementById("servers-table-body").addEventListener("click", onTableClick);

    load();

    // Fetches the enrolled server list and renders the table.
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
            tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-4">
                No servers enrolled yet. Run the agent's <code>enroll</code> command to register one.</td></tr>`;
            return;
        }
        tbody.innerHTML = servers.map((s) => `
            <tr>
                <td>${escapeHtml(s.hostname)}</td>
                <td>${escapeHtml(s.ip_address || "-")}</td>
                <td>${escapeHtml([s.os_name, s.os_version].filter(Boolean).join(" ") || "-")}</td>
                <td>${statusBadge(s.current_status)}</td>
                <td>${formatPercent(s.cpu_percent)}</td>
                <td>${formatPercent(s.ram_percent)}</td>
                <td>${formatPercent(s.disk_percent)}</td>
                <td>${formatDateTime(s.last_heartbeat_at)}</td>
                <td>${formatDateTime(s.last_boot_at)}</td>
                <td>
                    <button class="btn btn-sm btn-outline-secondary" data-server-id="${s.id}">
                        ${s.discovered_services.length} services, ${s.discovered_ports.length} ports
                    </button>
                </td>
            </tr>`).join("");
    }

    function formatPercent(value) {
        return value === null || value === undefined ? "-" : `${Math.round(value)}%`;
    }

    function onTableClick(event) {
        const btn = event.target.closest("button[data-server-id]");
        if (!btn) return;
        const server = servers.find((s) => s.id === Number(btn.dataset.serverId));
        if (server) openDiscoveryModal(server);
    }

    function openDiscoveryModal(server) {
        document.getElementById("discovery-modal-title").textContent = `Discovered on ${server.hostname}`;
        document.getElementById("discovery-services-body").innerHTML = server.discovered_services.length
            ? server.discovered_services.map((svc) => `
                <tr><td>${escapeHtml(svc.name)}</td><td>${escapeHtml(svc.display_name || "-")}</td><td>${escapeHtml(svc.status || "-")}</td></tr>`).join("")
            : `<tr><td colspan="3" class="text-muted text-center py-3">No services reported.</td></tr>`;
        document.getElementById("discovery-ports-body").innerHTML = server.discovered_ports.length
            ? server.discovered_ports.map((p) => `
                <tr><td>${p.port ?? "-"}</td><td>${escapeHtml(p.protocol || "-")}</td><td>${escapeHtml(p.process_name || "-")}</td></tr>`).join("")
            : `<tr><td colspan="3" class="text-muted text-center py-3">No ports reported.</td></tr>`;
        new bootstrap.Modal(document.getElementById("discovery-modal")).show();
    }
})();
