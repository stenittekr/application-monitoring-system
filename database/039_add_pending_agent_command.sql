-- What an admin has asked a server's agent to do, applied on its next
-- check-in (RESTART or UPDATE) - the alternative to running a command on
-- every machine in a 200+ PC fleet by hand.
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.servers') AND name = 'pending_agent_command')
BEGIN
    ALTER TABLE dbo.servers ADD pending_agent_command NVARCHAR(20) NULL;
END
GO
