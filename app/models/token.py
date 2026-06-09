import uuid
from datetime import datetime, timezone
from app.extensions import db


class Token(db.Model):
    """Jeton JWT actif — accès et rafraîchissement.

    Chaque JWT émis possède un identifiant unique (jti).
    La révocation consiste à marquer le jeton revoked=True.
    """
    __tablename__ = 'tokens'

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jti = db.Column(db.UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid.uuid4)
    user_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token_type = db.Column(db.String(10), nullable=False)  # 'access' | 'refresh'
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked = db.Column(db.Boolean, default=False, nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', back_populates='tokens')

    def revoke(self):
        self.revoked = True
        self.revoked_at = datetime.now(timezone.utc)

    def is_active(self):
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return not self.revoked and datetime.now(timezone.utc) < expires
