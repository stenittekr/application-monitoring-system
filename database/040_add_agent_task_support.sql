-- Phase 1 of on-demand remote support: a screenshot on request, and small,
-- specific tasks (starting with restarting one named service) - not an open
-- "run any command" channel, which would be a different, much larger risk.
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.servers') AND name = 'pending_agent_command_params_json')
BEGIN
    ALTER TABLE dbo.servers ADD pending_agent_command_params_json NVARCHAR(MAX) NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.servers') AND name = 'last_screenshot_at')
BEGIN
    ALTER TABLE dbo.servers ADD last_screenshot_at DATETIME2 NULL;
END
GO
