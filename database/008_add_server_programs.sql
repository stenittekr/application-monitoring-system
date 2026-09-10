-- =========================================================
-- 008_add_server_programs.sql
-- Adds the installed-software inventory reported by agent v0.3.0+ (name,
-- version, publisher, install date) - the same list Programs and Features
-- shows, read from the registry's Uninstall hives. Run after 001-007.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'discovered_programs_json') IS NULL
BEGIN
    ALTER TABLE dbo.servers ADD discovered_programs_json NVARCHAR(MAX) NULL;
END
GO
