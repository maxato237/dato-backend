from flask import Blueprint, request, g, current_app

from app.extensions import db
from app.schemas.auth import (
    RegisterSchema, LoginSchema, VerifyOtpSchema, ResendOtpSchema,
    ForgotPasswordSchema, ResetPasswordSchema, ChangePasswordSchema,
    UpdateProfileSchema, RefreshSchema,
)
from app.services.auth_service import AuthService
from app.services.token_service import TokenService
from app.utils.auth import login_required
from app.utils.errors import UnauthorizedError
from app.utils.responses import success, created, no_content, error

auth_bp = Blueprint('auth', __name__)


@auth_bp.post('/register')
def register():
    data = RegisterSchema().load(request.get_json(silent=True) or {})
    user, otp = AuthService.register(
        phone=data['phone'],
        name=data['name'],
        password=data['password'],
        email=data.get('email'),
    )
    body = {'message': 'Compte créé. Veuillez vérifier votre code OTP.', 'phone': user.phone}
    if current_app.config.get('OTP_IN_RESPONSE'):
        body['dev_otp'] = otp
    return created(data=body)


@auth_bp.post('/verify-otp')
def verify_otp():
    data = VerifyOtpSchema().load(request.get_json(silent=True) or {})
    user = AuthService.verify_otp(phone=data['phone'], code=data['code'], purpose=data['purpose'])
    tokens = TokenService.create_token_pair(user)
    return success(data={**tokens, 'user': user.to_dict()})


@auth_bp.post('/resend-otp')
def resend_otp():
    data = ResendOtpSchema().load(request.get_json(silent=True) or {})
    otp = AuthService.resend_otp(phone=data['phone'], purpose=data['purpose'])
    body = {'message': 'Code renvoyé.'}
    if current_app.config.get('OTP_IN_RESPONSE'):
        body['dev_otp'] = otp
    return success(data=body)


@auth_bp.post('/login')
def login():
    data = LoginSchema().load(request.get_json(silent=True) or {})
    user = AuthService.login(identifier=data['identifier'], password=data['password'])
    tokens = TokenService.create_token_pair(user)
    return success(data={**tokens, 'user': user.to_dict()})


@auth_bp.post('/refresh')
def refresh():
    data = RefreshSchema().load(request.get_json(silent=True) or {})
    tokens = TokenService.refresh_access_token(data['refresh_token'])
    return success(data=tokens)


@auth_bp.post('/logout')
@login_required
def logout():
    TokenService.revoke_all_for_user(g.current_user)
    return no_content()


@auth_bp.post('/forgot-password')
def forgot_password():
    data = ForgotPasswordSchema().load(request.get_json(silent=True) or {})
    user, otp = AuthService.initiate_password_reset(identifier=data['identifier'])
    body = {'message': 'Code de réinitialisation envoyé.', 'phone': user.phone}
    if current_app.config.get('OTP_IN_RESPONSE'):
        body['dev_otp'] = otp
    return success(data=body)


@auth_bp.post('/reset-password')
def reset_password():
    data = ResetPasswordSchema().load(request.get_json(silent=True) or {})
    AuthService.reset_password(phone=data['phone'], new_password=data['new_password'])
    return success(message='Mot de passe réinitialisé.')


@auth_bp.get('/me')
@login_required
def me():
    return success(data={'user': g.current_user.to_dict()})


@auth_bp.put('/me')
@login_required
def update_profile():
    data = UpdateProfileSchema().load(request.get_json(silent=True) or {})
    user = g.current_user
    if 'name' in data:
        user.name = data['name']
    if 'email' in data:
        user.email = data['email']
    db.session.commit()
    return success(data={'user': user.to_dict()})


@auth_bp.put('/change-password')
@login_required
def change_password():
    data = ChangePasswordSchema().load(request.get_json(silent=True) or {})
    AuthService.change_password(
        user=g.current_user,
        current_password=data['current_password'],
        new_password=data['new_password'],
    )
    TokenService.revoke_all_for_user(g.current_user)
    return success(message='Mot de passe modifié. Veuillez vous reconnecter.')
