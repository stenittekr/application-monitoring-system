-- =========================================================
-- 002_create_tables.sql
-- Creates all tables for the Application Monitoring System.
-- Run after 001_create_database.sql, connected to ApplicationMonitoringDB.
-- =========================================================

USE ApplicationMonitoringDB;
GO

-- -----------------------------------------------------------
-- users: application accounts (ADMIN / MANAGER / VIEWER)
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.users', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.users (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        name            NVARCHAR(150)   NOT NULL,
        email           NVARCHAR(255)   NOT NULL UNIQUE,
        password_hash   NVARCHAR(255)   NOT NULL,
        role            VARCHAR(20)     NOT NULL CHECK (role IN ('ADMIN','IT_MANAGER','APP_OWNER','OPERATOR','AUDITOR')),
        is_active       BIT             NOT NULL DEFAULT 1,
        created_at      DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
        last_login_at   DATETIME2       NULL
    );
END
GO

-- -----------------------------------------------------------
-- applications: monitored company applications
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.applications', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.applications (
        id                          INT IDENTITY(1,1) PRIMARY KEY,
        name                        NVARCHAR(200)  NOT NULL,
        description                 NVARCHAR(1000) NULL,
        url                         NVARCHAR(1000) NULL,  -- required for HTTP/HTTPS checks
        server                      NVARCHAR(255)  NULL,  -- required for TCP checks
        port                        INT            NULL,  -- required for TCP checks
        health_check_type           VARCHAR(10)    NOT NULL DEFAULT 'HTTP'
                                       CHECK (health_check_type IN ('HTTP','HTTPS','TCP')),
        environment                 VARCHAR(50)    NOT NULL DEFAULT 'Production',
        owner_name                  NVARCHAR(150)  NOT NULL,
        owner_email                 NVARCHAR(255)  NOT NULL,
        manager_name                NVARCHAR(150)  NOT NULL,
        manager_email               NVARCHAR(255)  NOT NULL,

        monitoring_enabled          BIT            NOT NULL DEFAULT 1,
        monitoring_interval         INT            NOT NULL DEFAULT 300,  -- seconds
        timeout                     INT            NOT NULL DEFAULT 10,   -- seconds
        retry_count                 INT            NOT NULL DEFAULT 3,
        retry_delay                 INT            NOT NULL DEFAULT 5,    -- seconds
        expected_status_code        INT            NOT NULL DEFAULT 200,
        verify_ssl                  BIT            NOT NULL DEFAULT 1,
        department                  NVARCHAR(100)  NULL,
        icon                        VARCHAR(50)    NULL,  -- bootstrap-icons class, e.g. 'bi-people'

        current_status              VARCHAR(20)    NOT NULL DEFAULT 'UNKNOWN'
                                       CHECK (current_status IN ('UP','DOWN','DEGRADED','UNKNOWN','DISABLED')),

        last_checked_at             DATETIME2      NULL,
        last_successful_check_at    DATETIME2      NULL,
        last_failed_check_at        DATETIME2      NULL,

        created_at                  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at                  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        deleted_at                  DATETIME2      NULL
    );
END
GO

-- -----------------------------------------------------------
-- health_checks: individual health-check attempts
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.health_checks', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.health_checks (
        id                  BIGINT IDENTITY(1,1) PRIMARY KEY,
        application_id      INT            NOT NULL,
        checked_at          DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        status              VARCHAR(20)    NOT NULL CHECK (status IN ('UP','DOWN','DEGRADED')),
        http_status_code    INT            NULL,
        response_time       FLOAT          NULL,  -- milliseconds
        success             BIT            NOT NULL,
        error_message       NVARCHAR(1000) NULL,
        attempt_number      INT            NOT NULL DEFAULT 1,
        CONSTRAINT FK_health_checks_application FOREIGN KEY (application_id)
            REFERENCES dbo.applications(id)
    );
END
GO

-- -----------------------------------------------------------
-- servers: enrolled agents/servers being monitored via heartbeat
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.servers', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.servers (
        id                          INT IDENTITY(1,1) PRIMARY KEY,
        hostname                    NVARCHAR(255)  NOT NULL,
        ip_address                  VARCHAR(64)    NULL,
        os_name                     NVARCHAR(100)  NULL,
        os_version                  NVARCHAR(255)  NULL,
        agent_version               VARCHAR(50)    NULL,

        token_hash                  CHAR(64)       NOT NULL,  -- sha256 hex digest of the agent's secret

        owner_name                  NVARCHAR(150)  NULL,
        owner_email                 NVARCHAR(255)  NULL,

        heartbeat_interval_seconds  INT            NOT NULL DEFAULT 60,
        current_status              VARCHAR(20)    NOT NULL DEFAULT 'UNKNOWN'
                                       CHECK (current_status IN ('UP','DOWN','UNKNOWN')),

        cpu_percent                 FLOAT          NULL,
        ram_percent                 FLOAT          NULL,
        disk_percent                FLOAT          NULL,
        uptime_seconds              INT            NULL,

        last_heartbeat_at           DATETIME2      NULL,
        last_boot_at                DATETIME2      NULL,

        discovered_services_json    NVARCHAR(MAX)  NULL,
        discovered_ports_json       NVARCHAR(MAX)  NULL,

        created_at                  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at                  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        deleted_at                  DATETIME2      NULL
    );
END
GO

-- -----------------------------------------------------------
-- incidents: confirmed outages (one active incident per app/server)
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.incidents', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.incidents (
        id                          INT IDENTITY(1,1) PRIMARY KEY,
        application_id              INT            NULL,  -- exactly one of application_id/server_id is set
        server_id                   INT            NULL,

        status                      VARCHAR(20)    NOT NULL DEFAULT 'OPEN'
                                       CHECK (status IN ('OPEN','RESOLVED')),

        started_at                  DATETIME2      NOT NULL,
        detected_at                 DATETIME2      NOT NULL,
        resolved_at                 DATETIME2      NULL,

        duration_seconds            INT            NULL,

        reason                      NVARCHAR(500)  NULL,
        http_status_code            INT            NULL,
        error_message               NVARCHAR(1000) NULL,

        notification_sent           BIT            NOT NULL DEFAULT 0,
        recovery_notification_sent  BIT            NOT NULL DEFAULT 0,

        acknowledged_at             DATETIME2      NULL,
        acknowledged_by_id          INT            NULL,
        assigned_to_id              INT            NULL,
        escalated_at                DATETIME2      NULL,

        created_at                  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at                  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_incidents_application FOREIGN KEY (application_id)
            REFERENCES dbo.applications(id),
        CONSTRAINT FK_incidents_server FOREIGN KEY (server_id)
            REFERENCES dbo.servers(id),
        CONSTRAINT FK_incidents_acknowledged_by FOREIGN KEY (acknowledged_by_id)
            REFERENCES dbo.users(id),
        CONSTRAINT FK_incidents_assigned_to FOREIGN KEY (assigned_to_id)
            REFERENCES dbo.users(id)
    );
END
GO

-- -----------------------------------------------------------
-- notifications: emails sent for incidents
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.notifications', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.notifications (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        incident_id         INT            NOT NULL,
        application_id      INT            NULL,  -- exactly one of application_id/server_id is set
        server_id           INT            NULL,

        notification_type   VARCHAR(20)    NOT NULL CHECK (notification_type IN ('DOWN','RECOVERY','REMINDER','ESCALATION')),

        recipient           NVARCHAR(255)  NOT NULL,
        cc                  NVARCHAR(255)  NULL,

        subject             NVARCHAR(500)  NOT NULL,

        status              VARCHAR(20)    NOT NULL DEFAULT 'PENDING'
                                       CHECK (status IN ('PENDING','SENT','FAILED')),

        sent_at             DATETIME2      NULL,
        error_message       NVARCHAR(1000) NULL,
        retry_count         INT            NOT NULL DEFAULT 0,

        created_at          DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_notifications_incident FOREIGN KEY (incident_id)
            REFERENCES dbo.incidents(id),
        CONSTRAINT FK_notifications_application FOREIGN KEY (application_id)
            REFERENCES dbo.applications(id),
        CONSTRAINT FK_notifications_server FOREIGN KEY (server_id)
            REFERENCES dbo.servers(id)
    );
END
GO

-- -----------------------------------------------------------
-- activity_logs: audit trail
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.activity_logs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.activity_logs (
        id              BIGINT IDENTITY(1,1) PRIMARY KEY,
        user_id         INT            NULL,

        action          VARCHAR(100)   NOT NULL,

        entity_type     VARCHAR(50)    NULL,
        entity_id       INT            NULL,

        description     NVARCHAR(1000) NULL,

        ip_address      VARCHAR(50)    NULL,
        metadata        NVARCHAR(MAX)  NULL,  -- JSON text

        created_at      DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_activity_logs_user FOREIGN KEY (user_id)
            REFERENCES dbo.users(id)
    );
END
GO

-- -----------------------------------------------------------
-- maintenance_windows: planned outages that suppress incidents/alerts
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.maintenance_windows', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.maintenance_windows (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        application_id  INT            NULL,  -- NULL = applies to all applications
        starts_at       DATETIME2      NOT NULL,
        ends_at         DATETIME2      NOT NULL,
        reason          NVARCHAR(500)  NULL,
        created_by      INT            NULL,
        created_at      DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_maintenance_windows_application FOREIGN KEY (application_id)
            REFERENCES dbo.applications(id),
        CONSTRAINT FK_maintenance_windows_user FOREIGN KEY (created_by)
            REFERENCES dbo.users(id)
    );
END
GO

-- -----------------------------------------------------------
-- system_settings: key/value application settings
-- -----------------------------------------------------------
IF OBJECT_ID('dbo.system_settings', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.system_settings (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        setting_key     VARCHAR(100)   NOT NULL UNIQUE,
        setting_value   NVARCHAR(1000) NULL,
        updated_at      DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_by      INT            NULL,
        CONSTRAINT FK_system_settings_user FOREIGN KEY (updated_by)
            REFERENCES dbo.users(id)
    );
END
GO
