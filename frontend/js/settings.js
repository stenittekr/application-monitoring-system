(function () {
    initLayout("settings");

    const SMTP_FIELDS = [
        { key: "smtp_host", label: "SMTP Host", type: "text", placeholder: "smtp.office365.com" },
        { key: "smtp_port", label: "SMTP Port", type: "number", placeholder: "587" },
        { key: "smtp_username", label: "SMTP Username", type: "text", placeholder: "notifications@example.com" },
        { key: "smtp_password", label: "SMTP Password", type: "password", placeholder: "" },
        { key: "email_from", label: "From Address", type: "text", placeholder: "notifications@example.com" },
        { key: "smtp_use_tls", label: "Use TLS", type: "select", options: ["true", "false"] },
    ];

    let settingsByKey = {};

    load();
    document.getElementById("save-smtp-btn").addEventListener("click", saveSmtpSettings);

    // Fetches all settings and renders the SMTP fields.
    async function load() {
        try {
            const rows = await api.get("/settings");
            settingsByKey = Object.fromEntries(rows.map((r) => [r.setting_key, r.setting_value]));
            renderSmtpFields();
        } catch (err) {
            showError(err);
        }
    }

    // Builds the SMTP settings form inputs, masking the stored password field.
    function renderSmtpFields() {
        const container = document.getElementById("smtp-settings-fields");
        container.innerHTML = SMTP_FIELDS.map((field) => {
            const currentValue = settingsByKey[field.key] || "";
            const isSecret = field.type === "password";
            const inputValue = isSecret ? "" : currentValue;
            const hint = isSecret && currentValue
                ? `<div class="form-text">Currently set (hidden). Leave blank to keep it.</div>`
                : "";
            let input;
            if (field.type === "select") {
                input = `<select class="form-select" id="smtp-${field.key}">
                    ${field.options.map((o) => `<option value="${o}" ${o === currentValue ? "selected" : ""}>${o === "true" ? "Yes" : "No"}</option>`).join("")}
                </select>`;
            } else {
                input = `<input type="${field.type}" class="form-control" id="smtp-${field.key}" value="${escapeHtml(inputValue)}" placeholder="${field.placeholder}">`;
            }
            return `<div class="col-md-6"><label class="form-label">${field.label}</label>${input}${hint}</div>`;
        }).join("");
    }

    // Saves each SMTP field to the backend, skipping the password field if left blank.
    async function saveSmtpSettings() {
        try {
            for (const field of SMTP_FIELDS) {
                const value = document.getElementById(`smtp-${field.key}`).value;
                if (field.type === "password" && !value) continue; // keep existing password
                await api.put(`/settings/${field.key}`, { setting_value: value });
            }
            showToast("Email settings saved.");
            await load();
        } catch (err) {
            showError(err);
        }
    }
})();
