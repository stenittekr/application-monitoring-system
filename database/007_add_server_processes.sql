-- =========================================================
-- 007_add_server_processes.sql
-- Adds the running-process inventory reported by agent v0.3.0+: process name,
-- pid, user, memory, and for interpreters (python/node/java/...) the script
-- being run - so "python.exe" on the dashboard becomes an answer to "which of
-- our scripts is that". Same JSON-column pattern as discovered_services_json.
-- Run after 001-006.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'discovered_processes_json') IS NULL
BEGIN
    ALTER TABLE dbo.servers ADD discovered_processes_json NVARCHAR(MAX) NULL;
END
GO
