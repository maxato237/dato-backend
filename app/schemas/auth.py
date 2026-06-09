from marshmallow import Schema, fields, validate


class RegisterSchema(Schema):
    phone = fields.Str(required=True, validate=validate.Regexp(r'^\+?\d{8,15}$', error='Numéro de téléphone invalide.'))
    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    password = fields.Str(required=True, validate=validate.Length(min=8, error='Le mot de passe doit contenir au moins 8 caractères.'), load_only=True)
    email = fields.Email(required=False, allow_none=True, load_default=None)


class LoginSchema(Schema):
    identifier = fields.Str(required=True)
    password = fields.Str(required=True, load_only=True)


class VerifyOtpSchema(Schema):
    phone = fields.Str(required=True)
    code = fields.Str(required=True, validate=validate.Length(equal=6))
    purpose = fields.Str(required=True, validate=validate.OneOf(['registration', 'reset']))


class ResendOtpSchema(Schema):
    phone = fields.Str(required=True)
    purpose = fields.Str(required=True, validate=validate.OneOf(['registration', 'reset']))


class ForgotPasswordSchema(Schema):
    identifier = fields.Str(required=True)


class ResetPasswordSchema(Schema):
    phone = fields.Str(required=True)
    new_password = fields.Str(required=True, validate=validate.Length(min=8), load_only=True)


class ChangePasswordSchema(Schema):
    current_password = fields.Str(required=True, load_only=True)
    new_password = fields.Str(required=True, validate=validate.Length(min=8), load_only=True)


class UpdateProfileSchema(Schema):
    name = fields.Str(required=False, validate=validate.Length(min=2, max=100))
    email = fields.Email(required=False, allow_none=True)


class RefreshSchema(Schema):
    refresh_token = fields.Str(required=True)
