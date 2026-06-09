from marshmallow import Schema, fields, validate


class ProductSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    description = fields.Str(required=False, allow_none=True, load_default=None)
    unit = fields.Str(required=False, allow_none=True, load_default=None, validate=validate.Length(max=50))
    unit_price = fields.Decimal(required=True, places=2, as_string=False)
