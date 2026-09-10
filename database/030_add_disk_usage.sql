-- =========================================================
-- 030_add_disk_usage.sql
-- What is actually consuming each volume.
--
-- On 31 August a server sat at 88% with 25 GB left and nothing could say what
-- was on it. The platform could report that a disk was nearly full and not one
-- thing about why, which left the only answer as logging in and running
-- commands by hand - exactly what a monitoring platform exists to avoid.
--
-- §8 asks for a storage growth trend. A trend says when; this says what.
-- Run after 001-029.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'disk_usage_json') IS NULL
    ALTER TABLE dbo.servers ADD disk_usage_json NVARCHAR(MAX) NULL;
GO

PRINT '030_add_disk_usage.sql applied.';
GO
