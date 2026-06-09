import pytest


def _setup_user_with_company(client):
    """Inscrit un utilisateur, le vérifie et crée son entreprise. Retourne les headers."""
    r = client.post('/api/auth/register', json={
        'phone': '+237674000099', 'name': 'Test', 'password': 'password123'
    })
    otp = r.get_json()['data']['dev_otp']
    tokens = client.post('/api/auth/verify-otp', json={
        'phone': '+237674000099', 'code': otp, 'purpose': 'registration'
    }).get_json()['data']
    headers = {'Authorization': f'Bearer {tokens["access_token"]}'}

    client.post('/api/company', json={
        'name': 'Ma Boîte', 'currency': 'FCFA', 'phones': ['+237674000099']
    }, headers=headers)
    return headers


def _quote_payload(**kwargs):
    base = {
        'title': 'Devis test',
        'validity_days': 30,
        'items': [
            {'description': 'Prestation A', 'quantity': 2, 'unit_price': 50000, 'unit': 'heure'},
        ],
    }
    base.update(kwargs)
    return base


class TestQuoteCrud:
    def test_create_quote(self, client):
        headers = _setup_user_with_company(client)
        r = client.post('/api/quotes', json=_quote_payload(), headers=headers)
        assert r.status_code == 201
        data = r.get_json()['data']
        assert data['number'].startswith('DEV-')
        assert data['status'] == 'draft'
        assert len(data['items']) == 1
        assert data['total'] == 100000.0

    def test_quote_number_increments(self, client):
        headers = _setup_user_with_company(client)
        r1 = client.post('/api/quotes', json=_quote_payload(), headers=headers)
        r2 = client.post('/api/quotes', json=_quote_payload(), headers=headers)
        n1 = r1.get_json()['data']['number']
        n2 = r2.get_json()['data']['number']
        assert n1 != n2

    def test_list_quotes(self, client):
        headers = _setup_user_with_company(client)
        client.post('/api/quotes', json=_quote_payload(), headers=headers)
        client.post('/api/quotes', json=_quote_payload(title='Devis 2'), headers=headers)
        r = client.get('/api/quotes', headers=headers)
        assert r.status_code == 200
        assert len(r.get_json()['data']) == 2

    def test_filter_by_status(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        client.patch(f'/api/quotes/{q["id"]}/status', json={'status': 'sent'}, headers=headers)
        client.post('/api/quotes', json=_quote_payload(title='Draft'), headers=headers)

        r = client.get('/api/quotes?status=sent', headers=headers)
        assert len(r.get_json()['data']) == 1
        r2 = client.get('/api/quotes?status=draft', headers=headers)
        assert len(r2.get_json()['data']) == 1

    def test_update_quote(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        r = client.put(f'/api/quotes/{q["id"]}', json={'title': 'Titre modifié'}, headers=headers)
        assert r.status_code == 200
        assert r.get_json()['data']['title'] == 'Titre modifié'

    def test_cannot_update_accepted_quote(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        client.patch(f'/api/quotes/{q["id"]}/status', json={'status': 'accepted'}, headers=headers)
        r = client.put(f'/api/quotes/{q["id"]}', json={'title': 'Tentative'}, headers=headers)
        assert r.status_code == 409

    def test_delete_quote(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        r = client.delete(f'/api/quotes/{q["id"]}', headers=headers)
        assert r.status_code == 204

    def test_duplicate_quote(self, client):
        headers = _setup_user_with_company(client)
        q = client.post('/api/quotes', json=_quote_payload(), headers=headers).get_json()['data']
        r = client.post(f'/api/quotes/{q["id"]}/duplicate', headers=headers)
        assert r.status_code == 201
        copy = r.get_json()['data']
        assert copy['number'] != q['number']
        assert 'Copie' in copy['title']
        assert copy['total'] == q['total']


class TestTotals:
    def test_tax_computed_correctly(self, client):
        headers = _setup_user_with_company(client)
        r = client.post('/api/quotes', json=_quote_payload(
            tax_rate=19.25,
            items=[{'description': 'Service', 'quantity': 1, 'unit_price': 100000}],
        ), headers=headers)
        data = r.get_json()['data']
        assert data['subtotal'] == 100000.0
        assert abs(data['tax_amount'] - 19250.0) < 0.01
        assert abs(data['total'] - 119250.0) < 0.01
