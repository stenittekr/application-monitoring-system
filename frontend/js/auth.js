/** login.html only - handles the sign-in form. */
(function () {
    if (getToken()) {
        window.location.href = "dashboard.html";
        return;
    }

    const form = document.getElementById("login-form");
    const alertBox = document.getElementById("login-alert");
    const spinner = document.getElementById("login-spinner");
    const submitBtn = document.getElementById("login-btn");

    // Submits the login form: authenticates, saves the session, then redirects to the dashboard.
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        alertBox.classList.add("d-none");
        spinner.classList.remove("d-none");
        submitBtn.disabled = true;

        try {
            const data = await api.post("/auth/login", {
                email: document.getElementById("email").value.trim(),
                password: document.getElementById("password").value,
            });
            setSession(data.access_token, data.user);
            window.location.href = "dashboard.html";
        } catch (err) {
            alertBox.textContent = err.message;
            alertBox.classList.remove("d-none");
        } finally {
            spinner.classList.add("d-none");
            submitBtn.disabled = false;
        }
    });
})();
