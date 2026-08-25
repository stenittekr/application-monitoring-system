-- =========================================================
-- 006_add_notification_body.sql
-- Stores the rendered email body on the notification row. Needed because a
-- notification can now be delivered later than it was created - held over a
-- quiet day (weekends), or retried after an SMTP outage - and the retry sweep
-- previously sent a "(retry) See original alert details." placeholder instead
-- of the real alert. Run after 001-005.
-- =========================================================

USE ApplicationMonitoringDB;
GO

IF COL_LENGTH('dbo.notifications', 'body') IS NULL
BEGIN
    ALTER TABLE dbo.notifications ADD body NVARCHAR(MAX) NULL;
END
GO

-- The held-over-the-weekend rows are found by status = 'PENDING', which the
-- existing notifications index already covers - no new index needed.
