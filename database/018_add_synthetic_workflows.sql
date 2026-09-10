-- =========================================================
-- 018_add_synthetic_workflows.sql
-- FR-011 / layer 5: a declarative synthetic business transaction per
-- application, stored as JSON steps. Never code - §14 permits only
-- allow-listed actions - and credentials are ${ENV_VAR} references, so test
-- logins are not stored in the profile text (§18).
-- Also widens the health-check type to allow WORKFLOW.
-- Run after 001-017.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.applications', 'workflow_json') IS NULL
    ALTER TABLE dbo.applications ADD workflow_json NVARCHAR(MAX) NULL;
GO

IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_applications_health_check_type')
    ALTER TABLE dbo.applications DROP CONSTRAINT CK_applications_health_check_type;
GO
ALTER TABLE dbo.applications ADD CONSTRAINT CK_applications_health_check_type
    CHECK (health_check_type IN ('HTTP','HTTPS','TCP','DATABASE','WORKFLOW'));
GO
