import os
import tempfile

# Racine du projet backend (dossier qui contient `app/`).
_BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class BaseConfig:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'dev-jwt-secret-key')
    JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES', 3600))
    JWT_REFRESH_TOKEN_EXPIRES = int(os.getenv('JWT_REFRESH_TOKEN_EXPIRES', 2592000))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Postgres managé (Sevalla/Supabase) ferme les connexions inactives.
    # pool_pre_ping teste la connexion avant chaque usage et la recrée si
    # elle est morte ; pool_recycle renouvelle les connexions trop vieilles.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
    }
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')
    OTP_EXPIRES_SECONDS = 600  # 10 minutes
    # Mettre REQUIRE_OTP=1 dans l'env quand Twilio est configuré.
    # Par défaut False : inscription directement vérifiée, pas d'OTP envoyé.
    REQUIRE_OTP = os.getenv('REQUIRE_OTP', '0') == '1'

    # Upload d'images (logo, couverture d'en-tête, bannière de pied de page).
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', os.path.join(_BASE_DIR, 'uploads'))
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH', 5 * 1024 * 1024))  # 5 Mo
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

    # Stockage des images : Supabase Storage si configuré, sinon disque local.
    SUPABASE_URL = os.getenv('SUPABASE_URL', '')
    SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
    SUPABASE_STORAGE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'DATO_PROFIL_PDP_PDC')


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:password@localhost:5432/dato_dev',
    )
    OTP_IN_RESPONSE = True  # renvoie le code OTP dans la réponse en dev


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:?check_same_thread=False'
    OTP_IN_RESPONSE = True
    REQUIRE_OTP = True  # tests gardent le flux OTP complet (pas de vrai SMS)
    JWT_ACCESS_TOKEN_EXPIRES = 3600
    JWT_REFRESH_TOKEN_EXPIRES = 2592000
    # Uploads isolés dans un dossier temporaire (n'altère pas backend/uploads).
    UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), 'dato_test_uploads')


class ProductionConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    OTP_IN_RESPONSE = False


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
