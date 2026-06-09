import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app

from app.extensions import db
from app.models.token import Token
from app.models.user import User
from app.utils.errors import UnauthorizedError


class TokenService:
    @staticmethod
    def _secret():
        return current_app.config['JWT_SECRET_KEY']

    @staticmethod
    def _encode(payload: dict) -> str:
        return jwt.encode(payload, TokenService._secret(), algorithm='HS256')

    @staticmethod
    def _decode(token: str) -> dict:
        try:
            return jwt.decode(token, TokenService._secret(), algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            raise UnauthorizedError('Token expiré.')
        except jwt.InvalidTokenError:
            raise UnauthorizedError('Token invalide.')

    @staticmethod
    def create_token_pair(user: User) -> dict:
        now = datetime.now(timezone.utc)
        access_expires = now + timedelta(seconds=current_app.config['JWT_ACCESS_TOKEN_EXPIRES'])
        refresh_expires = now + timedelta(seconds=current_app.config['JWT_REFRESH_TOKEN_EXPIRES'])

        access_jti = uuid.uuid4()
        refresh_jti = uuid.uuid4()

        access_payload = {
            'sub': str(user.id),
            'jti': str(access_jti),
            'type': 'access',
            'iat': now,
            'exp': access_expires,
        }
        refresh_payload = {
            'sub': str(user.id),
            'jti': str(refresh_jti),
            'type': 'refresh',
            'iat': now,
            'exp': refresh_expires,
        }

        db.session.add(Token(jti=access_jti, user_id=user.id, token_type='access', expires_at=access_expires))
        db.session.add(Token(jti=refresh_jti, user_id=user.id, token_type='refresh', expires_at=refresh_expires))
        db.session.commit()

        return {
            'access_token': TokenService._encode(access_payload),
            'refresh_token': TokenService._encode(refresh_payload),
            'token_type': 'Bearer',
            'expires_in': current_app.config['JWT_ACCESS_TOKEN_EXPIRES'],
        }

    @staticmethod
    def validate_access_token(raw_token: str) -> User:
        payload = TokenService._decode(raw_token)
        if payload.get('type') != 'access':
            raise UnauthorizedError('Token de type incorrect.')

        jti = uuid.UUID(payload['jti'])
        token_record = Token.query.filter_by(jti=jti).first()
        if not token_record or token_record.revoked:
            raise UnauthorizedError('Token révoqué ou inconnu.')

        user = db.session.get(User, uuid.UUID(payload['sub']))
        if not user or not user.is_active:
            raise UnauthorizedError('Utilisateur introuvable ou désactivé.')
        return user

    @staticmethod
    def refresh_access_token(raw_refresh_token: str) -> dict:
        payload = TokenService._decode(raw_refresh_token)
        if payload.get('type') != 'refresh':
            raise UnauthorizedError('Token de type incorrect.')

        jti = uuid.UUID(payload['jti'])
        token_record = Token.query.filter_by(jti=jti).first()
        if not token_record or token_record.revoked:
            raise UnauthorizedError('Refresh token révoqué ou inconnu.')

        user = db.session.get(User, uuid.UUID(payload['sub']))
        if not user or not user.is_active:
            raise UnauthorizedError('Utilisateur introuvable ou désactivé.')

        # Rotation du refresh token
        token_record.revoke()

        return TokenService.create_token_pair(user)

    @staticmethod
    def revoke_all_for_user(user: User):
        Token.query.filter_by(user_id=user.id, revoked=False).update({'revoked': True, 'revoked_at': datetime.now(timezone.utc)})
        db.session.commit()

    @staticmethod
    def revoke_access_token(raw_token: str):
        try:
            payload = TokenService._decode(raw_token)
            jti = uuid.UUID(payload['jti'])
            token_record = Token.query.filter_by(jti=jti).first()
            if token_record:
                token_record.revoke()
                db.session.commit()
        except UnauthorizedError:
            pass  # token déjà expiré, rien à révoquer
