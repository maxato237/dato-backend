from flask import Blueprint, request, g

from app.extensions import db
from app.models.company import Company
from app.models.product import Product
from app.schemas.product import ProductSchema
from app.utils.auth import login_required
from app.utils.errors import NotFoundError
from app.utils.responses import success, created, no_content

library_bp = Blueprint('library', __name__)


def _company_or_404(user):
    company = Company.query.filter_by(user_id=user.id).first()
    if not company:
        raise NotFoundError('Entreprise')
    return company


def _product_or_404(company, product_id):
    product = Product.query.filter_by(id=product_id, company_id=company.id).first()
    if not product:
        raise NotFoundError('Produit/service')
    return product


@library_bp.get('')
@login_required
def list_products():
    company = _company_or_404(g.current_user)
    search = request.args.get('q', '').strip()
    query = Product.query.filter_by(company_id=company.id)
    if search:
        query = query.filter(Product.name.ilike(f'%{search}%'))
    products = query.order_by(Product.name).all()
    return success(data=[p.to_dict() for p in products])


@library_bp.post('')
@login_required
def create_product():
    company = _company_or_404(g.current_user)
    data = ProductSchema().load(request.get_json(silent=True) or {})
    product = Product(company_id=company.id, **data)
    db.session.add(product)
    db.session.commit()
    return created(data=product.to_dict())


@library_bp.get('/<uuid:product_id>')
@login_required
def get_product(product_id):
    company = _company_or_404(g.current_user)
    product = _product_or_404(company, product_id)
    return success(data=product.to_dict())


@library_bp.put('/<uuid:product_id>')
@login_required
def update_product(product_id):
    company = _company_or_404(g.current_user)
    product = _product_or_404(company, product_id)
    data = ProductSchema().load(request.get_json(silent=True) or {}, partial=True)
    for key, value in data.items():
        setattr(product, key, value)
    db.session.commit()
    return success(data=product.to_dict())


@library_bp.delete('/<uuid:product_id>')
@login_required
def delete_product(product_id):
    company = _company_or_404(g.current_user)
    product = _product_or_404(company, product_id)
    db.session.delete(product)
    db.session.commit()
    return no_content()
