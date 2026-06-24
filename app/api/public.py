"""Routes publiques — accessibles sans authentification."""
from flask import Blueprint

from app.models.quote import Quote
from app.utils.errors import NotFoundError
from app.utils.responses import success

public_bp = Blueprint('public', __name__)


@public_bp.get('/p/<uuid:share_token>')
def public_quote(share_token):
    quote = Quote.query.filter_by(share_token=share_token).first()
    # Lien inconnu OU révoqué → 404 indifférencié (on ne divulgue pas l'existence).
    if not quote or not quote.share_enabled:
        raise NotFoundError('Devis')
    data = quote.to_dict()
    data['company'] = quote.company.to_dict(include_signatures=True)
    return success(data=data)
