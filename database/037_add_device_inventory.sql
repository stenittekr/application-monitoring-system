-- Asset identity per machine (§7.2 discovery and inventory).
--
-- What Windows shows under Settings > System > About: device name and FQDN,
-- Device ID, Product ID, manufacturer, model, BIOS, serial number, CPU, RAM.
-- Held so an estate of 200 PCs can be inventoried from the platform rather
-- than by walking to each machine and reading its screen.
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.servers') AND name = 'device_inventory_json')
BEGIN
    ALTER TABLE dbo.servers ADD device_inventory_json NVARCHAR(MAX) NULL;
END
GO
