-- =========================================================
-- 029_add_alert_scope.sql
-- Who hears about a particular machine: everyone, its owner, or nobody.
--
-- Replaces the owner_only_alerts flag with three states, because two were not
-- enough. The laptop running the platform raised 19 of 27 incidents in one
-- week - CPU spikes on wake, missed heartbeats when it went home. All real,
-- none of it a manager's problem, and some of it not worth an email at all.
--
--   ALL    owner plus the standing distribution list (the default)
--   OWNER  its owner only
--   NONE   nobody - still recorded, still on the dashboard, never emailed
--
-- Existing values carry over: owner_only_alerts = 1 becomes OWNER.
-- Run after 001-028.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'alert_scope') IS NULL
    ALTER TABLE dbo.servers ADD alert_scope VARCHAR(10) NOT NULL
        CONSTRAINT DF_servers_alert_scope DEFAULT 'ALL';
GO

IF COL_LENGTH('dbo.servers', 'owner_only_alerts') IS NOT NULL
    UPDATE dbo.servers SET alert_scope = 'OWNER' WHERE owner_only_alerts = 1;
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_servers_alert_scope')
    ALTER TABLE dbo.servers ADD CONSTRAINT CK_servers_alert_scope
        CHECK (alert_scope IN ('ALL','OWNER','NONE'));
GO

-- The old flag is superseded. Its default constraint has to go first.
IF COL_LENGTH('dbo.servers', 'owner_only_alerts') IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM sys.default_constraints WHERE name = 'DF_servers_owner_only_alerts')
        ALTER TABLE dbo.servers DROP CONSTRAINT DF_servers_owner_only_alerts;
    ALTER TABLE dbo.servers DROP COLUMN owner_only_alerts;
END
GO

PRINT '029_add_alert_scope.sql applied.';
GO
