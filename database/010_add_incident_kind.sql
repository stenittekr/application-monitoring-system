-- =========================================================
-- 010_add_incident_kind.sql
-- Distinguishes REACHABILITY incidents (down/unreachable) from RESOURCE ones
-- (CPU/RAM/disk threshold breaches). A server can be short of disk AND
-- unreachable at the same time; without this they share a single OPEN row and
-- each silently closes the other. Run after 001-009.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.incidents', 'kind') IS NULL
BEGIN
    ALTER TABLE dbo.incidents ADD kind VARCHAR(20) NOT NULL
        CONSTRAINT DF_incidents_kind DEFAULT 'REACHABILITY'
        CONSTRAINT CK_incidents_kind CHECK (kind IN ('REACHABILITY','RESOURCE'));
END
GO
