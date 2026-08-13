from datetime import datetime, timezone

from app.extensions import db, bcrypt

ROLES = ("ADMIN", "MANAGER", "VIEWER")


class User(db.Model):
    """Database model for a system user (admin, manager, or viewer)."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="VIEWER")
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
