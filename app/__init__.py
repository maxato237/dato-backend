import os

from flask import Flask

from .config import config
from .extensions import db, migrate, bcrypt, cors


def create_app(config_name: str = 'development') -> Flask:
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # S'assurer que le dossier d'upload existe.
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    cors.init_app(
        app,
        resources={r'/api/*': {'origins': app.config.get('CORS_ORIGINS', '*')}},
        supports_credentials=True,
    )

    # Importer les modèles pour que SQLAlchemy et Flask-Migrate les détectent.
    # Ne pas pousser d'app context ici — l'engine doit rester créé paresseusement.
    from .models import User, OtpCode, Token, Company, Signature, Client, Product, Quote, QuoteItem  # noqa: F401

    # Blueprints
    from .api.auth import auth_bp
    from .api.company import company_bp
    from .api.clients import clients_bp
    from .api.quotes import quotes_bp
    from .api.library import library_bp
    from .api.dashboard import dashboard_bp
    from .api.public import public_bp
    from .api.uploads import uploads_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(company_bp, url_prefix='/api/company')
    app.register_blueprint(clients_bp, url_prefix='/api/clients')
    app.register_blueprint(quotes_bp, url_prefix='/api/quotes')
    app.register_blueprint(library_bp, url_prefix='/api/products')
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(public_bp)
    app.register_blueprint(uploads_bp)  # routes complètes : /api/uploads, /uploads/<f>


    with app.app_context():
        db.create_all()
        _ensure_dev_columns(app)

    # Gestionnaires d'erreurs
    from .utils.errors import register_error_handlers
    register_error_handlers(app)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'service': 'dato-backend'}

    return app


def _ensure_dev_columns(app):
    """Ajoute de façon idempotente les colonnes récentes à une base PostgreSQL
    existante (dev/prod). `db.create_all()` ne modifie pas les tables déjà
    créées : ce filet évite d'avoir à dropper la base en développement.

    SQLite (tests) est ignoré : `create_all()` crée déjà toutes les colonnes.
    """
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('postgresql'):
        return

    from sqlalchemy import text

    statements = [
        'ALTER TABLE companies ADD COLUMN IF NOT EXISTS address VARCHAR(200)',
        'ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500)',
        'ALTER TABLE companies ADD COLUMN IF NOT EXISTS header_image_url VARCHAR(500)',
        'ALTER TABLE companies ADD COLUMN IF NOT EXISTS footer_image_url VARCHAR(500)',
        'ALTER TABLE companies ADD COLUMN IF NOT EXISTS location VARCHAR(300)',
    ]
    for stmt in statements:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception:  # noqa: BLE001 — best-effort, on continue
            db.session.rollback()
