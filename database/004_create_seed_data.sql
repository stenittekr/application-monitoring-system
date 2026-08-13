-- =========================================================
-- 004_create_seed_data.sql
-- Development seed data: one user per role + sample applications.
-- Passwords below are bcrypt hashes (never plaintext):
--   admin@example.com      -> Admin@123
--   itmanager@example.com  -> ItManager@123
--   appowner@example.com   -> AppOwner@123
--   operator@example.com   -> Operator@123
--   auditor@example.com    -> Auditor@123
-- Change these passwords immediately in any non-local environment.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF NOT EXISTS (SELECT 1 FROM dbo.users WHERE email = 'admin@example.com')
INSERT INTO dbo.users (name, email, password_hash, role, is_active)
VALUES ('System Admin', 'admin@example.com', '$2b$12$sDq6aBANguBo9FPQ/zS8RuVRTvVp8Wxckc9Il4Y5KA7rzPZqg/jp6', 'ADMIN', 1);

IF NOT EXISTS (SELECT 1 FROM dbo.users WHERE email = 'itmanager@example.com')
INSERT INTO dbo.users (name, email, password_hash, role, is_active)
VALUES ('Jane ITManager', 'itmanager@example.com', '$2b$12$wzv5pjxs2IKutRh6I6sgbecsCuoLBGe4yPw5eNMYBcb.YOU9y1Hmy', 'IT_MANAGER', 1);

IF NOT EXISTS (SELECT 1 FROM dbo.users WHERE email = 'appowner@example.com')
INSERT INTO dbo.users (name, email, password_hash, role, is_active)
VALUES ('Oscar AppOwner', 'appowner@example.com', '$2b$12$zblShYH1TfNFHeKuy7MZSOC.1h86Hl9YunHoKLLwcdzooVV7JbZ0O', 'APP_OWNER', 1);

IF NOT EXISTS (SELECT 1 FROM dbo.users WHERE email = 'operator@example.com')
INSERT INTO dbo.users (name, email, password_hash, role, is_active)
VALUES ('Olivia Operator', 'operator@example.com', '$2b$12$rtrJ/UjgpnYgsLe.WdV1.OC7/n/zxnOaAds90/OFYjpP3CRTnQ1xi', 'OPERATOR', 1);

IF NOT EXISTS (SELECT 1 FROM dbo.users WHERE email = 'auditor@example.com')
INSERT INTO dbo.users (name, email, password_hash, role, is_active)
VALUES ('Vince Auditor', 'auditor@example.com', '$2b$12$2ae413MSGfSXJqBlzgKTh.2Y6ZCKbqBYfxmZgiIif8GtfmGsKB..a', 'AUDITOR', 1);
GO

IF NOT EXISTS (SELECT 1 FROM dbo.applications WHERE name = 'Example Public Website')
INSERT INTO dbo.applications
    (name, description, url, environment, owner_name, owner_email, manager_name, manager_email,
     monitoring_enabled, monitoring_interval, timeout, retry_count, retry_delay, expected_status_code, current_status)
VALUES
    ('Example Public Website', 'Sample production website used for demo monitoring.',
     'https://example.com', 'Production', 'Jane Manager', 'manager@example.com', 'Jane Manager', 'manager@example.com',
     1, 60, 10, 3, 5, 200, 'UNKNOWN');

IF NOT EXISTS (SELECT 1 FROM dbo.applications WHERE name = 'Example Internal API')
INSERT INTO dbo.applications
    (name, description, url, environment, owner_name, owner_email, manager_name, manager_email,
     monitoring_enabled, monitoring_interval, timeout, retry_count, retry_delay, expected_status_code, current_status)
VALUES
    ('Example Internal API', 'Sample internal REST API used for demo monitoring.',
     'https://httpbin.org/status/200', 'Production', 'System Admin', 'admin@example.com', 'Jane Manager', 'manager@example.com',
     1, 120, 10, 3, 5, 200, 'UNKNOWN');

IF NOT EXISTS (SELECT 1 FROM dbo.applications WHERE name = 'Example Staging App')
INSERT INTO dbo.applications
    (name, description, url, environment, owner_name, owner_email, manager_name, manager_email,
     monitoring_enabled, monitoring_interval, timeout, retry_count, retry_delay, expected_status_code, current_status)
VALUES
    ('Example Staging App', 'Sample staging environment app, monitoring disabled by default.',
     'https://example.org', 'Staging', 'Jane Manager', 'manager@example.com', 'System Admin', 'admin@example.com',
     0, 300, 10, 3, 5, 200, 'DISABLED');

-- Demonstrates a TCP (non-HTTP) health check - no url, just server+port.
IF NOT EXISTS (SELECT 1 FROM dbo.applications WHERE name = 'Example Database Server')
INSERT INTO dbo.applications
    (name, description, server, port, health_check_type, environment, owner_name, owner_email, manager_name, manager_email,
     monitoring_enabled, monitoring_interval, timeout, retry_count, retry_delay, expected_status_code, current_status)
VALUES
    ('Example Database Server', 'Sample TCP port check (e.g. a database listener) used for demo monitoring.',
     'example.com', 443, 'TCP', 'Production', 'System Admin', 'admin@example.com', 'Jane Manager', 'manager@example.com',
     1, 60, 10, 3, 5, 200, 'UNKNOWN');
GO

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'reminder_notifications_enabled')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('reminder_notifications_enabled', 'true');

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'reminder_interval_minutes')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('reminder_interval_minutes', '60');

-- SMTP configuration is stored here (system_settings), not in .env, so an
-- admin can change/rotate it from the Settings page at runtime. Only the
-- non-secret operational values are seeded below - smtp_password is left
-- blank on purpose. Set it once, after this script runs, via the Settings
-- page (as an ADMIN) or with:
--   UPDATE dbo.system_settings SET setting_value = N'<the real password>' WHERE setting_key = 'smtp_password';
-- Never commit the real password into this file or any other file in source control.
IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'smtp_host')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('smtp_host', 'smtp.office365.com');

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'smtp_port')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('smtp_port', '587');

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'smtp_use_tls')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('smtp_use_tls', 'true');

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'smtp_username')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('smtp_username', 'notification@awgtc.com');

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'smtp_password')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('smtp_password', '');

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'email_from')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('email_from', 'notification@awgtc.com');
GO
