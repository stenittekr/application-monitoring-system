-- =========================================================
-- 015_add_server_changes.sql
-- FR-006 change detection. Discovery already collects services and installed
-- software on every heartbeat; the new snapshot simply overwrote the old one.
-- Diffing before the overwrite records additions, removals and version changes
-- with no extra collection. Run after 001-014.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF OBJECT_ID('dbo.server_changes', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.server_changes (
        id           INT IDENTITY(1,1) PRIMARY KEY,
        server_id    INT            NOT NULL,
        category     VARCHAR(20)    NOT NULL CHECK (category IN ('SERVICE','PROGRAM','PORT')),
        change_type  VARCHAR(20)    NOT NULL CHECK (change_type IN ('ADDED','REMOVED','CHANGED')),
        item_name    NVARCHAR(300)  NOT NULL,
        old_value    NVARCHAR(300)  NULL,
        new_value    NVARCHAR(300)  NULL,
        detected_at  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_server_changes_server FOREIGN KEY (server_id) REFERENCES dbo.servers(id)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_server_changes_server_detected')
    CREATE INDEX IX_server_changes_server_detected
        ON dbo.server_changes(server_id, detected_at DESC);
GO
