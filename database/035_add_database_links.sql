-- What each application on a server is actually connected to (FR-011, §8).
--
-- A configuration file says which database an application was pointed at. The
-- socket table says which one it is talking to now, and when the two disagree
-- it is the socket that is right. Discovered by the agent from its own machine,
-- read-only: no connection is made and no credential is ever seen.
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.servers') AND name = 'database_links_json')
BEGIN
    ALTER TABLE dbo.servers ADD database_links_json NVARCHAR(MAX) NULL;
END
GO
