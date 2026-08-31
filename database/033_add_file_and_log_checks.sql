-- =========================================================
-- 033_add_file_and_log_checks.sql
-- FILE and LOG check types (FR-010, FR-009).
--
-- Two failures the platform could not previously see:
--
--   * a nightly export stops being written. The process runs, the service is
--     up, the URL answers - and the file the business needs is yesterday's.
--     Every other check passes.
--   * an application writes the same exception every few seconds. Nothing is
--     down, response times are normal, and the only evidence sits in a log
--     nobody reads until someone complains.
--
-- Both now configure as ordinary checks, so they inherit intervals,
-- consecutive-failure rules, severity, maintenance windows and alert routing.
-- Run after 001-032.
-- =========================================================

USE ApplicationMonitoringDB;
GO

-- A CHECK constraint cannot be widened in place; drop and recreate it.
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_applications_health_check_type')
    ALTER TABLE dbo.applications DROP CONSTRAINT CK_applications_health_check_type;
GO

DECLARE @c SYSNAME =
    (SELECT TOP 1 cc.name FROM sys.check_constraints cc
       JOIN sys.columns col ON col.object_id = cc.parent_object_id
                           AND col.column_id = cc.parent_column_id
      WHERE cc.parent_object_id = OBJECT_ID('dbo.applications')
        AND col.name = 'health_check_type');
IF @c IS NOT NULL EXEC('ALTER TABLE dbo.applications DROP CONSTRAINT ' + @c);
GO

ALTER TABLE dbo.applications ADD CONSTRAINT CK_applications_health_check_type
    CHECK (health_check_type IN ('HTTP','HTTPS','TCP','DATABASE','WORKFLOW','FILE','LOG'));
GO

PRINT '033_add_file_and_log_checks.sql applied.';
GO
