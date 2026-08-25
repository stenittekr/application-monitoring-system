-- =========================================================
-- 019_add_incident_notes.sql
-- §21 "acknowledge, comment, assign, resolve"; §11 step 9 "resolved with
-- timestamps, cause/category, notes and evidence".
--
-- Notes are rows rather than a column so each carries its own author and
-- timestamp, and are append-only: an investigation record that can be quietly
-- rewritten is not evidence.
-- Run after 001-018.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF OBJECT_ID('dbo.incident_notes', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.incident_notes (
        id           INT IDENTITY(1,1) PRIMARY KEY,
        incident_id  INT             NOT NULL,
        user_id      INT             NOT NULL,
        note         NVARCHAR(2000)  NOT NULL,
        created_at   DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_incident_notes_incident FOREIGN KEY (incident_id) REFERENCES dbo.incidents(id),
        CONSTRAINT FK_incident_notes_user FOREIGN KEY (user_id) REFERENCES dbo.users(id)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_incident_notes_incident')
    CREATE INDEX IX_incident_notes_incident ON dbo.incident_notes(incident_id, created_at);
GO

IF COL_LENGTH('dbo.incidents', 'resolved_by_id') IS NULL
    ALTER TABLE dbo.incidents ADD resolved_by_id INT NULL
        CONSTRAINT FK_incidents_resolved_by FOREIGN KEY REFERENCES dbo.users(id);
GO
IF COL_LENGTH('dbo.incidents', 'resolution_category') IS NULL
    ALTER TABLE dbo.incidents ADD resolution_category NVARCHAR(50) NULL;
GO
IF COL_LENGTH('dbo.incidents', 'resolution_note') IS NULL
    ALTER TABLE dbo.incidents ADD resolution_note NVARCHAR(1000) NULL;
GO
IF COL_LENGTH('dbo.incidents', 'reopened_count') IS NULL
    ALTER TABLE dbo.incidents ADD reopened_count INT NOT NULL
        CONSTRAINT DF_incidents_reopened_count DEFAULT 0;
GO
