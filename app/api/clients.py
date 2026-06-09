from flask import Blueprint, request, g

from app.extensions import db
from app.models.client import Client
from app.models.company import Company
from app.schemas.client import ClientSchema
from app.utils.auth import login_required
from app.utils.errors import NotFoundError
from app.utils.responses import success, created, no_content

clients_bp = Blueprint('clients', __name__)


def _company_or_404(user):
    company = Company.query.filter_by(user_id=user.id).first()
    if not company:
        raise NotFoundError('Entreprise')
    return company


def _client_or_404(company, client_id):
    client = Client.query.filter_by(id=client_id, company_id=company.id).first()
    if not client:
        raise NotFoundError('Client')
    return client


@clients_bp.get('')
@login_required
def list_clients():
    company = _company_or_404(g.current_user)
    search = request.args.get('q', '').strip()
    query = Client.query.filter_by(company_id=company.id)
    if search:
        query = query.filter(Client.name.ilike(f'%{search}%'))
    clients = query.order_by(Client.name).all()
    return success(data=[c.to_dict() for c in clients])


@clients_bp.post('')
@login_required
def create_client():
    company = _company_or_404(g.current_user)
    data = ClientSchema().load(request.get_json(silent=True) or {})
    client = Client(company_id=company.id, **data)
    db.session.add(client)
    db.session.commit()
    return created(data=client.to_dict())


@clients_bp.get('/<uuid:client_id>')
@login_required
def get_client(client_id):
    company = _company_or_404(g.current_user)
    client = _client_or_404(company, client_id)
    return success(data=client.to_dict())


@clients_bp.put('/<uuid:client_id>')
@login_required
def update_client(client_id):
    company = _company_or_404(g.current_user)
    client = _client_or_404(company, client_id)
    data = ClientSchema().load(request.get_json(silent=True) or {}, partial=True)
    for key, value in data.items():
        setattr(client, key, value)
    db.session.commit()
    return success(data=client.to_dict())


@clients_bp.delete('/<uuid:client_id>')
@login_required
def delete_client(client_id):
    company = _company_or_404(g.current_user)
    client = _client_or_404(company, client_id)
    db.session.delete(client)
    db.session.commit()
    return no_content()
