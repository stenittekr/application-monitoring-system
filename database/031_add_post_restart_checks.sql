-- =========================================================
-- 031_add_post_restart_checks.sql
-- Marks a server as needing a priority check after it reboots (§10, FR-004).
--
-- The platform detected restarts and logged them, then waited for each
-- application's normal interval to come round before checking anything. A
-- machine that has just come back is the least trustworthy it ever is: a
-- service set to manual does not return, a mapped drive is missing, an
-- auto-start task fails silently. PS_QAS has had a failing FeedBack App
-- auto-start task since 18 August and nothing said so.
-- Run after 001-030.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'restart_pending_checks_at') IS NULL
    ALTER TABLE dbo.servers ADD restart_pending_checks_at DATETIME2 NULL;
GO

PRINT '031_add_post_restart_checks.sql applied.';
GO
