import uuid
from datetime import datetime, timezone
from app.extensions import db


class Company(db.Model):
    __tablename__ = 'companies'

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    activity = db.Column(db.String(200), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    phones = db.Column(db.JSON, nullable=False, default=list)
    currency = db.Column(db.String(10), nullable=False, default='FCFA')
    logo_url = db.Column(db.String(500), nullable=True)
    # Texte de localisation affiché dans le pied de page.
    location = db.Column(db.String(300), nullable=True)
    # URL du modèle Word (.docx) utilisé pour générer les PDF de devis.
    template_docx_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship('User', back_populates='company')
    signatures = db.relationship(
        'Signature', back_populates='company', lazy='dynamic',
        cascade='all, delete-orphan', order_by='Signature.order_index',
    )
    clients = db.relationship('Client', back_populates='company', lazy='dynamic', cascade='all, delete-orphan')
    products = db.relationship('Product', back_populates='company', lazy='dynamic', cascade='all, delete-orphan')
    quotes = db.relationship('Quote', back_populates='company', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self, include_signatures=False):
        data = {
            'id': str(self.id),
            'name': self.name,
            'activity': self.activity,
            'address': self.address,
            'city': self.city,
            'phones': self.phones or [],
            'currency': self.currency,
            'logo_url': self.logo_url,
            'location': self.location,
            'template_docx_url': self.template_docx_url,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
        if include_signatures:
            data['signatures'] = [s.to_dict() for s in self.signatures]
        return data


class Signature(db.Model):
    __tablename__ = 'signatures'

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    label = db.Column(db.String(100), nullable=False)
    text = db.Column(db.Text, nullable=False)
    order_index = db.Column(db.Integer, nullable=False, default=0)

    company = db.relationship('Company', back_populates='signatures')

    def to_dict(self):
        return {
            'id': str(self.id),
            'label': self.label,
            'text': self.text,
            'order_index': self.order_index,
        }
