import uuid
from datetime import datetime, timezone

from flask import Blueprint, request, g, send_file, current_app
import io

from app.extensions import db
from app.models.company import Company
from app.models.quote import Quote, QuoteItem
from app.schemas.quote import QuoteCreateSchema, QuoteUpdateSchema, QuoteStatusSchema
from app.services.pdf_service import generate_quote_pdf
from app.utils.auth import login_required
from app.utils.errors import NotFoundError, ApiError
from app.utils.responses import success, created, no_content

quotes_bp = Blueprint('quotes', __name__)


def _company_or_404(user):
    company = Company.query.filter_by(user_id=user.id).first()
    if not company:
        raise NotFoundError('Entreprise')
    return company


def _quote_or_404(company, quote_id):
    quote = Quote.query.filter_by(id=quote_id, company_id=company.id).first()
    if not quote:
        raise NotFoundError('Devis')
    return quote


def _public_url(share_token) -> str:
    """URL publique joignable (ex. http://192.168.1.128:5000/p/<token>),
    construite depuis l'hôte de la requête pour rester valable sur le réseau local."""
    return f"{request.host_url.rstrip('/')}/p/{share_token}"


def _next_quote_number(company) -> str:
    from datetime import date
    year = date.today().year
    prefix = f'DEV-{year}-'
    last = (
        Quote.query
        .filter(Quote.company_id == company.id, Quote.number.like(f'{prefix}%'))
        .order_by(Quote.created_at.desc())
        .first()
    )
    if last:
        try:
            seq = int(last.number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f'{prefix}{seq:03d}'


def _apply_items(quote: Quote, items_data: list):
    for existing in list(quote.items):
        db.session.delete(existing)
    db.session.flush()

    new_items = []
    for i, item_data in enumerate(items_data):
        item = QuoteItem(
            quote_id=quote.id,
            product_id=item_data.get('product_id'),
            description=item_data['description'],
            quantity=item_data['quantity'],
            unit_price=item_data['unit_price'],
            unit=item_data.get('unit'),
            order_index=item_data.get('order_index', i),
        )
        item.compute_total()
        db.session.add(item)
        new_items.append(item)

    db.session.flush()
    # Calculer depuis les objets en mémoire — la relation peut être en cache stale
    from decimal import Decimal
    quote.subtotal = sum(item.total for item in new_items)
    quote.tax_amount = quote.subtotal * (quote.tax_rate / Decimal('100'))
    quote.total = quote.subtotal + quote.tax_amount


@quotes_bp.get('')
@login_required
def list_quotes():
    company = _company_or_404(g.current_user)
    status_filter = request.args.get('status')
    search = request.args.get('q', '').strip()

    query = Quote.query.filter_by(company_id=company.id)
    if status_filter:
        if status_filter not in Quote.VALID_STATUSES:
            raise ApiError(f'Statut invalide. Valeurs acceptées : {", ".join(Quote.VALID_STATUSES)}')
        query = query.filter_by(status=status_filter)
    if search:
        query = query.filter(
            db.or_(
                Quote.number.ilike(f'%{search}%'),
                Quote.title.ilike(f'%{search}%'),
            )
        )
    quotes = query.order_by(Quote.created_at.desc()).all()
    return success(data=[q.to_dict(include_items=False) for q in quotes])


@quotes_bp.post('')
@login_required
def create_quote():
    company = _company_or_404(g.current_user)
    data = QuoteCreateSchema().load(request.get_json(silent=True) or {})

    provided_id = data.get('id')
    if provided_id:
        existing = Quote.query.filter_by(id=provided_id, company_id=company.id).first()
        if existing:
            # Rejeu de la file de sync : la création a déjà été appliquée → idempotent.
            return success(data=existing.to_dict())

    quote = Quote(
        company_id=company.id,
        client_id=data.get('client_id'),
        number=data.get('number') or _next_quote_number(company),
        title=data['title'],
        validity_days=data.get('validity_days', 30),
        notes=data.get('notes'),
        tax_rate=data.get('tax_rate', 0),
        document_json=data.get('document_json'),
    )
    if provided_id:
        quote.id = provided_id
    db.session.add(quote)
    db.session.flush()

    _apply_items(quote, data['items'])
    db.session.commit()
    return created(data=quote.to_dict())


@quotes_bp.get('/<uuid:quote_id>')
@login_required
def get_quote(quote_id):
    company = _company_or_404(g.current_user)
    quote = _quote_or_404(company, quote_id)
    return success(data=quote.to_dict())


@quotes_bp.put('/<uuid:quote_id>')
@login_required
def update_quote(quote_id):
    company = _company_or_404(g.current_user)
    quote = _quote_or_404(company, quote_id)

    if quote.status in (Quote.STATUS_ACCEPTED, Quote.STATUS_REJECTED):
        raise ApiError('Un devis accepté ou refusé ne peut plus être modifié.', 409)

    data = QuoteUpdateSchema().load(request.get_json(silent=True) or {})

    if 'title' in data:
        quote.title = data['title']
    if 'client_id' in data:
        quote.client_id = data['client_id']
    if 'validity_days' in data:
        quote.validity_days = data['validity_days']
    if 'notes' in data:
        quote.notes = data['notes']
    if 'tax_rate' in data:
        quote.tax_rate = data['tax_rate']
    if 'document_json' in data:
        quote.document_json = data['document_json']
    if 'items' in data:
        _apply_items(quote, data['items'])

    db.session.commit()
    return success(data=quote.to_dict())


@quotes_bp.patch('/<uuid:quote_id>/status')
@login_required
def update_status(quote_id):
    company = _company_or_404(g.current_user)
    quote = _quote_or_404(company, quote_id)
    data = QuoteStatusSchema().load(request.get_json(silent=True) or {})
    new_status = data['status']

    if new_status == Quote.STATUS_SENT and not quote.sent_at:
        quote.sent_at = datetime.now(timezone.utc)
    quote.status = new_status
    db.session.commit()
    return success(data=quote.to_dict(include_items=False))


@quotes_bp.post('/<uuid:quote_id>/duplicate')
@login_required
def duplicate_quote(quote_id):
    company = _company_or_404(g.current_user)
    original = _quote_or_404(company, quote_id)

    copy = Quote(
        company_id=company.id,
        client_id=original.client_id,
        number=_next_quote_number(company),
        title=f'Copie — {original.title}',
        validity_days=original.validity_days,
        notes=original.notes,
        tax_rate=original.tax_rate,
    )
    db.session.add(copy)
    db.session.flush()

    copied_items = []
    for item in original.items:
        new_item = QuoteItem(
            quote_id=copy.id,
            product_id=item.product_id,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            unit=item.unit,
            order_index=item.order_index,
        )
        new_item.compute_total()
        db.session.add(new_item)
        copied_items.append(new_item)

    db.session.flush()
    from decimal import Decimal
    copy.subtotal = sum(i.total for i in copied_items)
    copy.tax_amount = copy.subtotal * (copy.tax_rate / Decimal('100'))
    copy.total = copy.subtotal + copy.tax_amount
    db.session.commit()
    return created(data=copy.to_dict())


@quotes_bp.delete('/<uuid:quote_id>')
@login_required
def delete_quote(quote_id):
    company = _company_or_404(g.current_user)
    # Idempotent : un rejeu de suppression sur un devis déjà absent reste un 204.
    quote = Quote.query.filter_by(id=quote_id, company_id=company.id).first()
    if quote:
        db.session.delete(quote)
        db.session.commit()
    return no_content()


@quotes_bp.post('/<uuid:quote_id>/share')
@login_required
def enable_share(quote_id):
    """Active (ou réactive) le lien public et le renvoie. Pas de rotation du jeton."""
    company = _company_or_404(g.current_user)
    quote = _quote_or_404(company, quote_id)
    quote.share_enabled = True
    db.session.commit()
    return success(data={
        'share_token': str(quote.share_token),
        'share_enabled': True,
        'public_url': _public_url(quote.share_token),
    })


@quotes_bp.post('/<uuid:quote_id>/share/regenerate')
@login_required
def regenerate_share(quote_id):
    """Génère un NOUVEAU jeton : l'ancien lien devient définitivement invalide."""
    company = _company_or_404(g.current_user)
    quote = _quote_or_404(company, quote_id)
    quote.share_token = uuid.uuid4()
    quote.share_enabled = True
    db.session.commit()
    return success(data={
        'share_token': str(quote.share_token),
        'share_enabled': True,
        'public_url': _public_url(quote.share_token),
    })


@quotes_bp.delete('/<uuid:quote_id>/share')
@login_required
def revoke_share(quote_id):
    """Révoque le lien public : la vue publique renverra 404 (jeton conservé)."""
    company = _company_or_404(g.current_user)
    quote = _quote_or_404(company, quote_id)
    quote.share_enabled = False
    db.session.commit()
    return success(data={'share_token': str(quote.share_token), 'share_enabled': False})


@quotes_bp.get('/<uuid:quote_id>/pdf')
@login_required
def download_pdf(quote_id):
    company = _company_or_404(g.current_user)
    quote = _quote_or_404(company, quote_id)
    pdf_bytes = generate_quote_pdf(quote)
    filename = f'devis-{quote.number}.pdf'
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )


@quotes_bp.post('/pdf')
@login_required
def render_template_pdf():
    """Génère un PDF à partir du modèle Word de l'entreprise, sans persistance.

    Les devis vivent en mémoire côté app (offline-first) ; cet endpoint reçoit
    donc les lignes du tableau déjà formatées et les injecte dans le template
    Word (en-tête / pied de page préservés), puis renvoie le PDF.

    Corps JSON attendu :
        {
          "number": "DEV-001",
          "rows": [
            {"kind": "line", "designation": "...", "qty": "2",
             "pu": "1 000", "pt": "2 000"},
            {"kind": "span", "label": "TOTAL GÉNÉRAL", "amount": "...",
             "bold": true}
          ]
        }

    Renvoie 422 si aucun modèle n'est configuré ou si la génération échoue
    (l'app retombe alors sur son rendu local par défaut).
    """
    company = _company_or_404(g.current_user)
    if not getattr(company, 'template_docx_url', None):
        raise ApiError('Aucun modèle Word configuré pour cette entreprise.', 422)

    payload = request.get_json(silent=True) or {}
    number = str(payload.get('number') or 'devis')

    from app.services.pdf_service import _load_file_bytes
    from app.services.docx_template_service import render_quote_docx, docx_to_pdf

    template_bytes = _load_file_bytes(company.template_docx_url)
    if not template_bytes:
        raise ApiError('Modèle Word introuvable ou inaccessible.', 422)

    try:
        filled = render_quote_docx(template_bytes, payload)
        pdf_bytes = docx_to_pdf(filled)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning('Rendu PDF via template échoué : %s', exc)
        raise ApiError(f'Échec de la génération via le modèle : {exc}', 422)

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'devis-{number}.pdf',
    )
