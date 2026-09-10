-- DNS, gateway and platform reachability as the agent sees them (§8 network).
--
-- Separates three failures that look identical from a dashboard: the name does
-- not resolve, the gateway is unreachable, or the path to the platform is
-- lossy. Each has a different owner.
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.servers') AND name = 'reachability_json')
BEGIN
    ALTER TABLE dbo.servers ADD reachability_json NVARCHAR(MAX) NULL;
END
GO
