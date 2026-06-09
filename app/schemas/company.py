from marshmallow import Schema, fields, validate


class CompanySchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    activity = fields.Str(required=False, allow_none=True, load_default=None)
    address = fields.Str(required=False, allow_none=True, load_default=None)
    city = fields.Str(required=False, allow_none=True, load_default=None)
    phones = fields.List(fields.Str(), required=False, load_default=[])
    currency = fields.Str(required=False, load_default='FCFA', validate=validate.Length(max=10))
    logo_url = fields.Str(required=False, allow_none=True, load_default=None)
    header_image_url = fields.Str(required=False, allow_none=True, load_default=None)
    footer_image_url = fields.Str(required=False, allow_none=True, load_default=None)
    location = fields.Str(required=False, allow_none=True, load_default=None, validate=validate.Length(max=300))


class SignatureSchema(Schema):
    label = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    text = fields.Str(required=True, validate=validate.Length(min=1))
    order_index = fields.Int(required=False, load_default=0)
