from functools import wraps
from flask import request, g
from app.services.token_service import TokenService
from app.utils.errors import UnauthorizedError


def _extract_bearer_token():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        raise UnauthorizedError('Token manquant ou mal formé.')
    return auth_header[7:]


def login_required(f):
    """Vérifie le token d'accès JWT et injecte l'utilisateur dans g.current_user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        raw_token = _extract_bearer_token()
        user = TokenService.validate_access_token(raw_token)
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    return g.get('current_user')
