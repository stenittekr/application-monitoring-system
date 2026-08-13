"""One-off local dev seeding, mirroring database/004_create_seed_data.sql for the
SQLite dev DB. Not part of the app - safe to delete once you're on real SQL Server."""
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.application import Application
from app.models.system_setting import SystemSetting

app = create_app()
with app.app_context():
    db.create_all()

    if not User.query.filter_by(email="admin@example.com").first():
        admin = User(name="System Admin", email="admin@example.com", role="ADMIN")
        admin.set_password("Admin@123")
        db.session.add(admin)

    if not User.query.filter_by(email="manager@example.com").first():
        manager = User(name="Jane Manager", email="manager@example.com", role="MANAGER")
        manager.set_password("Manager@123")
        db.session.add(manager)

    if not User.query.filter_by(email="viewer@example.com").first():
        viewer = User(name="Vince Viewer", email="viewer@example.com", role="VIEWER")
        viewer.set_password("Viewer@123")
        db.session.add(viewer)

    if not Application.query.filter_by(name="Example Public Website").first():
        db.session.add(Application(
            name="Example Public Website", description="Sample production website used for demo monitoring.",
            url="https://example.com", environment="Production",
            owner_name="Jane Manager", owner_email="manager@example.com",
            manager_name="Jane Manager", manager_email="manager@example.com",
            monitoring_enabled=True, monitoring_interval=60, timeout=10,
            retry_count=3, retry_delay=5, expected_status_code=200, current_status="UNKNOWN",
        ))

    if not Application.query.filter_by(name="Example Internal API").first():
        db.session.add(Application(
            name="Example Internal API", description="Sample internal REST API used for demo monitoring.",
            url="https://httpbin.org/status/200", environment="Production",
            owner_name="System Admin", owner_email="admin@example.com",
            manager_name="Jane Manager", manager_email="manager@example.com",
            monitoring_enabled=True, monitoring_interval=120, timeout=10,
            retry_count=3, retry_delay=5, expected_status_code=200, current_status="UNKNOWN",
        ))

    if not Application.query.filter_by(name="Example Staging App").first():
        db.session.add(Application(
            name="Example Staging App", description="Sample staging environment app, monitoring disabled by default.",
            url="https://example.org", environment="Staging",
            owner_name="Jane Manager", owner_email="manager@example.com",
            manager_name="System Admin", manager_email="admin@example.com",
            monitoring_enabled=False, monitoring_interval=300, timeout=10,
            retry_count=3, retry_delay=5, expected_status_code=200, current_status="DISABLED",
        ))

    if not Application.query.filter_by(name="Example Database Server").first():
        db.session.add(Application(
            name="Example Database Server", description="Sample TCP port check (e.g. a database listener).",
            server="example.com", port=443, health_check_type="TCP", environment="Production",
            owner_name="System Admin", owner_email="admin@example.com",
            manager_name="Jane Manager", manager_email="manager@example.com",
            monitoring_enabled=True, monitoring_interval=60, timeout=10,
            retry_count=3, retry_delay=5, expected_status_code=200, current_status="UNKNOWN",
        ))

    defaults = {
        "reminder_notifications_enabled": "true",
        "reminder_interval_minutes": "60",
        "smtp_host": "smtp.office365.com",
        "smtp_port": "587",
        "smtp_use_tls": "true",
        "smtp_username": "notification@awgtc.com",
        "smtp_password": "",
        "email_from": "notification@awgtc.com",
    }
    for key, value in defaults.items():
        if not SystemSetting.query.filter_by(setting_key=key).first():
            db.session.add(SystemSetting(setting_key=key, setting_value=value))

    db.session.commit()
    print("Seed complete: 3 users, 3 applications, settings.")
