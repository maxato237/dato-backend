from flask import Blueprint, request, g

from app.extensions import db
from app.models.company import Company, Signature
from app.schemas.company import CompanySchema, SignatureSchema
from app.utils.auth import login_required
from app.utils.errors import NotFoundError, ForbiddenError
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
