from datetime import datetime, timezone

from app.extensions import db, bcrypt

# Matches Section 4 (Users and Roles) of the platform requirements doc:
#   ADMIN       - Platform Administrator: full configuration/enrollment/users/security/audit access
#   IT_MANAGER  - views everything, approves maintenance/profiles/reports, manages incidents fleet-wide
#   APP_OWNER   - restricted to their own applications (owner_email/manager_email match); acknowledges own incidents
#   OPERATOR    - IT Support: monitors everything, acknowledges incidents, runs on-demand diagnostics
#   AUDITOR     - Auditor/Management: read-only across dashboards, reports, and the audit trail
ROLES = ("ADMIN", "IT_MANAGER", "APP_OWNER", "OPERATOR", "AUDITOR")


class User(db.Model):
    """Database model for a system user (one of the five roles in ROLES above)."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="AUDITOR")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_login_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, plain_password):
        """Hashes and stores the given plain-text password."""
        self.password_hash = bcrypt.generate_password_hash(plain_password).decode("utf-8")

    def check_password(self, plain_password):
        """Checks whether the given plain-text password matches the stored hash."""
        return bcrypt.check_password_hash(self.password_hash, plain_password)

    def to_dict(self):
        """Serializes the user into a JSON-friendly dict, excluding the password hash."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }
