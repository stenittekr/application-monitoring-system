-- =========================================================
-- 025_add_owner_only_alerts.sql
-- Marks a server as monitoring infrastructure rather than a business system.
--
-- The laptop running the platform raised 19 of the last 27 incidents: CPU
-- spikes on wake, missed heartbeats when it left the office. All real, all
-- worth recording, none of them a manager's problem. Alerts about a server
-- flagged here go to its owner and no further.
--
-- Defaults to 0, so every existing server keeps copying the full list.
-- Run after 001-024.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'owner_only_alerts') IS NULL
    ALTER TABLE dbo.servers ADD owner_only_alerts BIT NOT NULL
        CONSTRAINT DF_servers_owner_only_alerts DEFAULT 0;
GO

PRINT '025_add_owner_only_alerts.sql applied.';
GO
