-- =========================================================
-- 027_add_fr008_fr012_fr017_fr023.sql
-- Network and hardware telemetry, scheduled tasks, containers, clock skew,
-- capacity history, SLA targets, and site/tag grouping.
--
-- FR-008 asked for network, per-core and hardware metrics; FR-009 for
-- scheduled task and container checks; §19 for clock-skew detection and a
-- disk growth rate; FR-017 for SLA targets; FR-023 for grouping beyond a
-- single environment field.
--
-- Everything here is nullable or defaulted. A server running an older agent
-- simply reports none of it, and shows "Not available" rather than a zero.
-- Run after 001-026.
-- =========================================================

USE ApplicationMonitoringDB;
GO

-- FR-008 / FR-009 telemetry
IF COL_LENGTH('dbo.servers', 'network_interfaces_json') IS NULL
    ALTER TABLE dbo.servers ADD network_interfaces_json NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.servers', 'cpu_per_core_json') IS NULL
    ALTER TABLE dbo.servers ADD cpu_per_core_json NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.servers', 'hardware_json') IS NULL
    ALTER TABLE dbo.servers ADD hardware_json NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.servers', 'disk_volumes_json') IS NULL
    ALTER TABLE dbo.servers ADD disk_volumes_json NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.servers', 'scheduled_tasks_json') IS NULL
    ALTER TABLE dbo.servers ADD scheduled_tasks_json NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.servers', 'containers_json') IS NULL
    ALTER TABLE dbo.servers ADD containers_json NVARCHAR(MAX) NULL;
GO

-- §19 clock incorrect
IF COL_LENGTH('dbo.servers', 'clock_skew_seconds') IS NULL
    ALTER TABLE dbo.servers ADD clock_skew_seconds INT NULL;
GO

-- FR-023 grouping
IF COL_LENGTH('dbo.servers', 'site') IS NULL
    ALTER TABLE dbo.servers ADD site VARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.servers', 'tags_json') IS NULL
    ALTER TABLE dbo.servers ADD tags_json NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.applications', 'site') IS NULL
    ALTER TABLE dbo.applications ADD site VARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.applications', 'tags_json') IS NULL
    ALTER TABLE dbo.applications ADD tags_json NVARCHAR(MAX) NULL;
GO

-- FR-017 SLA target. Nullable on purpose: no target is different from 99.9%,
-- and reports must say so rather than mark everyone against an invented one.
IF COL_LENGTH('dbo.applications', 'sla_target_percent') IS NULL
    ALTER TABLE dbo.applications ADD sla_target_percent FLOAT NULL;
GO

-- §8 growth trend / §19 disk fills rapidly
IF OBJECT_ID('dbo.server_metrics', 'U') IS NULL
    CREATE TABLE dbo.server_metrics (
        id            INT IDENTITY(1,1) PRIMARY KEY,
        server_id     INT       NOT NULL FOREIGN KEY REFERENCES dbo.servers(id),
        recorded_at   DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        disk_percent  FLOAT     NULL,
        disk_total_gb FLOAT     NULL
    );
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_server_metrics_server_time')
    CREATE INDEX IX_server_metrics_server_time
        ON dbo.server_metrics(server_id, recorded_at);
GO

PRINT '027_add_fr008_fr012_fr017_fr023.sql applied.';
GO
