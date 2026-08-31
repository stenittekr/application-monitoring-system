-- =========================================================
-- 028_add_alert_switch.sql
-- A master switch for incident alert email.
--
-- Quiet days hold mail and deliver it later. On 31 August that meant a weekend
-- of alerts arriving in one burst on Monday morning - most of them about a
-- database that was never down, because the machine running the platform had
-- gone home on Thursday.
--
-- This switch discards instead of holding, so turning it back on cannot
-- produce a flood. Incidents are still opened, recorded and shown; only the
-- emailing stops.
--
-- Seeded 'true'. The current deployment sets it false until the platform moves
-- off the laptop it runs on.
-- Run after 001-027.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'incident_alerts_enabled')
    INSERT INTO dbo.system_settings (setting_key, setting_value)
    VALUES ('incident_alerts_enabled', 'true');
GO

PRINT '028_add_alert_switch.sql applied.';
GO
