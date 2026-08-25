-- =========================================================
-- 005_add_application_health_profile.sql
-- Adds the Application Health Profile fields from requirements doc §7.3/§9:
-- a lifecycle status (Discovered -> ... -> Retired), a dependency list, and
-- a free-text baseline description. Run after 001-004 against an existing
-- ApplicationMonitoringDB, or as part of a fresh install after 002.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.applications', 'maturity_status') IS NULL
BEGIN
    ALTER TABLE dbo.applications ADD maturity_status VARCHAR(30) NOT NULL
        CONSTRAINT DF_applications_maturity_status DEFAULT 'MONITORED'
        CONSTRAINT CK_applications_maturity_status
            CHECK (maturity_status IN ('DISCOVERED','INFORMATION_REQUIRED','PROFILE_DRAFT','MONITORED','MAINTENANCE','RETIRED'));
END
GO

IF COL_LENGTH('dbo.applications', 'depends_on_json') IS NULL
BEGIN
    ALTER TABLE dbo.applications ADD depends_on_json NVARCHAR(MAX) NULL;
END
GO

IF COL_LENGTH('dbo.applications', 'baseline_notes') IS NULL
BEGIN
    ALTER TABLE dbo.applications ADD baseline_notes NVARCHAR(MAX) NULL;
END
GO
