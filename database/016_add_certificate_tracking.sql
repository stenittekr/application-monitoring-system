-- =========================================================
-- 016_add_certificate_tracking.sql
-- TLS certificate expiry for HTTPS applications (§8 security posture,
-- §12.1 expiring certificates, §19 "credential expires"). Refreshed once a
-- day rather than per check - it is a date that moves once a year.
-- Run after 001-015.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.applications', 'cert_expires_at') IS NULL
    ALTER TABLE dbo.applications ADD cert_expires_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.applications', 'cert_issuer') IS NULL
    ALTER TABLE dbo.applications ADD cert_issuer NVARCHAR(300) NULL;
GO
IF COL_LENGTH('dbo.applications', 'cert_checked_at') IS NULL
    ALTER TABLE dbo.applications ADD cert_checked_at DATETIME2 NULL;
GO
