import json
import pytest


def _register(client, phone='+237674000001', name='Test User', password='password123', email=None):
    payload = {'phone': phone, 'name': name, 'password': password}
    if email:
        payload['email'] = email
    return client.post('/api/auth/register', json=payload)


def _verify(client, phone, otp, purpose='registration'):
    return client.post('/api/auth/verify-otp', json={'phone': phone, 'code': otp, 'purpose': purpose})


def _login(client, identifier, password='password123'):
    return client.post('/api/auth/login', json={'identifier': identifier, 'password': password})


def _auth_header(token):
    return {'Authorization': f'Bearer {token}'}


class TestRegister:
    def test_register_success(self, client):
        r = _register(client)
        assert r.status_code == 201
        data = r.get_json()
        assert data['success'] is True
        assert 'dev_otp' in data['data']
        assert len(data['data']['dev_otp']) == 6

    def test_register_duplicate_phone(self, client):
        _register(client)
        r = _register(client)
        assert r.status_code == 409

    def test_register_invalid_phone(self, client):
        r = _register(client, phone='abc')
        assert r.status_code == 422

    def test_register_short_password(self, client):
        r = _register(client, password='short')
        assert r.status_code == 422


class TestVerifyOtp:
    def test_verify_otp_success(self, client):
        r = _register(client)
        otp = r.get_json()['data']['dev_otp']
        r2 = _verify(client, '+237674000001', otp)
        assert r2.status_code == 200
        data = r2.get_json()['data']
        assert 'access_token' in data
        assert 'refresh_token' in data
        assert data['user']['phone'] == '+237674000001'
        assert data['user']['is_verified'] is True

    def test_verify_wrong_code(self, client):
        _register(client)
        r = _verify(client, '+237674000001', '000000')
        assert r.status_code == 400

    def test_verify_unknown_phone(self, client):
        r = _verify(client, '+237000000000', '123456')
        assert r.status_code == 404


class TestLogin:
    def _registered_user(self, client):
        r = _register(client)
        otp = r.get_json()['data']['dev_otp']
        _verify(client, '+237674000001', otp)

    def test_login_success(self, client):
        self._registered_user(client)
        r = _login(client, '+237674000001')
        assert r.status_code == 200
        assert 'access_token' in r.get_json()['data']

    def test_login_wrong_password(self, client):
        self._registered_user(client)
        r = _login(client, '+237674000001', 'wrongpass')
        assert r.status_code == 401

    def test_login_unverified_user(self, client):
        _register(client)
        r = _login(client, '+237674000001')
        assert r.status_code == 401


class TestTokenRefresh:
    def test_refresh_success(self, client):
        r = _register(client)
        otp = r.get_json()['data']['dev_otp']
        tokens = _verify(client, '+237674000001', otp).get_json()['data']
        r2 = client.post('/api/auth/refresh', json={'refresh_token': tokens['refresh_token']})
        assert r2.status_code == 200
        assert 'access_token' in r2.get_json()['data']

    def test_refresh_invalid_token(self, client):
        r = client.post('/api/auth/refresh', json={'refresh_token': 'invalid.token.here'})
        assert r.status_code == 401


class TestLogout:
    def test_logout_revokes_tokens(self, client):
        r = _register(client)
        otp = r.get_json()['data']['dev_otp']
        tokens = _verify(client, '+237674000001', otp).get_json()['data']
        headers = _auth_header(tokens['access_token'])

        # Logout
        r2 = client.post('/api/auth/logout', headers=headers)
        assert r2.status_code == 204

        # Le token est maintenant révoqué
        r3 = client.get('/api/auth/me', headers=headers)
        assert r3.status_code == 401

    def test_logout_requires_auth(self, client):
        r = client.post('/api/auth/logout')
        assert r.status_code == 401


class TestMe:
    def test_me_returns_user(self, client):
        r = _register(client)
        otp = r.get_json()['data']['dev_otp']
        tokens = _verify(client, '+237674000001', otp).get_json()['data']
        r2 = client.get('/api/auth/me', headers=_auth_header(tokens['access_token']))
        assert r2.status_code == 200
        assert r2.get_json()['data']['user']['phone'] == '+237674000001'
