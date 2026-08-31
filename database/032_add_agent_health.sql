-- =========================================================
-- 032_add_agent_health.sql
-- What the agent reports about itself (§7.1).
--
-- Everything else the agent sends describes the machine. Without this, the one
-- component nobody watches is the one doing the watching - and a silently
-- degrading agent looks exactly like a healthy one until it stops.
--
-- Queue depth is the useful signal: it grows when the platform cannot be
-- reached, so a queue that never drains means heartbeats are being kept rather
-- than delivered, even while the last one that got through looks fine.
-- Run after 001-031.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.servers', 'agent_health_json') IS NULL
    ALTER TABLE dbo.servers ADD agent_health_json NVARCHAR(MAX) NULL;
GO

PRINT '032_add_agent_health.sql applied.';
GO
