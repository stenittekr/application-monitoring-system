-- =========================================================
-- 023_add_blocked_recipients.sql
-- A block list of addresses that must never receive alert mail.
--
-- Removing someone from the distribution list only holds until the next thing
-- that builds a recipient from an owner field, a manager field or an
-- escalation path. send_email is the single choke point every message passes
-- through, and this is the list it checks there.
--
-- Seeded empty: the mechanism travels with the schema, the addresses do not.
-- Names of people taken off the alerts do not belong in source control.
-- Run after 001-022.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF NOT EXISTS (SELECT 1 FROM dbo.system_settings WHERE setting_key = 'alert_blocked_recipients')
    INSERT INTO dbo.system_settings (setting_key, setting_value)
    VALUES ('alert_blocked_recipients', '');
GO

PRINT '023_add_blocked_recipients.sql applied.';
GO
