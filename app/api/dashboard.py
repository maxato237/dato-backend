from flask import Blueprint, g
from sqlalchemy import func

from app.extensions import db
from app.models.company import Company
from app.models.quote import Quote
from app.utils.auth import login_required
from app.utils.errors import NotFoundError
from app.utils.responses import success

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.get('/stats')
@login_required
def stats():
    company = Company.query.filter_by(user_id=g.current_user.id).first()
    if not company:
        raise NotFoundError('Entreprise')

    rows = (
        db.session.query(Quote.status, func.count(Quote.id), func.coalesce(func.sum(Quote.total), 0))
        .filter(Quote.company_id == company.id)
        .group_by(Quote.status)
        .all()
    )

    counts = {s: 0 for s in Quote.VALID_STATUSES}
    amounts = {s: 0.0 for s in Quote.VALID_STATUSES}
    for status, count, amount in rows:
        counts[status] = count
        amounts[status] = float(amount)

    total_quotes = sum(counts.values())
    total_revenue = amounts[Quote.STATUS_ACCEPTED]

    recent = (
        Quote.query.filter_by(company_id=company.id)
        .order_by(Quote.created_at.desc())
        .limit(5)
        .all()
    )

    return success(data={
        'total_quotes': total_quotes,
        'total_revenue': total_revenue,
        'by_status': {
            status: {'count': counts[status], 'amount': amounts[status]}
            for status in Quote.VALID_STATUSES
        },
        'recent_quotes': [q.to_dict(include_items=False) for q in recent],
        'currency': company.currency,
    })
