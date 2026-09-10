-- =========================================================
-- 022_allow_unknown_health_check.sql
-- Adds UNKNOWN to the health-check status vocabulary.
--
-- A check that cannot run - a missing driver, a malformed DSN, a bug of ours -
-- is not a pass and not a fail. Before this it was recorded as neither: the
-- exception was logged and the cycle moved on, so the application kept
-- displaying its last known status. Two database checks sat on the dashboard
-- showing UP for two days while raising ModuleNotFoundError 2,400 times.
--
-- §11 requires that nothing we are unsure of reads as healthy, which needs a
-- row to be written saying so.
--
-- The constraint is unnamed in 002, so it is located through
-- sys.check_constraints rather than dropped by name.
-- Run after 001-021.
-- =========================================================

USE ApplicationMonitoringDB;
GO

-- A CHECK constraint cannot be widened in place; drop and recreate it.
DECLARE @constraint SYSNAME =
    (SELECT TOP 1 cc.name
       FROM sys.check_constraints cc
       JOIN sys.columns c
         ON c.object_id = cc.parent_object_id
        AND c.column_id = cc.parent_column_id
      WHERE cc.parent_object_id = OBJECT_ID('dbo.health_checks')
        AND c.name = 'status');

IF @constraint IS NOT NULL
    EXEC('ALTER TABLE dbo.health_checks DROP CONSTRAINT ' + @constraint);
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_health_checks_status')
    ALTER TABLE dbo.health_checks ADD CONSTRAINT CK_health_checks_status
        CHECK (status IN ('UP','DOWN','DEGRADED','UNKNOWN'));
GO

PRINT '022_allow_unknown_health_check.sql applied.';
GO
