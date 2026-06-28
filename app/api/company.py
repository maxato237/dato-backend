import io

from flask import Blueprint, request, g, current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.company import Company, Signature
from app.schemas.company import CompanySchema, SignatureSchema
from app.utils.auth import login_required
from app.utils.errors import NotFoundError, ForbiddenError, ApiError
from app.utils.responses import success, created, no_content

company_bp = Blueprint('company', __name__)


def _get_company_or_404(user):
    company = Company.query.filter_by(user_id=user.id).first()
    if not company:
        raise NotFoundError('Entreprise')
    return company


@company_bp.get('')
@login_required
def get_company():
    company = _get_company_or_404(g.current_user)
    return success(data=company.to_dict(include_signatures=True))


@company_bp.post('')
@login_required
def create_company():
    if Company.query.filter_by(user_id=g.current_user.id).first():
        from app.utils.errors import ConflictError
        raise ConflictError('Vous avez déjà une entreprise enregistrée.')
    data = CompanySchema().load(request.get_json(silent=True) or {})
    company = Company(user_id=g.current_user.id, **data)
    db.session.add(company)
    db.session.commit()
    return created(data=company.to_dict())


@company_bp.put('')
@login_required
def update_company():
    company = _get_company_or_404(g.current_user)
    data = CompanySchema().load(request.get_json(silent=True) or {}, partial=True)
    for key, value in data.items():
        setattr(company, key, value)
    db.session.commit()
    return success(data=company.to_dict(include_signatures=True))


# ── Modèle Word (.docx) ────────────────────────────────────────────────────

@company_bp.post('/template')
@login_required
def upload_template():
    """Upload du modèle Word (.doc/.docx) utilisé pour générer les PDF de devis.

    Accepte uniquement les fichiers .doc et .docx.
    Sauvegarde le fichier via storage_service et met à jour company.template_docx_url.
    """
    if 'file' not in request.files:
        raise ApiError('Aucun fichier fourni (champ « file » manquant).', 400)

    file = request.files['file']
    if not file or not file.filename:
        raise ApiError('Fichier vide.', 400)

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in {'doc', 'docx'}:
        raise ApiError(
            'Format non supporté. Seuls les fichiers .doc et .docx sont acceptés.', 400
        )

    company = _get_company_or_404(g.current_user)

    # Normalisation best-effort : ré-ancre les images de l'en-tête/pied de page
    # « à la page » pour un rendu PDF identique Word ↔ LibreOffice. Ne s'exécute
    # que là où Word est disponible (poste/worker Windows) ; sur l'hébergeur
    # Linux (sans Word), l'exception est avalée et on stocke le fichier d'origine.
    raw = file.read()
    out = raw
    if ext == 'docx':
        try:
            from app.services.template_normalizer import normalize_letterhead
            out = normalize_letterhead(raw)
            current_app.logger.info('Modèle %s normalisé (ancrage page).', file.filename)
        except Exception as exc:  # noqa: BLE001 — best-effort, jamais bloquant
            current_app.logger.info(
                'Normalisation du modèle ignorée (%s) : %s', type(exc).__name__, exc)
            out = raw

    storable = FileStorage(io.BytesIO(out), filename=file.filename,
                           content_type=file.mimetype)

    from app.services.storage_service import save_image
    url = save_image(storable, ext, folder='templates')

    company.template_docx_url = url
    db.session.commit()

    return success(data={'url': url, 'template_docx_url': url})


@company_bp.delete('/template')
@login_required
def delete_template():
    """Retire le modèle Word de l'entreprise (remet template_docx_url à NULL)."""
    company = _get_company_or_404(g.current_user)
    company.template_docx_url = None
    db.session.commit()
    return no_content()


# ── Signatures ─────────────────────────────────────────────────────────────

@company_bp.get('/signatures')
@login_required
def list_signatures():
    company = _get_company_or_404(g.current_user)
    return success(data=[s.to_dict() for s in company.signatures])


@company_bp.post('/signatures')
@login_required
def create_signature():
    company = _get_company_or_404(g.current_user)
    data = SignatureSchema().load(request.get_json(silent=True) or {})
    sig = Signature(company_id=company.id, **data)
    db.session.add(sig)
    db.session.commit()
    return created(data=sig.to_dict())


@company_bp.put('/signatures/<uuid:sig_id>')
@login_required
def update_signature(sig_id):
    company = _get_company_or_404(g.current_user)
    sig = Signature.query.get(sig_id)
    if not sig or str(sig.company_id) != str(company.id):
        raise NotFoundError('Signature')
    data = SignatureSchema().load(request.get_json(silent=True) or {}, partial=True)
    for key, value in data.items():
        setattr(sig, key, value)
    db.session.commit()
    return success(data=sig.to_dict())


@company_bp.delete('/signatures/<uuid:sig_id>')
@login_required
def delete_signature(sig_id):
    company = _get_company_or_404(g.current_user)
    sig = Signature.query.get(sig_id)
    if not sig or str(sig.company_id) != str(company.id):
        raise NotFoundError('Signature')
    db.session.delete(sig)
    db.session.commit()
    return no_content()
