-- =========================================================
-- 013_add_database_inventory.sql
-- Stores what lives on a monitored SQL instance (database name, state,
-- recovery model), collected on each DATABASE health check. Answers "which
-- databases are on this server" without needing an agent on the DB host.
-- Run after 001-012.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.applications', 'discovered_databases_json') IS NULL
    ALTER TABLE dbo.applications ADD discovered_databases_json NVARCHAR(MAX) NULL;
GO
