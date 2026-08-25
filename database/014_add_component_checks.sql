-- =========================================================
-- 014_add_component_checks.sql
-- Service and process checks (FR-009, acceptance criteria 4 and 5). Discovery
-- already reports what is running; these columns record what OUGHT to be, so a
-- stopped service is detectable and distinguishable from a failed URL.
-- Also widens incidents.kind to allow COMPONENT alongside REACHABILITY/RESOURCE.
-- Run after 001-013.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'expected_services_json') IS NULL
    ALTER TABLE dbo.servers ADD expected_services_json NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.servers', 'expected_processes_json') IS NULL
    ALTER TABLE dbo.servers ADD expected_processes_json NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.servers', 'component_breach_streak') IS NULL
    ALTER TABLE dbo.servers ADD component_breach_streak INT NOT NULL
        CONSTRAINT DF_servers_component_breach_streak DEFAULT 0;
GO
IF COL_LENGTH('dbo.servers', 'component_clear_streak') IS NULL
    ALTER TABLE dbo.servers ADD component_clear_streak INT NOT NULL
        CONSTRAINT DF_servers_component_clear_streak DEFAULT 0;
GO

-- A CHECK constraint cannot be widened in place; drop and recreate it.
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_incidents_kind')
    ALTER TABLE dbo.incidents DROP CONSTRAINT CK_incidents_kind;
GO
ALTER TABLE dbo.incidents ADD CONSTRAINT CK_incidents_kind
    CHECK (kind IN ('REACHABILITY','RESOURCE','COMPONENT'));
GO
