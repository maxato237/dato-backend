from marshmallow import EXCLUDE, Schema, fields, validate


class CompanySchema(Schema):
    class Meta:
        # Le client envoie aussi des réglages purement locaux (signature_left/
        # right, quote_prefix, quote_number_by_object) que le backend ne stocke
        # pas : on les ignore au lieu de rejeter tout le PUT en 422.
        unknown = EXCLUDE

    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    activity = fields.Str(required=False, allow_none=True, load_default=None)
    address = fields.Str(required=False, allow_none=True, load_default=None)
    city = fields.Str(required=False, allow_none=True, load_default=None)
    phones = fields.List(fields.Str(), required=False, load_default=[])
    currency = fields.Str(required=False, load_default='FCFA', validate=validate.Length(max=10))
    logo_url = fields.Str(required=False, allow_none=True, load_default=None)
    location = fields.Str(required=False, allow_none=True, load_default=None, validate=validate.Length(max=300))
    template_docx_url = fields.Str(required=False, allow_none=True, load_default=None)


class SignatureSchema(Schema):
    label = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    text = fields.Str(required=True, validate=validate.Length(min=1))
    order_index = fields.Int(required=False, load_default=0)
