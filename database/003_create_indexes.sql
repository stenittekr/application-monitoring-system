-- =========================================================
-- 003_create_indexes.sql
-- Indexes supporting the monitoring engine, dashboard and reports.
-- Run after 002_create_tables.sql.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_applications_current_status')
    CREATE INDEX IX_applications_current_status ON dbo.applications(current_status);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_applications_monitoring_enabled')
    CREATE INDEX IX_applications_monitoring_enabled ON dbo.applications(monitoring_enabled);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_applications_deleted_at')
    CREATE INDEX IX_applications_deleted_at ON dbo.applications(deleted_at);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_health_checks_application_id')
    CREATE INDEX IX_health_checks_application_id ON dbo.health_checks(application_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_health_checks_checked_at')
    CREATE INDEX IX_health_checks_checked_at ON dbo.health_checks(checked_at);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_incidents_application_id')
    CREATE INDEX IX_incidents_application_id ON dbo.incidents(application_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_incidents_server_id')
    CREATE INDEX IX_incidents_server_id ON dbo.incidents(server_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_incidents_status')
    CREATE INDEX IX_incidents_status ON dbo.incidents(status);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_servers_current_status')
    CREATE INDEX IX_servers_current_status ON dbo.servers(current_status);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_servers_deleted_at')
    CREATE INDEX IX_servers_deleted_at ON dbo.servers(deleted_at);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_activity_logs_created_at')
    CREATE INDEX IX_activity_logs_created_at ON dbo.activity_logs(created_at);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_notifications_status')
    CREATE INDEX IX_notifications_status ON dbo.notifications(status);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_notifications_incident_id')
    CREATE INDEX IX_notifications_incident_id ON dbo.notifications(incident_id);
GO
