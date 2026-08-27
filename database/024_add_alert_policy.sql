-- =========================================================
-- 024_add_alert_policy.sql
-- Severity, support hours and the daily digest (FR-014).
--
-- Every alert was the same alert: a disk at 82% reached the same people, the
-- same way, at the same hour, as a production outage. Sixty emails went out in
-- one week and most were not worth reading at 03:00.
--
-- Severity is derived and then stored on the incident, so a threshold changed
-- later cannot rewrite how urgent something was at the time.
--
-- Defaults keep today's behaviour except for LOW, which is what this exists to
-- quieten. Run after 001-023.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.incidents', 'severity') IS NULL
    ALTER TABLE dbo.incidents ADD severity VARCHAR(10) NULL;
GO

IF COL_LENGTH('dbo.applications', 'criticality') IS NULL
    ALTER TABLE dbo.applications ADD criticality VARCHAR(20) NULL;
GO

IF COL_LENGTH('dbo.applications', 'support_hours') IS NULL
    ALTER TABLE dbo.applications ADD support_hours VARCHAR(50) NULL;
GO

-- A held-back or policy-suppressed notification is neither sent nor failed.
DECLARE @constraint SYSNAME =
    (SELECT TOP 1 cc.name
       FROM sys.check_constraints cc
       JOIN sys.columns c
         ON c.object_id = cc.parent_object_id
        AND c.column_id = cc.parent_column_id
      WHERE cc.parent_object_id = OBJECT_ID('dbo.notifications')
        AND c.name = 'status');

IF @constraint IS NOT NULL
    EXEC('ALTER TABLE dbo.notifications DROP CONSTRAINT ' + @constraint);
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_notifications_status')
    ALTER TABLE dbo.notifications ADD CONSTRAINT CK_notifications_status
        CHECK (status IN ('PENDING','SENT','FAILED','DIGEST','SUPPRESSED'));
GO

-- DIGEST joins DOWN / RECOVERY / REMINDER / ESCALATION.
DECLARE @typeck SYSNAME =
    (SELECT TOP 1 cc.name
       FROM sys.check_constraints cc
       JOIN sys.columns c
         ON c.object_id = cc.parent_object_id
        AND c.column_id = cc.parent_column_id
      WHERE cc.parent_object_id = OBJECT_ID('dbo.notifications')
        AND c.name = 'notification_type');

IF @typeck IS NOT NULL
    EXEC('ALTER TABLE dbo.notifications DROP CONSTRAINT ' + @typeck);
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_notifications_type')
    ALTER TABLE dbo.notifications ADD CONSTRAINT CK_notifications_type
        CHECK (notification_type IN ('DOWN','RECOVERY','REMINDER','ESCALATION','DIGEST'));
GO

-- Routing defaults. Anything above LOW keeps arriving as it does today.
INSERT INTO dbo.system_settings (setting_key, setting_value)
SELECT v.k, v.v FROM (VALUES
    ('route_critical', 'EMAIL'),
    ('route_high',     'EMAIL'),
    ('route_medium',   'EMAIL'),
    ('route_low',      'DIGEST'),
    ('digest_hour',    '8'),
    ('default_support_hours', '24x7'),
    ('out_of_hours_minimum_severity', 'HIGH'),
    ('oncall_recipients', '')
) AS v(k, v)
WHERE NOT EXISTS (SELECT 1 FROM dbo.system_settings s WHERE s.setting_key = v.k);
GO

PRINT '024_add_alert_policy.sql applied.';
GO
