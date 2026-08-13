(function () {
    initLayout("users");

    const modal = new bootstrap.Modal(document.getElementById("user-form-modal"));
    // Opens the modal in "new user" mode.
    document.getElementById("new-user-btn").addEventListener("click", () => openForm(null));
    document.getElementById("user-form").addEventListener("submit", onSubmit);

    load();

    // Fetches all users and renders the table.
    async function load() {
        try {
            const users = await api.get("/users");
            renderTable(users);
        } catch (err) {
            showError(err);
        }
    }

    // Renders the users table rows, including edit and enable/disable buttons.
    function renderTable(users) {
        const tbody = document.getElementById("users-table-body");
        tbody.innerHTML = users.map((u) => `
            <tr>
                <td>${escapeHtml(u.name)}</td>
                <td>${escapeHtml(u.email)}</td>
                <td><span class="badge bg-primary-subtle text-primary-emphasis">${u.role}</span></td>
                <td>${u.is_active ? '<span class="text-success">Active</span>' : '<span class="text-muted">Disabled</span>'}</td>
                <td>${formatDateTime(u.last_login_at)}</td>
                <td class="btn-group btn-group-sm">
                    <button class="btn btn-outline-secondary" title="Edit" onclick='window.__editUser(${JSON.stringify(u)})'><i class="bi bi-pencil"></i></button>
                    <button class="btn btn-outline-${u.is_active ? "danger" : "success"}" title="${u.is_active ? "Disable" : "Enable"}"
                        onclick="window.__toggleUser(${u.id}, ${!u.is_active})">
                        <i class="bi ${u.is_active ? "bi-person-x" : "bi-person-check"}"></i>
                    </button>
                </td>
            </tr>`).join("");
    }

    // Fills the create/edit form with an existing user's data (or blank defaults) and opens the modal.
    function openForm(user) {
        document.getElementById("user-form-title").textContent = user ? "Edit User" : "New User";
        document.getElementById("user-id").value = user ? user.id : "";
        document.getElementById("user-name").value = user ? user.name : "";
        document.getElementById("user-email").value = user ? user.email : "";
        document.getElementById("user-role").value = user ? user.role : "VIEWER";
        document.getElementById("user-password").value = "";
        document.getElementById("user-password").required = !user;
        document.getElementById("user-password-hint").style.display = user ? "block" : "none";
        document.getElementById("user-active-wrapper").style.display = user ? "block" : "none";
        document.getElementById("user-active").checked = user ? user.is_active : true;
        modal.show();
    }

    // Reads the form fields and creates or updates the user via the API.
    async function onSubmit(event) {
        event.preventDefault();
        const id = document.getElementById("user-id").value;
        const password = document.getElementById("user-password").value;
        try {
            if (id) {
                const payload = {
                    name: document.getElementById("user-name").value.trim(),
                    email: document.getElementById("user-email").value.trim(),
                    role: document.getElementById("user-role").value,
                    is_active: document.getElementById("user-active").checked,
                };
                if (password) payload.password = password;
                await api.put(`/users/${id}`, payload);
                showToast("User updated.");
            } else {
                await api.post("/users", {
                    name: document.getElementById("user-name").value.trim(),
                    email: document.getElementById("user-email").value.trim(),
                    role: document.getElementById("user-role").value,
                    password,
                });
                showToast("User created.");
            }
            modal.hide();
            await load();
        } catch (err) {
            showError(err);
        }
    }

    // Exposes openForm as the row "Edit" button handler.
    window.__editUser = openForm;
    // Enables or disables a user account (row toggle button).
    window.__toggleUser = async (id, active) => {
        try {
            await api.put(`/users/${id}`, { is_active: active });
            showToast(`User ${active ? "enabled" : "disabled"}.`);
            await load();
        } catch (err) {
            showError(err);
        }
    };
})();
