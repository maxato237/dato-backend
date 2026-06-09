from flask import jsonify


def success(data=None, message=None, status_code=200):
    body = {'success': True}
    if message:
        body['message'] = message
    if data is not None:
        body['data'] = data
    return jsonify(body), status_code


def created(data=None, message=None):
    return success(data=data, message=message, status_code=201)


def no_content():
    return '', 204


def error(message, status_code=400, errors=None):
    body = {'success': False, 'message': message}
    if errors:
        body['errors'] = errors
    return jsonify(body), status_code
