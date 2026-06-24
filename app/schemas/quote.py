from marshmallow import Schema, fields, validate


class QuoteItemSchema(Schema):
    id = fields.UUID(required=False, load_default=None)
    product_id = fields.UUID(required=False, allow_none=True, load_default=None)
    description = fields.Str(required=True, validate=validate.Length(min=1, max=500))
    quantity = fields.Decimal(required=True, places=3, as_string=False)
    unit_price = fields.Decimal(required=True, places=2, as_string=False)
    unit = fields.Str(required=False, allow_none=True, load_default=None)
    order_index = fields.Int(required=False, load_default=0)


class QuoteCreateSchema(Schema):
    # id + number fournis par l'app (offline-first) → création idempotente au rejeu.
    id = fields.UUID(required=False, allow_none=True, load_default=None)
    number = fields.Str(required=False, allow_none=True, load_default=None, validate=validate.Length(min=1, max=30))
    title = fields.Str(required=True, validate=validate.Length(min=1, max=300))
    client_id = fields.UUID(required=False, allow_none=True, load_default=None)
    validity_days = fields.Int(required=False, load_default=30, validate=validate.Range(min=1, max=365))
    notes = fields.Str(required=False, allow_none=True, load_default=None)
    tax_rate = fields.Decimal(required=False, places=2, load_default=0)
    # Snapshot du devis riche (sections/rubriques) pour la vue publique fidèle.
    document_json = fields.Raw(required=False, allow_none=True, load_default=None)
    items = fields.List(fields.Nested(QuoteItemSchema), required=True, validate=validate.Length(min=1))


class QuoteUpdateSchema(Schema):
    title = fields.Str(required=False, validate=validate.Length(min=1, max=300))
    client_id = fields.UUID(required=False, allow_none=True)
    validity_days = fields.Int(required=False, validate=validate.Range(min=1, max=365))
    notes = fields.Str(required=False, allow_none=True)
    tax_rate = fields.Decimal(required=False, places=2)
    document_json = fields.Raw(required=False, allow_none=True)
    items = fields.List(fields.Nested(QuoteItemSchema), required=False)


class QuoteStatusSchema(Schema):
    status = fields.Str(required=True, validate=validate.OneOf(['draft', 'sent', 'accepted', 'rejected']))
