import random
import string
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db, bcrypt
from app.models.user import User, OtpCode
from app.utils.errors import ApiError, ConflictError, NotFoundError, UnauthorizedError


class AuthService:
    @staticmethod
    def _generate_otp() -> str:
        return ''.join(random.choices(string.digits, k=6))

    @staticmethod
    def _hash_password(password: str) -> str:
        return bcrypt.generate_password_hash(password).decode('utf-8')

    @staticmethod
    def _check_password(user: User, password: str) -> bool:
        return bcrypt.check_password_hash(user.password_hash, password)

    @staticmethod
    def register(phone: str, name: str, password: str, email: str | None = None) -> tuple[User, str | None]:
        """Crée un utilisateur et génère un OTP de vérification.

        Retourne (user, otp_code). otp_code est None si OTP_IN_RESPONSE est False
        et qu'aucun canal d'envoi n'est configuré (loggé en console uniquement).
        """
        if User.query.filter_by(phone=phone).first():
            raise ConflictError('Ce numéro de téléphone est déjà utilisé.')
        if email and User.query.filter_by(email=email).first():
            raise ConflictError('Cet e-mail est déjà utilisé.')

        user = User(
            phone=phone,
            email=email,
            name=name,
            password_hash=AuthService._hash_password(password),
            is_verified=False,
        )
        db.session.add(user)
        db.session.flush()

        otp = AuthService._create_otp(user, 'registration')
        db.session.commit()

        current_app.logger.info(f'[OTP registration] {phone} → {otp}')
        print(f'\n{"─"*45}')
        print(f'  📱 OTP INSCRIPTION  {phone}')
        print(f'  🔑 Code : {otp}')
        print(f'{"─"*45}\n')
        return user, otp

    @staticmethod
    def verify_otp(phone: str, code: str, purpose: str) -> User:
        user = User.query.filter_by(phone=phone).first()
        if not user:
            raise NotFoundError('Utilisateur')

        otp_record = (
            OtpCode.query
            .filter_by(user_id=user.id, purpose=purpose, used=False)
            .order_by(OtpCode.created_at.desc())
            .first()
        )

        if not otp_record:
            raise ApiError('Aucun code valide trouvé. Veuillez en demander un nouveau.', 400)
        if otp_record.is_expired():
            raise ApiError('Code expiré. Veuillez en demander un nouveau.', 400)
        if otp_record.code != code:
            raise ApiError('Code incorrect.', 400)

        otp_record.used = True
        if purpose == 'registration':
            user.is_verified = True
        db.session.commit()

        return user

    @staticmethod
    def resend_otp(phone: str, purpose: str) -> str:
        user = User.query.filter_by(phone=phone).first()
        if not user:
            raise NotFoundError('Utilisateur')

        otp = AuthService._create_otp(user, purpose)
        db.session.commit()

        current_app.logger.info(f'[OTP resend:{purpose}] {phone} → {otp}')
        print(f'\n{"─"*45}')
        print(f'  📱 OTP RENVOI ({purpose})  {phone}')
        print(f'  🔑 Code : {otp}')
        print(f'{"─"*45}\n')
        return otp

    @staticmethod
    def login(identifier: str, password: str) -> User:
        """identifier peut être le numéro de téléphone ou l'e-mail."""
        user = (
            User.query.filter_by(phone=identifier).first()
            or User.query.filter_by(email=identifier).first()
        )
        if not user or not AuthService._check_password(user, password):
            raise UnauthorizedError('Identifiant ou mot de passe incorrect.')
        if not user.is_active:
            raise UnauthorizedError('Compte désactivé.')
        if not user.is_verified:
            raise UnauthorizedError('Compte non vérifié. Veuillez valider votre code OTP.')
        return user

    @staticmethod
    def initiate_password_reset(identifier: str) -> tuple[User, str]:
        user = (
            User.query.filter_by(phone=identifier).first()
            or User.query.filter_by(email=identifier).first()
        )
        if not user:
            raise NotFoundError('Utilisateur')

        otp = AuthService._create_otp(user, 'reset')
        db.session.commit()

        current_app.logger.info(f'[OTP reset] {identifier} → {otp}')
        print(f'\n{"─"*45}')
        print(f'  📱 OTP RÉINITIALISATION  {identifier}')
        print(f'  🔑 Code : {otp}')
        print(f'{"─"*45}\n')
        return user, otp

    @staticmethod
    def reset_password(phone: str, new_password: str):
        user = User.query.filter_by(phone=phone).first()
        if not user:
            raise NotFoundError('Utilisateur')

        user.password_hash = AuthService._hash_password(new_password)
        db.session.commit()

    @staticmethod
    def change_password(user: User, current_password: str, new_password: str):
        if not AuthService._check_password(user, current_password):
            raise UnauthorizedError('Mot de passe actuel incorrect.')
        user.password_hash = AuthService._hash_password(new_password)
        db.session.commit()

    @staticmethod
    def _create_otp(user: User, purpose: str) -> str:
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=current_app.config.get('OTP_EXPIRES_SECONDS', 600)
        )
        code = AuthService._generate_otp()
        db.session.add(OtpCode(user_id=user.id, code=code, purpose=purpose, expires_at=expires))
        return code
