-- =========================================================
-- 017_add_server_identity.sql
-- §7.2 server identity: OS edition, architecture, domain/workgroup, CPU model
-- and every routable IP address. Collected on every heartbeat by agent v0.5.0+
-- rather than only at enrolment, so an upgraded, renamed or re-addressed
-- machine stops reporting whatever was true on the day it enrolled.
-- Run after 001-016.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'os_edition') IS NULL
    ALTER TABLE dbo.servers ADD os_edition NVARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.servers', 'os_architecture') IS NULL
    ALTER TABLE dbo.servers ADD os_architecture NVARCHAR(40) NULL;
GO
IF COL_LENGTH('dbo.servers', 'domain') IS NULL
    ALTER TABLE dbo.servers ADD domain NVARCHAR(150) NULL;
GO
IF COL_LENGTH('dbo.servers', 'cpu_model') IS NULL
    ALTER TABLE dbo.servers ADD cpu_model NVARCHAR(200) NULL;
GO
IF COL_LENGTH('dbo.servers', 'ip_addresses_json') IS NULL
    ALTER TABLE dbo.servers ADD ip_addresses_json NVARCHAR(MAX) NULL;
GO
