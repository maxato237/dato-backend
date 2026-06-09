import uuid
from datetime import datetime, timezone
from app.extensions import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tokens = db.relationship('Token', back_populates='user', lazy='dynamic', cascade='all, delete-orphan')
    otp_codes = db.relationship('OtpCode', back_populates='user', lazy='dynamic', cascade='all, delete-orphan')
    company = db.relationship('Company', back_populates='user', uselist=False, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': str(self.id),
            'phone': self.phone,
            'email': self.email,
            'name': self.name,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat(),
        }


class OtpCode(db.Model):
    __tablename__ = 'otp_codes'

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    purpose = db.Column(db.String(20), nullable=False)  # 'registration' | 'reset'
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', back_populates='otp_codes')

    def is_expired(self):
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        # SQLite retourne des datetimes naïfs ; on normalise pour comparer
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires
