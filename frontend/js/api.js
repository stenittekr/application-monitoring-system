/**
 * Shared API client + app shell (sidebar/topbar) + small UI helpers.
 * Every page includes this file before its own page-specific script.
 */
const API_BASE_URL = window.AMNS_API_BASE_URL || "http://localhost:5000/api";

const TOKEN_KEY = "amns_token";
const USER_KEY = "amns_user";

// Reads the saved auth token out of session storage.
function getToken() {
    return sessionStorage.getItem(TOKEN_KEY);
}

// Reads and parses the saved logged-in user out of session storage.
function getCurrentUser() {
    const raw = sessionStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
}

// Saves the auth token and user info after a successful login.
function setSession(token, user) {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

// Removes the saved auth token and user info (logout).
function clearSession() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
}

/** Redirects to login if there's no token. Call at the top of every protected page. */
function requireAuth() {
    if (!getToken()) {
        window.location.href = "login.html";
    }
}

// Sends an authenticated request to the API and unwraps the JSON response (or throws on failure).
async function apiRequest(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    let response;
    try {
        response = await fetch(`${API_BASE_URL}${path}`, {
            method,
            headers,
            body: body !== undefined ? JSON.stringify(body) : undefined,
        });
    } catch (networkError) {
        throw new Error("Could not reach the server. Is the Flask API running?");
    }

    if (response.status === 401) {
        clearSession();
        window.location.href = "login.html";
        throw new Error("Session expired.");
    }

    const isCsv = (response.headers.get("content-type") || "").includes("text/csv");
    if (isCsv) return response; // caller handles the raw response (e.g. CSV download)

    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
        throw new Error(payload.message || `Request failed (${response.status}).`);
    }
    return payload.data;
}

// Thin GET/POST/PUT/DELETE convenience wrapper around apiRequest.
const api = {
    get: (path) => apiRequest("GET", path),
    post: (path, body) => apiRequest("POST", path, body ?? {}),
    put: (path, body) => apiRequest("PUT", path, body ?? {}),
    del: (path) => apiRequest("DELETE", path),
};

/* ---------------------------- UI helpers ---------------------------- */

// Pops up a temporary Bootstrap toast notification with the given message.
function showToast(message, variant = "success") {
    let container = document.getElementById("amns-toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "amns-toast-container";
        document.body.appendChild(container);
    }
    const toastEl = document.createElement("div");
    toastEl.className = `toast align-items-center text-bg-${variant} border-0`;
    toastEl.setAttribute("role", "alert");
    toastEl.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${escapeHtml(message)}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>`;
    container.appendChild(toastEl);
    const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
    toast.show();
    toastEl.addEventListener("hidden.bs.toast", () => toastEl.remove());
}

// Shows an error message as a red toast.
function showError(err) {
    showToast(err.message || String(err), "danger");
}

// Escapes a value for safe insertion into HTML (prevents XSS from user-entered text).
function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}

// Formats an ISO timestamp from the backend into a readable local date/time string.
function formatDateTime(iso) {
    if (!iso) return "-";
    // Backend timestamps are always UTC but SQLite/SQLAlchemy strips the
    // timezone marker on read-back, so a string with no Z/offset would
    // otherwise be misread by Date() as already-local time.
    const hasTimezone = /Z$|[+-]\d{2}:\d{2}$/.test(iso);
    const date = new Date(hasTimezone ? iso : `${iso}Z`);
    if (isNaN(date.getTime())) return "-";
    return date.toLocaleString();
}

// Builds the small colored status badge HTML for a given status string.
function statusBadge(status) {
    const label = status || "UNKNOWN";
    return `<span class="status-badge status-${label}">${label}</span>`;
}

/** Returns a Promise<boolean> resolved by the user's choice in a Bootstrap modal. */
function confirmAction(message) {
    return new Promise((resolve) => {
        let modalEl = document.getElementById("amns-confirm-modal");
        if (!modalEl) {
            modalEl = document.createElement("div");
            modalEl.id = "amns-confirm-modal";
            modalEl.className = "modal fade";
            modalEl.tabIndex = -1;
            modalEl.innerHTML = `
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Please confirm</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body" id="amns-confirm-message"></div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-danger" id="amns-confirm-ok">Confirm</button>
                        </div>
                    </div>
                </div>`;
            document.body.appendChild(modalEl);
        }
        modalEl.querySelector("#amns-confirm-message").textContent = message;
        const modal = new bootstrap.Modal(modalEl);
        const okBtn = modalEl.querySelector("#amns-confirm-ok");

        // User clicked "Confirm": resolve true and close the modal.
        const onOk = () => {
            cleanup();
            modal.hide();
            resolve(true);
        };
        // Modal was dismissed some other way (Cancel, backdrop, Esc): resolve false.
        const onHidden = () => {
            cleanup();
            resolve(false);
        };
        // Detaches the one-time listeners so they don't stack up on repeated calls.
        function cleanup() {
            okBtn.removeEventListener("click", onOk);
            modalEl.removeEventListener("hidden.bs.modal", onHidden);
        }
        okBtn.addEventListener("click", onOk);
        modalEl.addEventListener("hidden.bs.modal", onHidden, { once: true });
        modal.show();
    });
}

/* ---------------------------- App shell ---------------------------- */

const NAV_ITEMS = [
    { key: "dashboard", label: "Dashboard", href: "dashboard.html", icon: "bi-speedometer2", roles: ["ADMIN", "MANAGER", "VIEWER"] },
    { key: "incidents", label: "Incidents", href: "incidents.html", icon: "bi-exclamation-triangle", roles: ["ADMIN", "MANAGER", "VIEWER"] },
    { key: "health-checks", label: "Health Checks", href: "health-checks.html", icon: "bi-heart-pulse", roles: ["ADMIN", "MANAGER", "VIEWER"] },
    { key: "servers", label: "Servers", href: "servers.html", icon: "bi-hdd-network", roles: ["ADMIN", "MANAGER", "VIEWER"] },
    { key: "users", label: "Users", href: "users.html", icon: "bi-people", roles: ["ADMIN"] },
    { key: "settings", label: "Settings", href: "settings.html", icon: "bi-gear", roles: ["ADMIN"] },
];

/** Builds the sidebar/topbar shell and wraps existing #amns-page-content.
 * Call once at the top of every protected page's own script. */
function initLayout(activeKey) {
    requireAuth();
    const user = getCurrentUser();
    if (!user) {
        window.location.href = "login.html";
        return;
    }

    const navHtml = NAV_ITEMS.filter((item) => item.roles.includes(user.role))
        .map((item) => `
            <a class="nav-link ${item.key === activeKey ? "active" : ""}" href="${item.href}">
                <i class="bi ${item.icon} me-2"></i>${item.label}
            </a>`)
        .join("");

    const shell = document.createElement("div");
    shell.innerHTML = `
        <nav id="amns-sidebar" class="d-flex flex-column">
            <div class="brand"><i class="bi bi-activity me-2"></i>Central Monitoring & Diagnostic Platform</div>
            <div class="nav flex-column">${navHtml}</div>
        </nav>
        <div id="amns-main">
            <header id="amns-topbar">
                <div class="fw-semibold text-secondary" id="amns-page-title"></div>
                <div class="d-flex align-items-center gap-3">
                    <span class="text-muted small">${escapeHtml(user.name)} &middot; ${user.role}</span>
                    <button class="btn btn-sm btn-outline-secondary" id="amns-logout-btn">
                        <i class="bi bi-box-arrow-right"></i> Logout
                    </button>
                </div>
            </header>
            <main id="amns-page-content"></main>
        </div>`;

    const existingContent = document.getElementById("amns-page-content");
    const pageBody = existingContent ? existingContent.innerHTML : "";
    // Anything living directly under <body> outside #amns-page-content (e.g. a
    // page's own modal) would otherwise be destroyed by body.innerHTML = "" below.
    const extraNodes = Array.from(document.body.children).filter((el) => el.id !== "amns-page-content");
    const pageTitle = document.body.getAttribute("data-page-title") || "";

    document.body.innerHTML = "";
    document.body.appendChild(shell);
    document.getElementById("amns-page-content").innerHTML = pageBody;
    document.getElementById("amns-page-title").textContent = pageTitle;
    extraNodes.forEach((el) => document.body.appendChild(el));

    // Logs the user out on the server (best-effort) and always clears the local session.
    document.getElementById("amns-logout-btn").addEventListener("click", async () => {
        try {
            await api.post("/auth/logout");
        } catch (e) {
            /* ignore - we're logging out either way */
        }
        clearSession();
        window.location.href = "login.html";
    });
}
