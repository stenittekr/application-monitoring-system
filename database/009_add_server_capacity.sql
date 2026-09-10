-- =========================================================
-- 009_add_server_capacity.sql
-- Adds the capacities behind the CPU/RAM/disk percentages reported by agent
-- v0.4.0+, so "61% RAM" can be read as "61% of 16 GB". A percentage alone is
-- not actionable: 61% of 4 GB and 61% of 128 GB are different problems.
-- Run after 001-008.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'cpu_cores') IS NULL
    ALTER TABLE dbo.servers ADD cpu_cores INT NULL;
GO
IF COL_LENGTH('dbo.servers', 'ram_total_mb') IS NULL
    ALTER TABLE dbo.servers ADD ram_total_mb INT NULL;
GO
IF COL_LENGTH('dbo.servers', 'disk_total_gb') IS NULL
    ALTER TABLE dbo.servers ADD disk_total_gb FLOAT NULL;
GO
