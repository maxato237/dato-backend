from marshmallow import Schema, fields, validate


class ClientSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    phone = fields.Str(required=False, allow_none=True, load_default=None)
    email = fields.Email(required=False, allow_none=True, load_default=None)
    address = fields.Str(required=False, allow_none=True, load_default=None)
