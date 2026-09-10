-- =========================================================
-- 012_add_alert_confirmation.sql
-- An application must fail consecutive WHOLE checks - not just the retries
-- inside one check - before an incident is opened and anyone is emailed, so a
-- momentary blip never alerts for a site that is actually serving.
-- Also seeds the standing alert CC list and the confirmation count.
-- Run after 001-011.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.applications', 'failure_streak') IS NULL
    ALTER TABLE dbo.applications ADD failure_streak INT NOT NULL
        CONSTRAINT DF_applications_failure_streak DEFAULT 0;
GO

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'failed_checks_before_incident')
INSERT INTO dbo.system_settings (setting_key, setting_value) VALUES ('failed_checks_before_incident', '2');
GO

-- Everyone CC'd on every application alert, on top of the application's own
-- manager. Comma-separated; edit here rather than in code.
IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'alert_cc_recipients')
INSERT INTO dbo.system_settings (setting_key, setting_value)
VALUES ('alert_cc_recipients', N'ajoy@awgtc.com, raam@awgtc.com, m.nizar@awgtc.com, stenitte@awgtc.com');
GO
