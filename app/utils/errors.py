from flask import jsonify
from marshmallow import ValidationError


class ApiError(Exception):
    def __init__(self, message, status_code=400, errors=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors

    def to_response(self):
        body = {'success': False, 'message': self.message}
        if self.errors:
            body['errors'] = self.errors
        return jsonify(body), self.status_code


class NotFoundError(ApiError):
    def __init__(self, resource='Ressource'):
        super().__init__(f'{resource} introuvable.', status_code=404)


class UnauthorizedError(ApiError):
    def __init__(self, message='Non autorisé.'):
        super().__init__(message, status_code=401)


class ForbiddenError(ApiError):
    def __init__(self, message='Accès refusé.'):
        super().__init__(message, status_code=403)


class ConflictError(ApiError):
    def __init__(self, message):
        super().__init__(message, status_code=409)


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return e.to_response()

    @app.errorhandler(ValidationError)
    def handle_validation_error(e):
        return jsonify({'success': False, 'message': 'Données invalides.', 'errors': e.messages}), 422

    @app.errorhandler(404)
    def handle_404(_e):
        return jsonify({'success': False, 'message': 'Route introuvable.'}), 404

    @app.errorhandler(405)
    def handle_405(_e):
        return jsonify({'success': False, 'message': 'Méthode non autorisée.'}), 405

    @app.errorhandler(413)
    def handle_413(_e):
        return jsonify({'success': False, 'message': 'Fichier trop volumineux (max 5 Mo).'}), 413

    @app.errorhandler(500)
    def handle_500(_e):
        return jsonify({'success': False, 'message': 'Erreur interne du serveur.'}), 500
