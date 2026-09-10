-- =========================================================
-- 011_add_resource_streaks.sql
-- Flapping control for CPU/RAM/disk thresholds (requirements 13, FR-012).
-- A single instantaneous sample is not a condition: a machine waking from
-- sleep spikes CPU to 100%, which opened and closed ten incidents in ninety
-- minutes. An incident now needs consecutive breaches to open and consecutive
-- clears to close. Run after 001-010.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'resource_breach_streak') IS NULL
    ALTER TABLE dbo.servers ADD resource_breach_streak INT NOT NULL
        CONSTRAINT DF_servers_resource_breach_streak DEFAULT 0;
GO
IF COL_LENGTH('dbo.servers', 'resource_clear_streak') IS NULL
    ALTER TABLE dbo.servers ADD resource_clear_streak INT NOT NULL
        CONSTRAINT DF_servers_resource_clear_streak DEFAULT 0;
GO
