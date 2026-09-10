-- Disk throughput and IIS sites/application pools (§7.1 I/O, §7.2 discovery).
--
-- Disk busy time is the metric that explains an outage nobody else can: every
-- application slow, while CPU, RAM and free space all read healthy. A stopped
-- IIS application pool is the same kind of invisible - the service runs, the
-- port listens, and one site answers 503.
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.servers') AND name = 'disk_io_json')
BEGIN
    ALTER TABLE dbo.servers ADD disk_io_json NVARCHAR(MAX) NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.servers') AND name = 'web_sites_json')
BEGIN
    ALTER TABLE dbo.servers ADD web_sites_json NVARCHAR(MAX) NULL;
END
GO
