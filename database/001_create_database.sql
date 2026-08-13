-- =========================================================
-- 001_create_database.sql
-- Creates the ApplicationMonitoringDB database.
-- Run this once as a user with CREATE DATABASE permission
-- (e.g. in SQL Server Management Studio, connected to master).
-- =========================================================

IF NOT EXISTS (SELECT 1 FROM sys.databases WHERE name = 'ApplicationMonitoringDB')
BEGIN
    CREATE DATABASE ApplicationMonitoringDB;
END
GO
