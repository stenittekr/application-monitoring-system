-- =========================================================
-- 020_add_application_host.sql
-- Links an application to the server it runs on, so that server's agent can
-- corroborate a failed check. Heartbeats travel the same network path in
-- reverse: a live agent proves the path works and the application is at fault,
-- while both failing means the monitor cannot see that host and blaming the
-- application would be a guess (§19 "agent stopped but server alive").
-- Run after 001-019.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.applications', 'hosted_on_server_id') IS NULL
    ALTER TABLE dbo.applications ADD hosted_on_server_id INT NULL
        CONSTRAINT FK_applications_hosted_on FOREIGN KEY REFERENCES dbo.servers(id);
GO
