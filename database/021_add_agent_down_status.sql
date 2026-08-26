-- =========================================================
-- 021_add_agent_down_status.sql
-- Adds AGENT_DOWN to the server status vocabulary.
--
-- A missed heartbeat previously meant only one thing: DOWN. But an agent going
-- quiet on a machine whose applications are still answering is a different
-- fault with a different fix - DOWN means go and look at the server,
-- AGENT_DOWN means go and look at the agent. Collapsing the two teaches people
-- to ignore the alert that matters when the machine really does fall over.
--
-- The constraint is unnamed in 002, so it is located through sys.check_constraints
-- rather than dropped by name.
-- Run after 001-020.
-- =========================================================

USE ApplicationMonitoringDB;
GO

-- A CHECK constraint cannot be widened in place; drop and recreate it.
DECLARE @constraint SYSNAME =
    (SELECT TOP 1 cc.name
       FROM sys.check_constraints cc
       JOIN sys.columns c
         ON c.object_id = cc.parent_object_id
        AND c.column_id = cc.parent_column_id
      WHERE cc.parent_object_id = OBJECT_ID('dbo.servers')
        AND c.name = 'current_status');

IF @constraint IS NOT NULL
    EXEC('ALTER TABLE dbo.servers DROP CONSTRAINT ' + @constraint);
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_servers_current_status')
    ALTER TABLE dbo.servers ADD CONSTRAINT CK_servers_current_status
        CHECK (current_status IN ('UP','DOWN','UNKNOWN','AGENT_DOWN'));
GO

PRINT '021_add_agent_down_status.sql applied.';
GO
