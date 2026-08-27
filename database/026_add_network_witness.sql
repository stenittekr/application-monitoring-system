-- =========================================================
-- 026_add_network_witness.sql
-- A server whose agent proves we can still see a target's network.
--
-- On three consecutive evenings the monitoring laptop left the office and
-- every internal target timed out at exactly ten seconds while every public
-- one answered in under two. The applications with a recorded host were
-- correctly held back as UNKNOWN; the two database checks had no host - the
-- SQL Server is on a machine we do not monitor - so they alerted as outages
-- for systems that were running perfectly.
--
-- A witness is not a host. The database at 162.20.20.250 does not run on
-- PS_QAS. But both are reachable only from the office network, so a live
-- heartbeat from PS_QAS is evidence that a failed database check means the
-- database, and a silent one means we cannot see that network at all.
--
-- Nullable, so an application without one alerts exactly as before.
-- Run after 001-025.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.applications', 'network_witness_server_id') IS NULL
    ALTER TABLE dbo.applications ADD network_witness_server_id INT NULL
        CONSTRAINT FK_applications_network_witness REFERENCES dbo.servers(id);
GO

PRINT '026_add_network_witness.sql applied.';
GO
