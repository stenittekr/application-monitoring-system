-- =========================================================
-- 034_add_application_versions.sql
-- Versioned, roll-back-able application profiles (FR-019, §19).
--
-- FR-019 asks for versioned configuration with rollback. §19 asks that a
-- configuration error retain the last valid version and be recoverable. Until
-- now a profile could be edited into a state that stopped alerting, and the
-- only record of what it had been was whoever remembered.
--
-- A full snapshot per change rather than a diff. A diff is smaller and useless
-- at the moment it is needed, when the question is "what did this look like on
-- Tuesday" and the answer must be complete enough to restore.
-- Run after 001-033.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF OBJECT_ID('dbo.application_versions', 'U') IS NULL
    CREATE TABLE dbo.application_versions (
        id             INT IDENTITY(1,1) PRIMARY KEY,
        application_id INT            NOT NULL FOREIGN KEY REFERENCES dbo.applications(id),
        version        INT            NOT NULL,
        snapshot_json  NVARCHAR(MAX)  NOT NULL,
        changed_by_id  INT            NULL FOREIGN KEY REFERENCES dbo.users(id),
        change_note    NVARCHAR(500)  NULL,
        created_at     DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
    );
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_application_versions_app')
    CREATE INDEX IX_application_versions_app
        ON dbo.application_versions(application_id, version DESC);
GO

PRINT '034_add_application_versions.sql applied.';
GO
