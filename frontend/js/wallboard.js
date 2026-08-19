/** Read-only, no-chrome display mode meant for a TV/wallboard - no sidebar,
 * no buttons, just status at a glance. Auto-refreshes on its own; nobody
 * needs to touch it once it's open. */
(function () {
    requireAuth();

    const REFRESH_MS = 15000;

    tickClock();
    setInterval(tickClock, 1000);
    load();
    setInterval(load, REFRESH_MS);

    // Updates the live clock/date in the top-right corner.
    function tickClock() {
        const now = new Date();
        document.getElementById("wb-clock").textContent = now.toLocaleTimeString();
        document.getElementById("wb-date").textContent = now.toLocaleDateString(undefined, {
            weekday: "long", year: "numeric", month: "long", day: "numeric",
        });
    }

    // Fetches applications, open incidents, and (if permitted) servers, then re-renders everything.
    async function load() {
        try {
            const [apps, incidents] = await Promise.all([
                api.get("/applications"),
                api.get("/incidents?status=OPEN"),
            ]);
            // A viewer without server access (e.g. Application Owner) still sees
            // the wallboard - servers just render as an empty section for them.
            const servers = await api.get("/servers").catch(() => []);

            renderAlertBanner(apps, servers, incidents);
            renderStats(apps, servers, incidents);
            renderApps(apps);
            renderServers(servers);
        } catch (err) {
            showError(err);
        }
    }

    // Shows a single unmissable banner across the top when anything is down.
    function renderAlertBanner(apps, servers, incidents) {
        const downApps = apps.filter((a) => a.current_status === "DOWN");
        const downServers = servers.filter((s) => s.current_status === "DOWN");
        const banner = document.getElementById("wb-alert-banner");
        const total = downApps.length + downServers.length;
        if (!total) {
            banner.classList.remove("show");
            return;
        }
        const names = [...downApps.map((a) => a.name), ...downServers.map((s) => s.hostname)];
        const label = total === 1 ? "1 issue" : `${total} issues`;
        document.getElementById("wb-alert-text").textContent =
            `${label} needs attention: ${names.join(", ")} (${incidents.length} open incident${incidents.length === 1 ? "" : "s"})`;
        banner.classList.add("show");
    }

    // Renders the big at-a-glance stat tiles.
    function renderStats(apps, servers, incidents) {
        const appsUp = apps.filter((a) => a.current_status === "UP").length;
        const appsDown = apps.filter((a) => a.current_status === "DOWN").length;
        const serversUp = servers.filter((s) => s.current_status === "UP").length;
        const serversDown = servers.filter((s) => s.current_status === "DOWN").length;

        const tiles = [
            { label: "Applications", value: apps.length, color: "#39816e" },
            { label: "Apps Up", value: appsUp, color: "#1f9d6e" },
            { label: "Apps Down", value: appsDown, color: appsDown ? "#dc3545" : "#c9d3ce" },
            { label: "Servers Up", value: serversUp, color: "#1f9d6e" },
            { label: "Active Incidents", value: incidents.length, color: incidents.length ? "#dc3545" : "#c9d3ce" },
        ];
        document.getElementById("wb-stats").innerHTML = tiles.map((t) => `
            <div class="wb-stat-card" style="--bar-color:${t.color}">
                <div class="wb-stat-label">${t.label}</div>
                <div class="wb-stat-value" style="color:${t.color}">${t.value}</div>
            </div>`).join("");
    }

    // Maps an application/server status string to a dot color class.
    function dotClass(status) {
        if (status === "UP") return "up";
        if (status === "DOWN") return "down";
        return "unknown";
    }

    // Renders the application status grid.
    function renderApps(apps) {
        const el = document.getElementById("wb-apps");
        if (!apps.length) {
            el.innerHTML = `<div class="wb-empty">No applications configured yet.</div>`;
            return;
        }
        el.innerHTML = apps.map((a) => `
            <div class="wb-card ${a.current_status === "DOWN" ? "is-down" : ""}">
                <span class="wb-dot ${dotClass(a.current_status)}"></span>
                <div class="wb-card-body">
                    <div class="wb-card-name">${escapeHtml(a.name)}</div>
                    <div class="wb-card-meta">${escapeHtml(a.environment)} &middot; ${escapeHtml(a.current_status)}</div>
                </div>
            </div>`).join("");
    }

    // Renders the server status grid, with a live CPU/RAM/disk snapshot per card.
    function renderServers(servers) {
        const el = document.getElementById("wb-servers");
        if (!servers.length) {
            el.innerHTML = `<div class="wb-empty">No servers enrolled yet.</div>`;
            return;
        }
        el.innerHTML = servers.map((s) => {
            const metrics = [
                s.cpu_percent !== null ? `CPU ${Math.round(s.cpu_percent)}%` : null,
                s.ram_percent !== null ? `RAM ${Math.round(s.ram_percent)}%` : null,
                s.disk_percent !== null ? `Disk ${Math.round(s.disk_percent)}%` : null,
            ].filter(Boolean).join(" &middot; ");
            return `
            <div class="wb-card ${s.current_status === "DOWN" ? "is-down" : ""}">
                <span class="wb-dot ${dotClass(s.current_status)}"></span>
                <div class="wb-card-body">
                    <div class="wb-card-name">${escapeHtml(s.hostname)}</div>
                    <div class="wb-card-meta">${metrics || "No metrics yet"}</div>
                </div>
            </div>`;
        }).join("");
    }
})();
