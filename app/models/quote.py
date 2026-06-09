import uuid
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db


class Quote(db.Model):
    __tablename__ = 'quotes'

    STATUS_DRAFT = 'draft'
    STATUS_SENT = 'sent'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    VALID_STATUSES = {STATUS_DRAFT, STATUS_SENT, STATUS_ACCEPTED, STATUS_REJECTED}

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    client_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('clients.id', ondelete='SET NULL'), nullable=True, index=True)
    number = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_DRAFT, index=True)
    validity_days = db.Column(db.Integer, nullable=False, default=30)
    notes = db.Column(db.Text, nullable=True)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    share_token = db.Column(db.UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4, index=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    company = db.relationship('Company', back_populates='quotes')
    client = db.relationship('Client', back_populates='quotes')
    items = db.relationship(
        'QuoteItem', back_populates='quote', lazy='joined',
        cascade='all, delete-orphan', order_by='QuoteItem.order_index',
    )

    def recompute_totals(self):
        self.subtotal = sum(item.total for item in self.items)
        self.tax_amount = self.subtotal * (self.tax_rate / Decimal('100'))
        self.total = self.subtotal + self.tax_amount

    def to_dict(self, include_items=True):
        data = {
            'id': str(self.id),
            'number': self.number,
            'title': self.title,
            'status': self.status,
            'validity_days': self.validity_days,
            'notes': self.notes,
            'subtotal': float(self.subtotal),
            'tax_rate': float(self.tax_rate),
            'tax_amount': float(self.tax_amount),
            'total': float(self.total),
            'share_token': str(self.share_token),
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'client': self.client.to_dict() if self.client else None,
        }
        if include_items:
            data['items'] = [i.to_dict() for i in self.items]
        return data


class QuoteItem(db.Model):
    __tablename__ = 'quote_items'

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('quotes.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('products.id', ondelete='SET NULL'), nullable=True)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(10, 3), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    unit = db.Column(db.String(50), nullable=True)
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    order_index = db.Column(db.Integer, nullable=False, default=0)

    quote = db.relationship('Quote', back_populates='items')

    def compute_total(self):
        self.total = self.quantity * self.unit_price

    def to_dict(self):
        return {
            'id': str(self.id),
            'product_id': str(self.product_id) if self.product_id else None,
            'description': self.description,
            'quantity': float(self.quantity),
            'unit_price': float(self.unit_price),
            'unit': self.unit,
            'total': float(self.total),
            'order_index': self.order_index,
        }
